"""Products of the basket for the P5 E2E tests and the demo, and reset of the P5 tables.

A basket « beurre, sucre, jus d'orange (6 L), lessive » (with « farine » and
« huile de tournesol » of the base catalog):

- Lidl is the cheapest on what it has, but has no orange juice: its estimated
  total adds the median of the others;
- Carrefour has everything (complete basket), the butter has an EAN;
- the orange juice is cheaper by 6 x 1 L pack at Aldi for a target of 6 L;
- Intermarché asks for a store, Courses U for its anti-robot check (fake.py).

The names avoid the words searched by the other tests (farine, blé, eau, lait,
huile, tournesol, pirate, tomate, vinaigre, pois, crème).
Each test starts with no saved list, no usual item and no last basket.
"""

import re
import sqlite3
from pathlib import Path

from backend import config

BUTTER_EAN = "3228021170015"

PRODUCTS = {
    "aldi": [
        {"name": "Beurre doux", "brand": "MILSANI", "price": 1.89, "quantity_label": "250 g"},
        {"name": "Sucre en poudre", "brand": "BELBAKE", "price": 1.09, "quantity_label": "1 kg"},
        {"name": "Jus d'orange", "brand": "RIO D'ORO", "price": 1.29, "quantity_label": "1 L"},
        {"name": "Jus d'orange 6x1L", "brand": "RIO D'ORO", "price": 6.90, "quantity_label": "6 x 1 L"},
    ],
    "lidl": [
        {"name": "Beurre doux", "brand": "Milbona", "price": 1.79, "quantity_label": "250 g"},
        {"name": "Sucre en poudre", "brand": "Belbake", "price": 0.99, "quantity_label": "1 kg"},
        {"name": "Lessive liquide", "brand": "W5", "price": 4.99, "quantity_label": "2 L"},
    ],
    "carrefour": [
        {
            "name": "Beurre doux",
            "brand": "PRÉSIDENT",
            "price": 2.05,
            "quantity_label": "250 g",
            "ean": BUTTER_EAN,
        },
        {"name": "Sucre en poudre", "brand": "CARREFOUR", "price": 1.15, "quantity_label": "1 kg"},
        {"name": "Jus d'orange", "brand": "CARREFOUR", "price": 1.45, "quantity_label": "1 L"},
        {"name": "Lessive liquide", "brand": "CARREFOUR", "price": 5.49, "quantity_label": "2 L"},
    ],
    "intermarche": [
        {"name": "Beurre doux", "brand": "Pâturages", "price": 1.99, "quantity_label": "250 g"},
    ],
    "coursesu": [
        {"name": "Beurre doux U", "brand": "U", "price": 1.95, "quantity_label": "250 g"},
    ],
}

# Tables of P5 emptied before each test (the list itself: tests/e2e/server.reset_data)
TABLES = ("list_history", "templates", "basket_last", "list_trash")


def reset_p5() -> None:
    db_path = Path(config.DB_PATH)
    if not db_path.exists():
        return
    with sqlite3.connect(db_path, timeout=5) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table in TABLES:
            if table in tables:
                db.execute(f"DELETE FROM {table}")  # noqa: S608 (fixed table names)
    db.close()


def install(fake, mp) -> None:
    base_reset = fake.reset

    def reset() -> None:
        base_reset()
        reset_p5()

    mp.setattr(fake, "reset", reset)


# --- Helpers of the P5 E2E tests (tests/e2e/test_p5_*.py) ----------------------

HEADERS = {"X-PrixMalin": "1"}
STORES = ["aldi", "lidl", "carrefour", "intermarche", "coursesu"]


def call(page, method: str, path: str, body=None):
    """JSON answer of the PrixMalin API, through the context of ``page``."""
    response = page.request.fetch(f"{page.base}{path}", method=method, data=body, headers=HEADERS)
    assert response.ok, f"{method} {path}: {response.status} {response.text()}"
    return response.json() if response.status != 204 else None


def add(page, query: str, **body) -> dict:
    return call(page, "POST", "/api/list", {"query": query, **body})


def demo_list(page) -> list[dict]:
    """« beurre, sucre, lessive, jus d'orange (6 L) ».

    Carrefour has everything, Lidl has no orange juice, Aldi no washing liquid.
    """
    for query in ("beurre", "sucre", "lessive"):
        add(page, query)
    add(page, "jus d'orange", target="6 L")
    return call(page, "GET", "/api/list")


def compare(page, stores=STORES) -> dict:
    """The basket compared by the server (as « Comparer mon panier »), kept as the last basket."""
    return call(page, "POST", "/api/basket/compare", {"stores": list(stores)})


def horizontal_overflow(page) -> int:
    """Pixels the page can be scrolled sideways (0: none)."""
    return page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")


def pdf_pages(page) -> int:
    """Number of A4 pages of the printed page (css/print.css)."""
    return len(re.findall(rb"/Type\s*/Page\b", page.pdf(format="A4")))
