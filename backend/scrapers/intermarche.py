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

SEARCH_URL = "https://www.intermarche.com/courses-en-ligne/recherche?q={query}"
HOME_URL = "https://www.intermarche.com"


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


class IntermarcheScraper(BaseScraper):
    store_name = "Intermarché"

    def __init__(self):
        self._store_configured = False
        self._store_id: str | None = None
        self._store_name_label: str | None = None

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

            # Intercept API responses
            def handle_response(response):
                try:
                    resp_url = response.url
                    if ("search" in resp_url or "product" in resp_url or "article" in resp_url) and response.status == 200:
                        content_type = response.headers.get("content-type", "")
                        if "json" in content_type:
                            data = response.json()
                            if isinstance(data, (dict, list)):
                                api_data.append(data if isinstance(data, dict) else {"items": data})
                except Exception:
                    pass

            page.on("response", handle_response)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)

                # Accept cookies if banner appears
                try:
                    for sel in [
                        "#onetrust-accept-btn-handler",
                        "[data-testid='accept-cookies']",
                        "button[class*='cookie']",
                        ".cookie-consent button",
                        "#footer_tc_privacy_button_2",
                        "#didomi-notice-agree-button",
                    ]:
                        btn = page.locator(sel).first
                        if btn.is_visible(timeout=2000):
                            btn.click(timeout=3000)
                            time.sleep(0.5)
                            break
                except Exception:
                    pass

                # Wait for products
                try:
                    page.wait_for_selector(
                        ".product-card, .product-item, .product-tile, [data-testid='product-card'], .search-product-list .product",
                        timeout=15000,
                    )
                except Exception:
                    logger.warning("Intermarché: no product cards for '%s'", query)

                time.sleep(1.5)

                # Try API data first
                if api_data:
                    products = self._parse_api_data(api_data)

                # Fallback to HTML parsing
                if not products:
                    products = self._parse_html(page)

            except Exception as e:
                logger.error("Intermarché scraper error: %s", e)
            finally:
                browser.close()

        return products

    def _parse_api_data(self, api_responses: list[dict]) -> list[ScrapedProduct]:
        products: list[ScrapedProduct] = []
        for data in api_responses:
            items = (
                data.get("products", [])
                or data.get("items", [])
                or data.get("hits", [])
                or data.get("data", {}).get("products", [])
                or data.get("articles", [])
            )
            for item in items:
                try:
                    name = (
                        item.get("title")
                        or item.get("name")
                        or item.get("label")
                        or item.get("designation", "")
                    )
                    if not name:
                        continue

                    price = None
                    for key in ["price", "currentPrice", "unitPrice", "sellingPrice"]:
                        val = item.get(key)
                        if isinstance(val, (int, float)):
                            price = float(val)
                            break
                        if isinstance(val, dict):
                            price = val.get("value") or val.get("price") or val.get("amount")
                            if price is not None:
                                price = float(price)
                                break

                    price_per_unit = None
                    for key in ["pricePerUnit", "unitPrice", "pricePerKg"]:
                        ppu = item.get(key)
                        if isinstance(ppu, str):
                            price_per_unit = ppu
                            break
                        if isinstance(ppu, dict):
                            price_per_unit = ppu.get("label") or ppu.get("formatted")
                            if price_per_unit:
                                break

                    image_url = item.get("image") or item.get("imageUrl") or item.get("img")
                    if isinstance(image_url, dict):
                        image_url = image_url.get("url") or image_url.get("src")
                    if isinstance(image_url, list) and image_url:
                        image_url = image_url[0] if isinstance(image_url[0], str) else image_url[0].get("url")

                    slug = item.get("url") or item.get("slug") or item.get("href", "")
                    product_url = (
                        slug if slug.startswith("http")
                        else f"https://www.intermarche.com{slug}" if slug else ""
                    )

                    products.append(ScrapedProduct(
                        name=name,
                        price=price,
                        price_per_unit=price_per_unit,
                        image_url=image_url,
                        product_url=product_url,
                        store_name=self.store_name,
                    ))
                except Exception as e:
                    logger.debug("Intermarché API parse error: %s", e)

        return products

    def _parse_html(self, page) -> list[ScrapedProduct]:
        products: list[ScrapedProduct] = []

        selectors = [
            ".product-card",
            ".product-item",
            ".product-tile",
            "[data-testid='product-card']",
            ".search-product-list .product",
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
                logger.debug("Intermarché card parse error: %s", e)

        return products

    def _parse_card(self, card) -> ScrapedProduct | None:
        name = None
        for sel in [
            ".product-card__title",
            ".product-item__name",
            ".product-name",
            "h2",
            "h3",
            "a[title]",
        ]:
            el = card.query_selector(sel)
            if el:
                name = el.get_attribute("title") or el.inner_text()
                name = name.strip()
                if name:
                    break

        if not name:
            return None

        price = None
        for sel in [
            ".product-card__price",
            ".product-price",
            ".price",
            ".product-item__price",
            "[data-testid='product-price']",
        ]:
            el = card.query_selector(sel)
            if el:
                price = self._parse_price(el.inner_text())
                if price:
                    break

        price_per_unit = None
        for sel in [
            ".product-card__unit-price",
            ".unit-price",
            ".price-per-unit",
            ".product-price__unit",
        ]:
            el = card.query_selector(sel)
            if el:
                price_per_unit = el.inner_text().strip()
                if price_per_unit:
                    break

        image_url = None
        img = card.query_selector("img")
        if img:
            image_url = img.get_attribute("src") or img.get_attribute("data-src")

        product_url = ""
        link = card.query_selector("a[href]")
        if link:
            href = link.get_attribute("href")
            if href:
                product_url = (
                    href if href.startswith("http")
                    else f"https://www.intermarche.com{href}"
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
        """Configure the nearest Intermarché store for the given postal code."""
        try:
            result = await asyncio.to_thread(self._setup_location_sync, postal_code)
            return result
        except Exception as e:
            logger.error("Intermarché location setup error: %s", e)
            return False

    def _setup_location_sync(self, postal_code: str) -> bool:
        proxy = _get_proxy_config()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
                proxy=proxy,
            )
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="fr-FR",
                ignore_https_errors=True,
            )
            try:
                page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)

                # Accept cookies
                try:
                    for sel in [
                        "#onetrust-accept-btn-handler",
                        "#didomi-notice-agree-button",
                    ]:
                        btn = page.query_selector(sel)
                        if btn:
                            btn.click()
                            time.sleep(0.5)
                            break
                except Exception:
                    pass

                # Try to find and click the store selector
                for sel in [
                    ".store-selector",
                    "[data-testid='store-selector']",
                    ".header-pdv",
                    ".choose-store",
                    ".pdv-selector",
                ]:
                    btn = page.query_selector(sel)
                    if btn:
                        btn.click()
                        time.sleep(1)
                        break

                # Enter postal code
                for sel in [
                    "input[placeholder*='postal']",
                    "input[placeholder*='ville']",
                    "input[name*='postal']",
                    "input[name*='location']",
                    "input[name*='search']",
                    ".store-search input",
                ]:
                    inp = page.query_selector(sel)
                    if inp:
                        inp.fill(postal_code)
                        time.sleep(1)
                        inp.press("Enter")
                        time.sleep(2)

                        # Click first store result
                        for result_sel in [
                            ".store-list .store-item:first-child",
                            ".store-results button:first-child",
                            ".pdv-item:first-child button",
                            ".store-result:first-child",
                        ]:
                            result = page.query_selector(result_sel)
                            if result:
                                result.click()
                                self._store_configured = True
                                return True
                        break

            except Exception as e:
                logger.error("Intermarché store setup error: %s", e)
            finally:
                browser.close()

        return False
