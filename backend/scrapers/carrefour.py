import asyncio
import json
import logging
import os
import re
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from backend.models import ScrapedProduct
from backend.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.carrefour.fr/s?q={query}"


def _get_proxy_config() -> dict | None:
    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if not proxy_url:
        return None
    parsed = urlparse(proxy_url)
    config: dict = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        config["username"] = parsed.username
    if parsed.password:
        config["password"] = parsed.password
    return config


class CarrefourScraper(BaseScraper):
    store_name = "Carrefour"

    async def search(self, query: str) -> list[ScrapedProduct]:
        return await asyncio.to_thread(self._search_sync, query)

    def _search_sync(self, query: str) -> list[ScrapedProduct]:
        url = SEARCH_URL.format(query=query)
        products: list[ScrapedProduct] = []
        api_data: list[dict] = []
        proxy = _get_proxy_config()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
                proxy=proxy,
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="fr-FR",
                ignore_https_errors=True,
            )
            page = context.new_page()

            # Intercept API responses for structured data
            def handle_response(response):
                try:
                    if "/search" in response.url and response.status == 200:
                        content_type = response.headers.get("content-type", "")
                        if "json" in content_type:
                            data = response.json()
                            if isinstance(data, dict):
                                api_data.append(data)
                except Exception:
                    pass

            page.on("response", handle_response)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)

                # Accept cookies if banner appears
                try:
                    btn = page.locator("#onetrust-accept-btn-handler")
                    btn.click(timeout=4000)
                    time.sleep(0.5)
                except Exception:
                    pass

                # Wait for products to appear
                try:
                    page.wait_for_selector(
                        "[data-testid='product-card-container'], .product-card-list__item, .ds-product-card",
                        timeout=15000,
                    )
                except Exception:
                    logger.warning("Carrefour: no product cards for '%s'", query)

                time.sleep(1.5)

                # Try API data first (more reliable)
                if api_data:
                    products = self._parse_api_data(api_data)

                # Fallback to HTML parsing
                if not products:
                    products = self._parse_html(page)

            except Exception as e:
                logger.error("Carrefour scraper error: %s", e)
            finally:
                browser.close()

        return products

    def _parse_api_data(self, api_responses: list[dict]) -> list[ScrapedProduct]:
        """Parse products from intercepted API JSON responses."""
        products: list[ScrapedProduct] = []
        for data in api_responses:
            items = data.get("data", {}).get("products", [])
            if not items:
                items = data.get("products", [])
            if not items and "hits" in data:
                items = data["hits"]

            for item in items:
                try:
                    name = item.get("title") or item.get("name", "")
                    if not name:
                        continue

                    price = None
                    price_data = item.get("price", {})
                    if isinstance(price_data, dict):
                        price = price_data.get("price") or price_data.get("value")
                    elif isinstance(price_data, (int, float)):
                        price = float(price_data)

                    price_per_unit = None
                    if isinstance(price_data, dict):
                        unit_price = price_data.get("pricePerUnit") or price_data.get("unitPrice")
                        unit = price_data.get("unit", "")
                        if unit_price:
                            price_per_unit = f"{unit_price} €/{unit}" if unit else f"{unit_price} €"

                    image_url = item.get("image") or item.get("imageUrl")
                    if isinstance(image_url, dict):
                        image_url = image_url.get("url")

                    product_url = item.get("url") or item.get("href", "")
                    if product_url and not product_url.startswith("http"):
                        product_url = f"https://www.carrefour.fr{product_url}"

                    products.append(ScrapedProduct(
                        name=name,
                        price=float(price) if price else None,
                        price_per_unit=price_per_unit,
                        image_url=image_url,
                        product_url=product_url,
                        store_name=self.store_name,
                    ))
                except Exception as e:
                    logger.debug("Carrefour API parse error: %s", e)

        return products

    def _parse_html(self, page) -> list[ScrapedProduct]:
        """Fallback: parse product cards from HTML."""
        products: list[ScrapedProduct] = []

        selectors = [
            "[data-testid='product-card-container']",
            ".product-card-list__item",
            ".ds-product-card",
            "li[data-testid]",
        ]

        cards = []
        for sel in selectors:
            cards = page.query_selector_all(sel)
            if cards:
                break

        for card in cards:
            try:
                product = self._parse_card(card)
                if product:
                    products.append(product)
            except Exception as e:
                logger.debug("Carrefour card parse error: %s", e)

        return products

    def _parse_card(self, card) -> ScrapedProduct | None:
        # Product name
        name = None
        for sel in [
            "[data-testid='product-card-title']",
            ".product-card__title",
            ".ds-product-card__title",
            "a[title]",
            "h2",
            "h3",
        ]:
            el = card.query_selector(sel)
            if el:
                name = el.get_attribute("title") or el.inner_text()
                name = name.strip()
                if name:
                    break

        if not name:
            return None

        # Price
        price = None
        for sel in [
            "[data-testid='product-card-price']",
            ".product-card__price",
            ".ds-product-card__price",
            ".product-price__amount",
        ]:
            el = card.query_selector(sel)
            if el:
                price = self._parse_price(el.inner_text())
                if price:
                    break

        # Price per unit
        price_per_unit = None
        for sel in [
            "[data-testid='product-card-unit-price']",
            ".product-card__unit-price",
            ".ds-product-card__unit-price",
            ".product-price__unit",
        ]:
            el = card.query_selector(sel)
            if el:
                price_per_unit = el.inner_text().strip()
                if price_per_unit:
                    break

        # Image
        image_url = None
        img = card.query_selector("img")
        if img:
            image_url = img.get_attribute("src") or img.get_attribute("data-src")

        # Product URL
        product_url = ""
        link = card.query_selector("a[href]")
        if link:
            href = link.get_attribute("href")
            if href:
                product_url = (
                    href if href.startswith("http")
                    else f"https://www.carrefour.fr{href}"
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
        text = text.replace("\xa0", " ").strip()
        match = re.search(r"(\d+)[.,](\d{1,2})", text)
        if match:
            return float(f"{match.group(1)}.{match.group(2)}")
        match = re.search(r"(\d+)", text)
        if match:
            return float(match.group(1))
        return None

    async def setup_location(self, postal_code: str) -> bool:
        """Carrefour works without location but may show local prices with one."""
        return True
