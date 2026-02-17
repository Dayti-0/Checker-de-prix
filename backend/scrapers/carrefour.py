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
                    resp_url = response.url
                    if response.status == 200:
                        content_type = response.headers.get("content-type", "")
                        if "json" in content_type:
                            if any(
                                k in resp_url
                                for k in [
                                    "search",
                                    "product",
                                    "catalog",
                                    "algolia",
                                    "api",
                                ]
                            ):
                                data = response.json()
                                if isinstance(data, dict):
                                    api_data.append(data)
                except Exception:
                    pass

            page.on("response", handle_response)

            try:
                page.goto(url, wait_until="commit", timeout=30000)

                # Accept cookies if banner appears
                try:
                    btn = page.locator("#onetrust-accept-btn-handler")
                    btn.click(timeout=4000)
                    time.sleep(0.5)
                except Exception:
                    pass

                # Wait for products to appear with broader selectors
                try:
                    page.wait_for_selector(
                        ", ".join(
                            [
                                "[data-testid='product-card-container']",
                                ".product-card-list__item",
                                ".ds-product-card",
                                "[class*='product']",
                                "[class*='Product']",
                                "[data-testid*='product']",
                                "article",
                                "li[data-testid]",
                            ]
                        ),
                        timeout=15000,
                    )
                except Exception:
                    logger.warning("Carrefour: no product cards for '%s'", query)

                time.sleep(2)

                # Strategy 1: Try __NEXT_DATA__ (SSR-rendered data)
                products = self._parse_next_data(page)

                # Strategy 2: Try API data (more reliable)
                if not products and api_data:
                    products = self._parse_api_data(api_data)

                # Strategy 3: Fallback to HTML parsing
                if not products:
                    products = self._parse_html(page)

            except Exception as e:
                logger.error("Carrefour scraper error: %s", e)
            finally:
                browser.close()

        return products

    def _parse_next_data(self, page) -> list[ScrapedProduct]:
        """Try to extract product data from __NEXT_DATA__ script tag."""
        products: list[ScrapedProduct] = []
        try:
            script = page.query_selector("script#__NEXT_DATA__")
            if not script:
                return products
            raw = script.inner_text()
            data = json.loads(raw)
            props = data.get("props", {}).get("pageProps", {})
            # Try various common structures
            items = (
                props.get("products", [])
                or props.get("searchResults", {}).get("products", [])
                or props.get("initialData", {}).get("products", [])
                or props.get("data", {}).get("products", [])
                or props.get("results", [])
            )
            if not items and "dehydratedState" in props:
                queries = props["dehydratedState"].get("queries", [])
                for q in queries:
                    state_data = q.get("state", {}).get("data", {})
                    if isinstance(state_data, dict):
                        items = (
                            state_data.get("products", [])
                            or state_data.get("items", [])
                            or state_data.get("hits", [])
                        )
                        if items:
                            break

            for item in items:
                try:
                    product = self._item_to_product(item)
                    if product:
                        products.append(product)
                except Exception as e:
                    logger.debug("Carrefour __NEXT_DATA__ item parse error: %s", e)

        except Exception as e:
            logger.debug("Carrefour __NEXT_DATA__ parse error: %s", e)
        return products

    def _item_to_product(self, item: dict) -> ScrapedProduct | None:
        """Convert a product dict (from API or __NEXT_DATA__) to ScrapedProduct."""
        name = item.get("title") or item.get("name", "")
        if not name:
            return None

        price = None
        price_data = item.get("price", {})
        if isinstance(price_data, dict):
            price = price_data.get("price") or price_data.get("value")
        elif isinstance(price_data, (int, float)):
            price = float(price_data)
        # Try alternative keys
        if price is None:
            for key in ["currentPrice", "sellingPrice"]:
                val = item.get(key)
                if isinstance(val, (int, float)):
                    price = float(val)
                    break
                if isinstance(val, dict):
                    price = val.get("value") or val.get("price")
                    if price is not None:
                        price = float(price)
                        break

        price_per_unit = None
        if isinstance(price_data, dict):
            unit_price = price_data.get("pricePerUnit") or price_data.get("unitPrice")
            unit = price_data.get("unit", "")
            if unit_price:
                price_per_unit = f"{unit_price} €/{unit}" if unit else f"{unit_price} €"
        if not price_per_unit:
            ppu = item.get("pricePerUnit") or item.get("unitPrice")
            if isinstance(ppu, str):
                price_per_unit = ppu
            elif isinstance(ppu, dict):
                price_per_unit = ppu.get("label") or ppu.get("formatted")

        image_url = item.get("image") or item.get("imageUrl")
        if isinstance(image_url, dict):
            image_url = image_url.get("url") or image_url.get("src")
        if isinstance(image_url, list) and image_url:
            image_url = (
                image_url[0]
                if isinstance(image_url[0], str)
                else image_url[0].get("url")
            )
        # Handle nested media
        if not image_url:
            media = item.get("media", {})
            if isinstance(media, dict):
                image_url = media.get("url") or media.get("src")
            elif isinstance(media, list) and media:
                image_url = (
                    media[0] if isinstance(media[0], str) else media[0].get("url")
                )

        product_url = item.get("url") or item.get("href", "")
        if product_url and not product_url.startswith("http"):
            product_url = f"https://www.carrefour.fr{product_url}"

        return ScrapedProduct(
            name=name,
            price=float(price) if price else None,
            price_per_unit=price_per_unit,
            image_url=image_url,
            product_url=product_url,
            store_name=self.store_name,
        )

    def _parse_api_data(self, api_responses: list[dict]) -> list[ScrapedProduct]:
        """Parse products from intercepted API JSON responses."""
        products: list[ScrapedProduct] = []
        for data in api_responses:
            # Try multiple data structure patterns
            items = (
                data.get("data", {}).get("products", [])
                or data.get("data", {}).get("data", {}).get("products", [])
                or data.get("products", [])
                or data.get("hits", [])
                or data.get("items", [])
                or data.get("results", [])
            )

            for item in items:
                try:
                    product = self._item_to_product(item)
                    if product:
                        products.append(product)
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
            "[class*='productCard']",
            "[class*='ProductCard']",
            "[class*='product-card']",
            "[data-testid*='product']",
            "li[data-testid]",
            "article",
        ]

        cards = []
        for sel in selectors:
            cards = page.query_selector_all(sel)
            if cards:
                logger.debug(
                    "Carrefour: found %d cards with selector '%s'",
                    len(cards),
                    sel,
                )
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
            "[class*='title']",
            "[class*='Title']",
            "[class*='name']",
            "[class*='Name']",
            "a[title]",
            "h2",
            "h3",
        ]:
            el = card.query_selector(sel)
            if el:
                name = el.get_attribute("title") or el.inner_text()
                name = name.strip()
                if name and len(name) > 2:
                    break
                name = None

        if not name:
            return None

        # Price
        price = None
        for sel in [
            "[data-testid='product-card-price']",
            "[class*='price']",
            "[class*='Price']",
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
            "[class*='unit-price']",
            "[class*='unitPrice']",
            "[class*='UnitPrice']",
            "[class*='price-per']",
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
            image_url = (
                img.get_attribute("src")
                or img.get_attribute("data-src")
                or img.get_attribute("srcset", "").split(",")[0].split(" ")[0]
            )

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
