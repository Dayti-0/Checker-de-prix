import logging
import re
from urllib.parse import quote

from backend.models import Product, StoreSelection
from backend.scrapers.base import BaseScraper
from backend.scrapers.common import accept_cookies, save_debug_snapshot, wait_for_clearance
from backend.scrapers.extract import extract_cards, extract_json_ld

logger = logging.getLogger(__name__)

BASE_URL = "https://www.coursesu.com"
SEARCH_URL = BASE_URL + "/recherche?q={query}"

TILE_OPTIONS = {
    "cardSelector": "[data-pid], .product-tile, .product-item",
    "nameSelector": ".product-tile__name, .product-name, .pdp-link a, .tile-body a, [itemprop='name']",
    "priceSelector": ".sales .value, [itemprop='price'], .product-price, .price-sales, [class*='price__value' i]",
    "unitSelector": "[class*='unit-price' i], [class*='price-per' i], [class*='unitPrice' i], [class*='pricePerUnit' i]",
    "brandSelector": ".product-brand, [class*='brand' i]",
}

_STORE_URL = re.compile(r"^https://www\.coursesu\.com/[\w-]+/?$")


def store_name_from_url(url: str) -> str:
    """'https://www.coursesu.com/drive-superu-roujan' -> 'Super U Roujan'."""
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"^(drive|magasin|livraison)-", "", slug)
    banners = {"superu": "Super U", "hyperu": "Hyper U", "uexpress": "U Express", "marcheu": "Marché U", "utile": "Utile"}
    words = slug.split("-")
    first = banners.get(words[0], words[0].capitalize()) if words else ""
    return " ".join([first] + [w.capitalize() for w in words[1:]]).strip()


def is_store_url(url: str) -> bool:
    return bool(_STORE_URL.match(url.strip()))


class CoursesUScraper(BaseScraper):
    key = "coursesu"
    label = "Courses U"
    home_url = BASE_URL + "/"
    needs_store = True
    store_hint = (
        "Les prix ne s'affichent qu'une fois un magasin choisi. Collez l'adresse de la page "
        "de votre magasin (ex : https://www.coursesu.com/drive-superu-roujan) ou choisissez-le "
        "sur le site avec « Ouvrir le site »."
    )

    def __init__(self) -> None:
        # Store page already visited in this session (it sets the store cookies)
        self._visited_store_url: str | None = None

    async def search(self, page, query: str, store: StoreSelection | None) -> list[Product]:
        if store and store.url and self._visited_store_url != store.url:
            await page.goto(store.url, wait_until="domcontentloaded", timeout=30000)
            await wait_for_clearance(page, self.label)
            await accept_cookies(page)
            self._visited_store_url = store.url

        await page.goto(SEARCH_URL.format(query=quote(query)), wait_until="domcontentloaded", timeout=30000)
        await wait_for_clearance(page, self.label)
        await accept_cookies(page)
        try:
            await page.wait_for_selector(
                "[data-pid], .product-tile, .product-item, [class*='no-result' i], [class*='noresult' i]",
                timeout=12000,
            )
        except Exception:
            logger.info("Courses U: no product tile for '%s'", query)
        await page.wait_for_timeout(500)

        products = await extract_cards(page, self.key, BASE_URL, **TILE_OPTIONS)
        if not products:
            products = await extract_cards(page, self.key, BASE_URL, linkPattern=r"/p/|\.html")
        if not products:
            products = await extract_json_ld(page, self.key, BASE_URL)
        if not products:
            await save_debug_snapshot(page, self.key)
        return products
