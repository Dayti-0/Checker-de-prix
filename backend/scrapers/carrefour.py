import logging
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
from backend.scrapers.extract import extract_cards, extract_json_ld, first_url, products_from_json
from backend.scrapers.parsing import clean_text, parse_price

logger = logging.getLogger(__name__)

BASE_URL = "https://www.carrefour.fr"

# The search page answers in JSON to the same XHR request as the site itself
JSON_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "x-requested-with": "XMLHttpRequest",
}

_UNITS = {"KG": "kg", "L": "L", "LITRE": "L", "U": "unité", "UNITE": "unité", "PIECE": "unité"}


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
        ean = str(attrs.get("ean") or item.get("id") or "")

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
        image = first_url(attrs.get("images"))

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
        await ensure_origin(page, self.home_url, self.label)

        result = await page_fetch(page, f"{BASE_URL}/s?q={quote(query)}&page=1", headers=JSON_HEADERS)
        if result.ok and result.is_json:
            try:
                data = result.json()
            except ValueError:
                data = None
            if isinstance(data, dict):
                products = parse_search_json(data)
                if not products and data.get("data"):
                    products = products_from_json(data, self.key, BASE_URL)
                if products or data.get("data") == []:
                    return products
        logger.info("Carrefour: JSON search unavailable (HTTP %s), reading the page", result.status)

        # Fallback: the regular search page
        await page.goto(f"{BASE_URL}/s?q={quote(query)}&noRedirect=1", wait_until="domcontentloaded", timeout=30000)
        await wait_for_clearance(page, self.label)
        await accept_cookies(page)
        try:
            await page.wait_for_selector("a[href*='/p/']", timeout=10000)
        except Exception:
            pass
        products = await extract_cards(page, self.key, BASE_URL, cardSelector="article", linkPattern="/p/")
        if not products:
            products = await extract_cards(page, self.key, BASE_URL, linkPattern="/p/")
        if not products:
            products = await extract_json_ld(page, self.key, BASE_URL)
        if not products:
            await save_debug_snapshot(page, self.key)
        return products
