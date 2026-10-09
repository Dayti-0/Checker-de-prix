import logging
from urllib.parse import quote

from backend.models import Product, StoreSelection
from backend.scrapers.base import BaseScraper
from backend.scrapers.common import accept_cookies, save_debug_snapshot, wait_for_clearance
from backend.scrapers.extract import extract_cards, extract_json_ld, products_from_json

logger = logging.getLogger(__name__)

BASE_URL = "https://www.aldi.fr"
SEARCH_URL = BASE_URL + "/recherche.html?query={query}"

# Product tiles of aldi.fr (rendered client-side from Algolia)
TILE_OPTIONS = {
    "cardSelector": ".product-tile",
    "nameSelector": ".product-tile__content__upper__product-name",
    "brandSelector": ".product-tile__content__upper__brand-name",
    "priceSelector": "[data-testid$='tag-current-price-amount'], .tag__label--price",
    "unitSelector": ".tag__marker--base-price",
    "quantitySelector": ".tag__marker--salesunit",
}


class AldiScraper(BaseScraper):
    key = "aldi"
    label = "Aldi"
    home_url = BASE_URL + "/"
    store_hint = "Prix nationaux : rien à configurer."

    async def search(self, page, query: str, store: StoreSelection | None) -> list[Product]:
        algolia_responses = []

        def on_response(response) -> None:
            if "algolia" in response.url:
                algolia_responses.append(response)

        page.on("response", on_response)
        try:
            await page.goto(SEARCH_URL.format(query=quote(query)), wait_until="domcontentloaded", timeout=30000)
            await wait_for_clearance(page, self.label)
            await accept_cookies(page)
            try:
                await page.wait_for_selector(
                    ".product-tile, [class*='no-result' i], [class*='noresult' i], [class*='empty-result' i]",
                    timeout=12000,
                )
            except Exception:
                logger.info("Aldi: no product tile for '%s'", query)
            await page.wait_for_timeout(500)

            products = await extract_cards(page, self.key, BASE_URL, **TILE_OPTIONS)
            if not products:
                # Tiles changed: use the search API responses captured meanwhile
                for response in algolia_responses:
                    try:
                        products += products_from_json(await response.json(), self.key, BASE_URL)
                    except Exception:
                        continue
            if not products:
                products = await extract_cards(page, self.key, BASE_URL, linkPattern=r"/(fiches-produits|produits?)/")
            if not products:
                products = await extract_json_ld(page, self.key, BASE_URL)
            if not products:
                await save_debug_snapshot(page, self.key)
            return products
        finally:
            page.remove_listener("response", on_response)
