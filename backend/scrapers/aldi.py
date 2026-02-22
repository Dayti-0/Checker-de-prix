import asyncio
import logging
import re

from backend.models import ScrapedProduct
from backend.scrapers.base import BaseScraper
from backend.scrapers.browser import create_stealth_browser, accept_cookies

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.aldi.fr/recherche.html?query={query}"


class AldiScraper(BaseScraper):
    store_name = "Aldi"

    async def search(self, query: str) -> list[ScrapedProduct]:
        """Run the synchronous scraper in a thread to avoid asyncio subprocess issues."""
        return await asyncio.to_thread(self._search_sync, query)

    def _search_sync(self, query: str) -> list[ScrapedProduct]:
        """Synchronous Playwright scraping (runs in a thread)."""
        url = SEARCH_URL.format(query=query)
        products: list[ScrapedProduct] = []

        with create_stealth_browser() as (browser, context, page):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                accept_cookies(page)

                # Wait for product tiles (loaded via Algolia client-side)
                try:
                    page.wait_for_selector(".product-tile", timeout=12000)
                except Exception:
                    logger.warning("Aldi: no product tiles for '%s'", query)
                    return products

                page.wait_for_timeout(1000)
                tiles = page.query_selector_all(".product-tile")

                for tile in tiles:
                    try:
                        product = self._parse_tile(tile)
                        if product:
                            products.append(product)
                    except Exception as e:
                        logger.debug("Aldi: tile parse error: %s", e)

            except Exception as e:
                logger.error("Aldi scraper error: %s", e)

        return products

    def _parse_tile(self, tile) -> ScrapedProduct | None:
        # Product name
        name_el = tile.query_selector(
            ".product-tile__content__upper__product-name"
        )
        if not name_el:
            return None
        name = name_el.inner_text().strip()
        if not name:
            return None

        # Brand
        brand_el = tile.query_selector(
            ".product-tile__content__upper__brand-name"
        )
        if brand_el:
            brand = brand_el.inner_text().strip()
            if brand:
                name = f"{name} - {brand}"

        # Price
        price = None
        price_el = tile.query_selector("[data-testid$='tag-current-price-amount']")
        if not price_el:
            price_el = tile.query_selector(".tag__label--price")
        if price_el:
            price_text = price_el.inner_text().strip()
            price = self._parse_price(price_text)

        # Price per unit (e.g. "KG = 0.69")
        price_per_unit = None
        unit_el = tile.query_selector(".tag__marker--base-price")
        if unit_el:
            price_per_unit = unit_el.inner_text().strip()

        # Sales unit (e.g. "1KG")
        sales_unit_el = tile.query_selector(".tag__marker--salesunit")
        if sales_unit_el:
            sales_unit = sales_unit_el.inner_text().strip()
            if price_per_unit:
                price_per_unit = f"{price_per_unit} ({sales_unit})"
            else:
                price_per_unit = sales_unit

        # Image
        image_url = None
        img = tile.query_selector(".product-tile__image-section img")
        if img:
            image_url = img.get_attribute("src")

        # Product URL
        product_url = ""
        link = tile.query_selector("a[href]")
        if link:
            href = link.get_attribute("href")
            if href:
                product_url = (
                    href
                    if href.startswith("http")
                    else f"https://www.aldi.fr{href}"
                )

        return ScrapedProduct(
            name=name,
            price=price,
            price_per_unit=price_per_unit,
            image_url=image_url,
            product_url=product_url,
            store_name=self.store_name,
        )

    @staticmethod
    def _parse_price(text: str) -> float | None:
        """Parse a price string like '2,49' or '0.69' into a float."""
        text = text.replace("\xa0", " ").strip()
        match = re.search(r"(\d+)[.,](\d{1,2})", text)
        if match:
            return float(f"{match.group(1)}.{match.group(2)}")
        match = re.search(r"(\d+)", text)
        if match:
            return float(match.group(1))
        return None

    async def setup_location(self, postal_code: str) -> bool:
        return True
