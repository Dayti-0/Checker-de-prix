"""The API keeps the products searched apart from the « Produits proches » (B35, B31, B37)."""

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.models import Product
from backend.services import search
from backend.services.matching import RELEVANT_SCORE


def item(store, name, price, **kw):
    return Product(store=store, name=name, price=price, product_url=f"https://{store}.example/{name}", **kw)


# Tuna, sardines... are cheaper than the oil: they must never be « the cheapest oil »
CATALOG = {
    "aldi": [
        item("aldi", "Thon à l'huile de tournesol", 0.99, quantity_label="160 g"),
        item("aldi", "Sardines à l'huile de tournesol", 1.15),
        item("aldi", "Huile de tournesol", 1.89, brand="Bellasan", quantity_label="1 L"),
        item("aldi", "Thon au naturel", 0.89),
    ],
    "lidl": [
        item("lidl", "Mayonnaise à l'huile de tournesol", 1.09),
        item("lidl", "Chips à l'huile de tournesol", 0.79),
        item("lidl", "Lesieur Huile de tournesol", 2.49, quantity_label="1 L"),
        item("lidl", "Huile de tournesol bio", 2.99, quantity_label="1 L"),
    ],
    # Only food in sunflower oil: nothing to buy for « huile de tournesol »
    "carrefour": [
        item("carrefour", "Thon albacore à l'huile de tournesol PETIT NAVIRE", 1.95),
        item("carrefour", "Maquereaux à l'huile de tournesol", 1.49),
    ],
}


@pytest.fixture
def client(monkeypatch):
    async def scrape(scraper, query, store):
        return [p.model_copy() for p in CATALOG.get(scraper.key, [])]

    monkeypatch.setattr(search, "_scrape", scrape)
    with TestClient(main.app) as c:
        yield c


def relevant_names(result):
    return [p["name"] for p in result["products"] if p["relevance"] >= 1]


@pytest.mark.parametrize("query", ["huile de tournesols", "huile de tournesol", "huile tournesol"])
def test_search_of_one_retailer_separates_the_products(client, query):
    aldi = client.get("/api/search/aldi", params={"q": query}).json()
    assert aldi["status"] == "ok"
    assert relevant_names(aldi) == ["Huile de tournesol"]
    by_name = {p["name"]: p for p in aldi["products"]}
    for name in ("Thon à l'huile de tournesol", "Sardines à l'huile de tournesol"):
        close = by_name[name]
        assert 0 < close["relevance"] < 1  # « Produits proches »
        assert close["match_score"] < RELEVANT_SCORE
        assert close["match_reason"] == "complement"
    assert by_name["Thon au naturel"]["relevance"] == 0
    # The products searched come first, then the closest ones
    assert aldi["products"][0]["name"] == "Huile de tournesol"
    assert aldi["products"][0]["match_score"] >= RELEVANT_SCORE
    assert aldi["products"][0]["match_reason"] is None


def test_search_of_every_retailer(client):
    response = client.get("/api/search", params={"q": "huile de tournesols", "stores": "aldi,lidl,carrefour"}).json()
    results = {r["store"]: r for r in response["results"]}
    assert relevant_names(results["aldi"]) == ["Huile de tournesol"]
    assert relevant_names(results["lidl"]) == ["Lesieur Huile de tournesol", "Huile de tournesol bio"]
    assert relevant_names(results["carrefour"]) == []
    # « Le moins cher » among the products searched: the oil of Aldi, not the chips at 0,79 €
    relevant = [p for r in results.values() for p in r["products"] if p["relevance"] >= 1]
    assert min(relevant, key=lambda p: p["price"])["name"] == "Huile de tournesol"
    assert len(relevant) == 3  # « 3 produits »: the close ones are not counted


def test_tuna_query_keeps_tuna_in_oil(client):
    aldi = client.get("/api/search/aldi", params={"q": "thon huile de tournesol"}).json()
    assert relevant_names(aldi) == ["Thon à l'huile de tournesol"]


def test_basket_never_picks_a_close_product(client):
    client.post("/api/list", json={"query": "huile de tournesols"})
    comparison = client.post("/api/basket/compare", json={"stores": ["aldi", "lidl", "carrefour"]}).json()
    baskets = {b["store"]: b for b in comparison["stores"]}
    assert baskets["aldi"]["lines"][0]["product"]["name"] == "Huile de tournesol"
    assert baskets["aldi"]["total"] == 1.89
    assert baskets["lidl"]["lines"][0]["product"]["name"] == "Lesieur Huile de tournesol"
    assert baskets["lidl"]["total"] == 2.49
    # Only tuna and mackerel at Carrefour: the item is missing, not replaced by tuna
    assert baskets["carrefour"]["lines"][0]["product"] is None
    assert baskets["carrefour"]["missing"] == 1
    assert comparison["best_store"] == "aldi"
    assert comparison["split_total"] == 1.89


def test_products_carry_flags_and_checked_barcodes(client, monkeypatch):
    products = [
        item("carrefour", "Farine de blé T45", 0.85, brand="CARREFOUR CLASSIC'", ean="3560070472888"),
        item("carrefour", "Farine de blé T65 bio", 1.45, brand="Francine", ean="3560070472889"),  # wrong check digit
        item("carrefour", "Farine de blé T45", 0.85, brand="CARREFOUR CLASSIC'", ean="3560070472888"),  # same EAN
        item("carrefour", "Farine de seigle", 1.10, available=False),
    ]

    async def scrape(scraper, query, store):
        return [p.model_copy() for p in products]

    monkeypatch.setattr(search, "_scrape", scrape)
    result = client.get("/api/search/carrefour", params={"q": "farine"}).json()
    names = [(p["name"], p["ean"], p["bio"], p["store_brand"], p["available"]) for p in result["products"]]
    assert names == [
        ("Farine de blé T45", "3560070472888", False, True, True),
        ("Farine de blé T65 bio", None, True, False, True),
        ("Farine de seigle", None, False, None, False),  # unavailable: last
    ]
