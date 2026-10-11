"""Lidl: the search API used by lidl.fr, called from inside a lidl.fr tab.

Each result is a "gridbox" (fullTitle, price.price, price.basePrice.text...),
the same structure on every Lidl country site. ``numFound`` above the products
read: the next ones (``offset``) are asked once, in the first half of the search.
"""

import logging
import re
from urllib.parse import quote, urljoin

from backend.models import Product, StoreSelection
from backend.scrapers.base import BaseScraper
from backend.scrapers.common import (
    accept_cookies,
    ensure_origin,
    page_fetch,
    save_debug_snapshot,
    wait_for_clearance,
)
from backend.scrapers.extract import (
    PageBudget,
    barcode_of,
    extract_cards,
    extract_json_ld,
    first_url,
    identifier_of,
    json_of,
    merge_pages,
    pause_between_pages,
    products_from_json,
)
from backend.scrapers.parsing import clean_text, parse_price

logger = logging.getLogger(__name__)

BASE_URL = "https://www.lidl.fr"
# Products asked at once
FETCH_SIZE = 48
SEARCH_API = BASE_URL + "/q/api/search?q={query}&assortment=FR&locale=fr_FR&version=v2.0.0&fetchsize=" + str(FETCH_SIZE)
SEARCH_URL = BASE_URL + "/q/search?q={query}"


def _text(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("text")
    return clean_text(value) if isinstance(value, str) else ""


def parse_search_json(data: object) -> list[Product]:
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    products = []
    for item in items:
        if not isinstance(item, dict):
            continue
        grid = item.get("gridbox", {}).get("data") if isinstance(item.get("gridbox"), dict) else item
        if not isinstance(grid, dict):
            continue
        name = clean_text(grid.get("fullTitle") or grid.get("title"))
        if not name:
            continue
        price_info = grid.get("price") if isinstance(grid.get("price"), dict) else {}
        price = parse_price(price_info.get("price"))
        old_price = parse_price(price_info.get("oldPrice"))

        # basePrice.text looks like "500 g (1 kg = 3,98 €)"
        base_text = _text(price_info.get("basePrice"))
        inside = re.search(r"\(([^)]*)\)", base_text)
        unit_label = inside.group(1) if inside else (base_text if "=" in base_text else None)
        keyfacts = grid.get("keyfacts") if isinstance(grid.get("keyfacts"), dict) else {}
        quantity = (
            clean_text(keyfacts.get("supplementalDescription"))
            or _text(price_info.get("packaging"))
            or base_text.split("(")[0].strip()
        )

        brand = grid.get("brand")
        brand = brand.get("name") if isinstance(brand, dict) else brand
        image = grid.get("image") or first_url(grid.get("imageList"))
        url = grid.get("canonicalUrl") or grid.get("canonicalPath") or ""
        discount = price_info.get("discount") if isinstance(price_info.get("discount"), dict) else {}
        promo = clean_text(discount.get("discountText")) or None
        if promo is None and old_price and price and old_price > price:
            promo = f"Au lieu de {old_price:.2f} €".replace(".", ",")

        products.append(
            Product(
                store="lidl",
                name=name,
                brand=clean_text(brand) if isinstance(brand, str) else None,
                price=price,
                unit_price_label=unit_label,
                quantity_label=quantity or None,
                image_url=urljoin(BASE_URL, image) if isinstance(image, str) and image else None,
                product_url=urljoin(BASE_URL, url) if url else BASE_URL,
                promo=promo,
                old_price=old_price if old_price and price and old_price > price else None,
                ean=barcode_of(grid),
                sku=identifier_of(grid),
            )
        )
    return products


def next_offset(data: object) -> int | None:
    """Where the next products start when the answer holds fewer than ``numFound``, else None."""
    if not isinstance(data, dict) or not isinstance(data.get("items"), list) or not data["items"]:
        return None
    found = data.get("numFound")
    if isinstance(found, bool) or not isinstance(found, int):
        return None
    offset = data.get("offset") if isinstance(data.get("offset"), int) else 0
    read = offset + len(data["items"])
    return read if found > read else None


class LidlScraper(BaseScraper):
    key = "lidl"
    label = "Lidl"
    home_url = BASE_URL + "/"
    store_hint = (
        "Prix nationaux : rien à configurer. Lidl ne publie en ligne qu'une partie "
        "de son rayon alimentaire (souvent les offres de la semaine)."
    )

    async def search(self, page, query: str, store: StoreSelection | None) -> list[Product]:
        self.last_source = None
        budget = PageBudget(self.key)
        await ensure_origin(page, self.home_url, self.label)
        result = await page_fetch(page, SEARCH_API.format(query=quote(query)), headers={"accept": "application/json"})
        data = json_of(result)
        if data is not None:
            products = self.found(parse_search_json(data), "api")
            if products:
                return self.found(await self._next_products(page, query, data, products, budget), "api")
            products = self.found(products_from_json(data, self.key, BASE_URL), "generic")
            if products or data.get("items") == []:
                return products
        logger.info("Lidl: JSON search unavailable (HTTP %s), reading the page", result.status)

        await page.goto(SEARCH_URL.format(query=quote(query)), wait_until="domcontentloaded", timeout=30000)
        await wait_for_clearance(page, self.label)
        await accept_cookies(page)
        try:
            await page.wait_for_selector("a[href*='/p/']", timeout=12000)
        except Exception as e:  # noqa: BLE001 (timeout: the page is read anyway)
            logger.debug("Lidl: no product link yet: %s", e)
        products = self.found(await extract_cards(page, self.key, BASE_URL, linkPattern="/p/"), "generic")
        if not products:
            products = self.found(await extract_json_ld(page, self.key, BASE_URL), "json-ld")
        if not products:
            await save_debug_snapshot(page, self.key)
        return products

    async def _next_products(self, page, query: str, data: dict, products: list[Product], budget: PageBudget):
        """The next products of the API (``offset``) when ``numFound`` says there are more."""
        offset = next_offset(data)
        if offset is None or not budget.allows_more():
            return products
        await pause_between_pages(page)
        url = SEARCH_API.format(query=quote(query)) + f"&offset={offset}"
        more = json_of(await page_fetch(page, url, headers={"accept": "application/json"}))
        if more is None:
            logger.info("Lidl: next products unavailable")
            return products
        return merge_pages(products, parse_search_json(more))
