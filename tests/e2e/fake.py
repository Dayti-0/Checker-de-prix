"""Fake retailers for the E2E tests and the demo: nothing leaves the machine.

``install(mp)`` replaces what talks to the outside world:

- ``backend.services.search._scrape``: products of ``CATALOG`` whose name shares
  a word with the query. Aldi and Lidl answer; Carrefour has a promotion, an
  organic product, EANs and an unavailable product; Intermarché asks for a store
  (``store_required``) until one is chosen; Courses U shows an anti-robot check
  (``blocked``) until the user went through « Ouvrir le site » then « J'ai terminé ».
- ``backend.services.settings.geocode``: a few postal codes (see ``TOWNS``).
- the PrixMalin browser: the Intermarché store finder, « Ouvrir le site »,
  « J'ai terminé » and the visible window switch.

Each retailer answers after ``DELAYS[key]`` seconds (a number or a ``(min, max)``
range): 0 in the tests, a few hundred milliseconds in the demo.

More products: add a ``tests/e2e/catalog_<name>.py`` module defining
``PRODUCTS = {"aldi": [{"name": ..., "price": ...}], ...}``; it is loaded
automatically. It may also define ``install(fake, mp)`` for extra patches.
"""

import asyncio
import importlib
import pkgutil
import random
import re
import sys
from pathlib import Path

from backend.browser import browser
from backend.models import Location, Product, StoreOption
from backend.scrapers.base import BlockedError, StoreRequiredError
from backend.services import matching, search, settings

# Products of each retailer: Product fields (store and product_url are filled in)
BASE_CATALOG: dict[str, list[dict]] = {
    "aldi": [
        {"name": "Farine de blé T55", "brand": "BELBAKE", "price": 0.79, "unit_price_label": "1 kg = 0,79 €",
         "quantity_label": "1 kg"},
        {"name": "Farine de sarrasin", "brand": "BELBAKE", "price": 1.49, "quantity_label": "500 g"},
        {"name": "Huile de tournesol", "brand": "BELLASAN", "price": 1.89, "unit_price_label": "1 L = 1,89 €",
         "quantity_label": "1 L"},
        {"name": "Eau minérale naturelle 6x1,5L", "brand": "SAINT-ELOI", "price": 1.62},
        {"name": "Gâteau marbré", "price": 2.19, "quantity_label": "400 g"},
    ],
    "lidl": [
        {"name": "Farine de blé T45", "brand": "Belbake", "price": 0.75, "unit_price_label": "1 kg = 0,75 €",
         "quantity_label": "1 kg"},
        {"name": "Huile de tournesol", "brand": "Vita D'or", "price": 1.79, "unit_price_label": "1 L = 1,79 €",
         "quantity_label": "1 L"},
    ],
    "carrefour": [
        {"name": "Farine de blé T45", "brand": "CARREFOUR CLASSIC'", "price": 0.85, "unit_price_label": "0,85 € / KG",
         "quantity_label": "1kg", "ean": "3560070472888", "promo": "2ème à -50%"},
        {"name": "Farine de blé fluide T45", "brand": "FRANCINE", "price": 1.89, "unit_price_label": "1,89 € / KG",
         "quantity_label": "1kg", "ean": "3229820129488", "available": False},
        {"name": "Farine de blé T65 bio", "brand": "CARREFOUR BIO", "price": 1.45, "unit_price_label": "1,45 € / KG",
         "quantity_label": "1kg", "ean": "3560071234567", "promo": "Au lieu de 1,65 €"},
        {"name": "Huile de tournesol", "brand": "LESIEUR", "price": 2.65, "unit_price_label": "2,65 € / L",
         "quantity_label": "1L", "ean": "3265478901234"},
        {"name": "Huile de tournesol", "brand": "CARREFOUR CLASSIC'", "price": 1.95, "unit_price_label": "1,95 € / L",
         "quantity_label": "1L", "ean": "3560070987654"},
        {"name": "Eau de source 6x1,5L", "brand": "CRISTALINE", "price": 1.74, "quantity_label": "6x1,5L",
         "ean": "3254381025063"},
    ],
    "intermarche": [
        {"name": "Farine de blé T45", "brand": "Chabrior", "price": 0.89, "unit_price_label": "0,89 €/Kg",
         "quantity_label": "1 kg", "ean": "3250390018575"},
        {"name": "Huile de tournesol", "brand": "Itinéraire des Saveurs", "price": 1.85, "quantity_label": "1 L",
         "ean": "3250391234567"},
    ],
    "coursesu": [
        {"name": "Farine de blé T45 U", "brand": "U", "price": 0.95, "unit_price_label": "0,95 € / kg",
         "quantity_label": "1 kg", "promo": "Au lieu de 1,10 €"},
        {"name": "Huile de tournesol U", "brand": "U", "price": 1.99, "quantity_label": "1 L"},
    ],
}

INTERMARCHE_STORES = [
    StoreOption(id="08012", name="Intermarché Super Montpellier Près d'Arènes",
                address="120 avenue de Palavas, 34070 Montpellier", distance_km=1.4),
    StoreOption(id="06814", name="Intermarché Hyper Lattes", address="Route de Mauguio, 34970 Lattes", distance_km=5.2),
    StoreOption(id="08890", name="Intermarché Contact Lavérune", address="2 rue du Château, 34880 Lavérune",
                distance_km=8.9),
]

TOWNS = {
    "34000": [("Montpellier", 43.61, 3.87)],
    "34970": [("Lattes", 43.57, 3.90)],
    "34480": [("Magalas", 43.47, 3.22), ("Puissalicon", 43.46, 3.24), ("Pouzolles", 43.48, 3.27),
              ("Autignac", 43.50, 3.17), ("Laurens", 43.52, 3.19)],
    "99999": [],
}

BLOCKED_MESSAGE = (
    "Courses U affiche une vérification anti-robot. Ouvrez le navigateur PrixMalin "
    "(Réglages → Ouvrir le site) et validez-la une fois."
)
STORE_MESSAGE = "Choisissez votre magasin Intermarché dans les réglages pour voir les prix."

# Seconds before each retailer answers: a number or a (min, max) range
DELAYS: dict[str, float | tuple[float, float]] = {}
CATALOG: dict[str, list[dict]] = {}


class State:
    """What the fake sites remember (reset between tests)."""

    def __init__(self) -> None:
        self.unblocked: set[str] = set()  # retailers whose anti-robot check was passed
        self.opened: list[str | None] = []  # retailers opened with « Ouvrir le site »
        self.scrapes: list[tuple[str, str]] = []  # (retailer, query) of each real scrape


state = State()


def reset() -> None:
    global state
    state = State()
    browser.setup_mode = False


def load_catalogs() -> dict[str, list[dict]]:
    """BASE_CATALOG plus the products of every tests/e2e/catalog_*.py module."""
    catalog = {key: list(products) for key, products in BASE_CATALOG.items()}
    for module in extra_modules():
        for key, products in getattr(module, "PRODUCTS", {}).items():
            catalog.setdefault(key, []).extend(products)
    return catalog


def extra_modules() -> list:
    folder = Path(__file__).parent
    names = sorted(m.name for m in pkgutil.iter_modules([str(folder)]) if m.name.startswith("catalog_"))
    return [importlib.import_module(f"tests.e2e.{name}") for name in names]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", matching.normalize(text)).strip("-")


def matches(name: str, query: str) -> bool:
    """A product is returned when its name shares a keyword with the query."""
    wanted = {matching.stem(w) for w in matching.keywords(query)}
    present = {matching.stem(t) for t in matching.tokenize(name)}
    return bool(wanted & present)


def products_for(key: str, query: str) -> list[Product]:
    return [
        Product(**{"store": key, "product_url": f"https://example.com/{key}/{_slug(p['name'])}-{index}", **p})
        for index, p in enumerate(CATALOG.get(key, []))
        if matches(p["name"], query)
    ]


async def _wait(key: str) -> None:
    delay = DELAYS.get(key, DELAYS.get("*", 0))
    if isinstance(delay, tuple):
        delay = random.uniform(*delay)  # noqa: S311 (not cryptographic)
    if delay:
        await asyncio.sleep(delay)


async def fake_scrape(scraper, query, store):
    await _wait(scraper.key)
    if scraper.key == "intermarche" and store is None:
        raise StoreRequiredError(STORE_MESSAGE)
    if scraper.key == "coursesu" and "coursesu" not in state.unblocked:
        raise BlockedError(BLOCKED_MESSAGE)
    state.scrapes.append((scraper.key, query))
    return products_for(scraper.key, query)


async def fake_geocode(postal_code):
    towns = TOWNS.get(postal_code, [(f"Ville {postal_code}", 45.0, 4.0)])
    return [Location(postal_code=postal_code, city=city, lat=lat, lon=lon) for city, lat, lon in towns]


async def fake_run(key, fn, *args, timeout=None, **kwargs):
    if getattr(fn, "__name__", "") != "find_stores":
        raise RuntimeError("pas de vrai navigateur dans les tests")
    await _wait(key)
    return list(INTERMARCHE_STORES)


async def fake_open_setup(key, url):
    state.opened.append(key)
    browser.setup_mode = True


async def fake_end_setup():
    browser.setup_mode = False
    # The user went through the anti-robot check of the sites he opened
    state.unblocked.update(k for k in state.opened if k)


async def fake_set_show_browser(show):
    browser.show_browser = show
    browser._headless = not show


class _Patcher:
    """Minimal stand-in for pytest's MonkeyPatch (used by the demo)."""

    def __init__(self) -> None:
        self._undo: list = []

    def setattr(self, target, name, value):
        self._undo.append((target, name, getattr(target, name)))
        setattr(target, name, value)

    def undo(self) -> None:
        for target, name, value in reversed(self._undo):
            setattr(target, name, value)
        self._undo.clear()


def install(mp=None, delays: dict | None = None):
    """Replace the outside world with the fakes; returns the patcher (``undo()``)."""
    mp = mp or _Patcher()
    CATALOG.clear()
    CATALOG.update(load_catalogs())
    DELAYS.clear()
    DELAYS.update(delays or {})
    reset()
    mp.setattr(search, "_scrape", fake_scrape)
    mp.setattr(settings, "geocode", fake_geocode)
    mp.setattr(browser, "run", fake_run)
    mp.setattr(browser, "open_setup", fake_open_setup)
    mp.setattr(browser, "end_setup", fake_end_setup)
    mp.setattr(browser, "set_show_browser", fake_set_show_browser)
    for module in extra_modules():
        if hasattr(module, "install"):
            module.install(sys.modules[__name__], mp)
    return mp
