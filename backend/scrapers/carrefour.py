"""Carrefour: the search page answers in JSON to the XHR request of the site itself.

Each product is ``data[].attributes`` (``title``, ``brand``, ``ean``, ``slug``,
``images``, ``offers[ean][offerId].attributes.price``); page 2 is read when page
1 is full (``has_next_page``) and the search is still in its first half.
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
    extract_cards,
    extract_json_ld,
    first_url,
    json_of,
    merge_pages,
    pause_between_pages,
    products_from_json,
)
from backend.scrapers.parsing import PIECE, clean_text, parse_price, valid_ean

logger = logging.getLogger(__name__)

BASE_URL = "https://www.carrefour.fr"

# The search page answers in JSON to the same XHR request as the site itself
JSON_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "x-requested-with": "XMLHttpRequest",
}

SEARCH_URL = BASE_URL + "/s?q={query}&page={page}"

_UNITS = {"KG": "kg", "L": "L", "LITRE": "L", "U": PIECE, "UNITE": PIECE, "PIECE": PIECE}

# Without a total in the answer, a page of at least this many products may have a next one
FULL_PAGE = 24
# Images of the site: /media/540x540/Photosite/... ; the results show 56 px thumbnails
THUMBNAIL_SIZE = "280x280"
_MEDIA_SIZE = re.compile(r"/media/(\d{2,4})x(\d{2,4})/")


def thumbnail(url: str | None) -> str | None:
    """The 280x280 version of a Carrefour image (« /media/540x540/ » -> « /media/280x280/ »)."""
    if not url:
        return url
    m = _MEDIA_SIZE.search(url)
    if m and int(m.group(1)) > 280:
        return url[: m.start()] + f"/media/{THUMBNAIL_SIZE}/" + url[m.end() :]
    return url


def _number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _first_number(source: dict, keys: tuple[str, ...]) -> int | None:
    return next((n for n in (_number(source.get(k)) for k in keys) if n is not None), None)


def has_next_page(data: object, read: int, page: int = 1) -> bool:
    """The answer for ``page`` says there are more than the ``read`` products: a next link,
    a total or a number of pages; without them, a full page (``FULL_PAGE``)."""
    if not isinstance(data, dict) or read <= 0:
        return False
    links = data.get("links") if isinstance(data.get("links"), dict) else {}
    if links.get("next"):
        return True
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    pagination = meta.get("pagination") if isinstance(meta.get("pagination"), dict) else {}
    for source in (meta, pagination):
        pages = _first_number(source, ("totalPages", "pageCount", "lastPage"))
        if pages is not None:
            return pages > page
        total = _first_number(source, ("total", "totalCount", "totalItems", "count"))
        if total is not None:
            return total > read
    return read >= FULL_PAGE


def _offer_attributes(offers: object) -> dict | None:
    """offers = {ean: {offerServiceId: {"attributes": {"price": {...}, ...}}}}"""
    stack = [offers]
    while stack:
        node = stack.pop(0)
        if isinstance(node, dict):
            attributes = node.get("attributes")
            if isinstance(attributes, dict) and isinstance(attributes.get("price"), dict):
                return attributes
            if isinstance(node.get("price"), dict):
                return node
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None


def parse_search_json(data: object) -> list[Product]:
    items = data.get("data") if isinstance(data, dict) else None
    if isinstance(items, dict):
        items = items.get("data") or items.get("products")
    if not isinstance(items, list):
        return []

    products = []
    for item in items:
        if not isinstance(item, dict):
            continue
        attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else item
        name = clean_text(attrs.get("title") or attrs.get("name"))
        if not name:
            continue
        ean = clean_text(str(attrs.get("ean") or item.get("id") or ""))

        offer = _offer_attributes(attrs.get("offers")) or {}
        price_info = offer.get("price") or {}
        price = parse_price(price_info.get("price"))
        unit_price = parse_price(price_info.get("perUnit"))
        unit = _UNITS.get(str(price_info.get("unitOfMeasure") or "").upper())

        promotion = offer.get("promotion") or attrs.get("promotion")
        promo = clean_text(promotion.get("label")) if isinstance(promotion, dict) else None
        availability = offer.get("availability")
        available = not (isinstance(availability, dict) and availability.get("purchasable") is False)

        links = item.get("links") if isinstance(item.get("links"), dict) else {}
        slug = attrs.get("slug")
        path = links.get("self") or (f"/p/{slug}-{ean}" if slug and ean else "")
        image = thumbnail(first_url(attrs.get("images")))

        products.append(
            Product(
                store="carrefour",
                name=name,
                brand=clean_text(attrs.get("brand")) or None,
                price=price,
                unit_price=unit_price if unit else None,
                unit=unit if unit_price else None,
                unit_price_label=clean_text(price_info.get("perUnitLabel")) or None,
                quantity_label=clean_text(attrs.get("format") or attrs.get("packaging")) or None,
                image_url=urljoin(BASE_URL, image) if image else None,
                product_url=urljoin(BASE_URL, path) if path else BASE_URL,
                promo=promo or None,
                available=available,
                ean=valid_ean(ean),
                sku=ean or None,
            )
        )
    return products


class CarrefourScraper(BaseScraper):
    key = "carrefour"
    label = "Carrefour"
    home_url = BASE_URL + "/"
    store_hint = (
        "Prix en ligne par défaut. Pour les prix de votre magasin, choisissez-le "
        "sur carrefour.fr avec « Ouvrir le site »."
    )

    async def search(self, page, query: str, store: StoreSelection | None) -> list[Product]:
        self.last_source = None
        budget = PageBudget(self.key)
        await ensure_origin(page, self.home_url, self.label)

        result = await page_fetch(page, SEARCH_URL.format(query=quote(query), page=1), headers=JSON_HEADERS)
        data = json_of(result)
        if data is not None:
            products = self.found(parse_search_json(data), "api")
            if products:
                return self.found(await self._next_page(page, query, data, products, budget), "api")
            if data.get("data"):
                products = self.found(products_from_json(data, self.key, BASE_URL), "generic")
            if products or data.get("data") == []:
                return products
        logger.info("Carrefour: JSON search unavailable (HTTP %s), reading the page", result.status)

        # Fallback: the regular search page
        await page.goto(f"{BASE_URL}/s?q={quote(query)}&noRedirect=1", wait_until="domcontentloaded", timeout=30000)
        await wait_for_clearance(page, self.label)
        await accept_cookies(page)
        try:
            await page.wait_for_selector("a[href*='/p/']", timeout=10000)
        except Exception as e:  # noqa: BLE001 (timeout: the page is read anyway)
            logger.debug("Carrefour: no product link yet: %s", e)
        cards = await extract_cards(page, self.key, BASE_URL, cardSelector="article", linkPattern="/p/")
        products = self.found(cards, "html")
        if not products:
            products = self.found(await extract_cards(page, self.key, BASE_URL, linkPattern="/p/"), "generic")
        if not products:
            products = self.found(await extract_json_ld(page, self.key, BASE_URL), "json-ld")
        if not products:
            await save_debug_snapshot(page, self.key)
        return products

    async def _next_page(self, page, query: str, data: dict, products: list[Product], budget: PageBudget):
        """Page 2 of the JSON search when page 1 is full and the search is in its first half."""
        if not has_next_page(data, len(products)) or not budget.allows_more():
            return products
        await pause_between_pages(page)
        second = json_of(await page_fetch(page, SEARCH_URL.format(query=quote(query), page=2), headers=JSON_HEADERS))
        if second is None:
            logger.info("Carrefour: page 2 unavailable")
            return products
        return merge_pages(products, parse_search_json(second))
