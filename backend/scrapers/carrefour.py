import asyncio
import json
import logging
import re

from backend.models import ScrapedProduct
from backend.scrapers.base import BaseScraper
from backend.scrapers.browser import create_stealth_browser, accept_cookies

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.carrefour.fr/s?q={query}"


class CarrefourScraper(BaseScraper):
    store_name = "Carrefour"

    async def search(self, query: str) -> list[ScrapedProduct]:
        return await asyncio.to_thread(self._search_sync, query)

    def _search_sync(self, query: str) -> list[ScrapedProduct]:
        url = SEARCH_URL.format(query=query)
        products: list[ScrapedProduct] = []
        api_data: list[dict] = []

        with create_stealth_browser() as (browser, context, page):
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
                # Use networkidle to let Cloudflare challenge complete
                page.goto(url, wait_until="networkidle", timeout=30000)
                accept_cookies(page)

                # Extra wait for Cloudflare challenge resolution
                page.wait_for_timeout(2000)

                # Check if we got a Cloudflare challenge page
                title = page.title()
                if "just a moment" in title.lower() or "cloudflare" in title.lower():
                    logger.warning(
                        "Carrefour: Cloudflare challenge detected, waiting..."
                    )
                    # Wait longer for challenge to resolve
                    page.wait_for_timeout(5000)

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

                page.wait_for_timeout(1000)

                # Strategy 1: Try __NEXT_DATA__ (SSR-rendered data)
                products = self._parse_next_data(page)

                # Strategy 2: Try API data (more reliable)
                if not products and api_data:
                    products = self._parse_api_data(api_data)

                # Strategy 3: Fallback to HTML parsing
                if not products:
                    products = self._parse_html(page)

                if products:
                    priced = sum(1 for p in products if p.price is not None)
                    if priced == 0:
                        logger.warning(
                            "Carrefour: found %d products but none have prices",
                            len(products),
                        )
                else:
                    logger.debug(
                        "Carrefour: page title='%s', url='%s'",
                        page.title(),
                        page.url,
                    )

            except Exception as e:
                logger.error("Carrefour scraper error: %s", e)

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
            search_results = props.get("searchResults")
            initial_data = props.get("initialData")
            prop_data = props.get("data")
            items = (
                props.get("products", [])
                or (search_results.get("products", []) if isinstance(search_results, dict) else [])
                or (initial_data.get("products", []) if isinstance(initial_data, dict) else [])
                or (prop_data.get("products", []) if isinstance(prop_data, dict) else [])
                or props.get("results", [])
            )
            # If any of these were lists, use them directly as items
            if not items:
                for candidate in [search_results, initial_data, prop_data]:
                    if isinstance(candidate, list) and candidate:
                        items = candidate
                        break
            if not items and "dehydratedState" in props:
                dehydrated = props["dehydratedState"]
                queries = dehydrated.get("queries", []) if isinstance(dehydrated, dict) else []
                for q in queries:
                    state = q.get("state", {}) if isinstance(q, dict) else {}
                    state_data = state.get("data", {}) if isinstance(state, dict) else {}
                    if isinstance(state_data, dict):
                        items = (
                            state_data.get("products", [])
                            or state_data.get("items", [])
                            or state_data.get("hits", [])
                        )
                        if items:
                            break
                    elif isinstance(state_data, list) and state_data:
                        items = state_data
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
        name = item.get("title") or item.get("name") or item.get("label", "")
        if not name:
            return None

        price = None
        price_data = item.get("price", {})
        if isinstance(price_data, dict):
            price = price_data.get("price") or price_data.get("value") or price_data.get("amount")
        elif isinstance(price_data, (int, float)):
            price = float(price_data)
        elif isinstance(price_data, str):
            price = self._parse_price(price_data)
        # Try alternative top-level keys
        if price is None:
            for key in ["currentPrice", "sellingPrice", "displayPrice", "formattedPrice"]:
                val = item.get(key)
                if isinstance(val, (int, float)):
                    price = float(val)
                    break
                if isinstance(val, str):
                    price = self._parse_price(val)
                    if price is not None:
                        break
                if isinstance(val, dict):
                    price = val.get("value") or val.get("price") or val.get("amount")
                    if price is not None:
                        price = float(price)
                        break
        # Try nested offer/pricing structures
        if price is None:
            for container_key in ["offer", "pricing", "prices"]:
                container = item.get(container_key)
                if isinstance(container, dict):
                    for pk in ["price", "currentPrice", "sellingPrice", "value", "amount"]:
                        val = container.get(pk)
                        if isinstance(val, (int, float)):
                            price = float(val)
                            break
                        if isinstance(val, str):
                            price = self._parse_price(val)
                            if price is not None:
                                break
                    if price is not None:
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

        image_url = item.get("image") or item.get("imageUrl") or item.get("thumbnailUrl")
        if isinstance(image_url, dict):
            image_url = image_url.get("url") or image_url.get("src")
        if isinstance(image_url, list) and image_url:
            first = image_url[0]
            image_url = first if isinstance(first, str) else first.get("url") if isinstance(first, dict) else None
        # Handle nested media/images
        if not image_url:
            for media_key in ["media", "medias", "images"]:
                media = item.get(media_key)
                if isinstance(media, dict):
                    image_url = media.get("url") or media.get("src") or media.get("href")
                    if image_url:
                        break
                elif isinstance(media, list) and media:
                    first = media[0]
                    image_url = first if isinstance(first, str) else (first.get("url") or first.get("src") if isinstance(first, dict) else None)
                    if image_url:
                        break

        product_url = item.get("url") or item.get("href") or item.get("slug", "")
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
            try:
                inner_data = data.get("data")
                inner_inner = inner_data.get("data") if isinstance(inner_data, dict) else None
                items = (
                    (inner_data.get("products", []) if isinstance(inner_data, dict) else [])
                    or (inner_inner.get("products", []) if isinstance(inner_inner, dict) else [])
                    or data.get("products", [])
                    or data.get("hits", [])
                    or data.get("items", [])
                    or data.get("results", [])
                )
                # If inner "data" was a list, use it directly
                if not items and isinstance(inner_data, list):
                    items = inner_data

                for item in items:
                    try:
                        if isinstance(item, dict):
                            product = self._item_to_product(item)
                            if product:
                                products.append(product)
                    except Exception as e:
                        logger.debug("Carrefour API item parse error: %s", e)
            except Exception as e:
                logger.debug("Carrefour API response parse error: %s", e)

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
            )
            if not image_url:
                srcset = img.get_attribute("srcset")
                if srcset:
                    image_url = srcset.split(",")[0].split(" ")[0]

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
