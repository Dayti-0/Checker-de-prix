"""Relevance through the running server (fake retailers of catalog_p2): API of the search and of the basket.

The screens of the results are tested by the frontend tests of P2; these tests
check what the server sends them.
"""

import pytest

from backend.services.matching import RELEVANT_SCORE

SUNFLOWER = ("Thon", "Sardines", "Mayonnaise", "Chips")


def get(page, path, **params):
    response = page.request.get(f"{page.base}{path}", params=params)
    assert response.ok, response.text()
    return response.json()


def main_list(result):
    return [p for p in result["products"] if p["relevance"] >= 1]


@pytest.mark.parametrize("query", ["huile de tournesols", "huile de tournesol", "huile tournesol"])
def test_food_in_oil_is_never_the_oil(desktop, query):
    response = get(desktop, "/api/search", q=query, stores="aldi,lidl,carrefour")
    results = {r["store"]: r for r in response["results"]}
    assert {k: [p["name"] for p in main_list(r)] for k, r in results.items()} == {
        "aldi": ["Huile de tournesol", "Huile de tournesol bio"],
        "lidl": ["Huile de tournesol", "Lesieur Huile de tournesol"],  # the brand first is still the oil
        "carrefour": ["Huile de tournesol", "Huile de tournesol"],  # Carrefour Classic' then Lesieur
    }
    close = [p for r in results.values() for p in r["products"] if 0 < p["relevance"] < 1]
    assert {p["name"].split()[0] for p in close} == set(SUNFLOWER)
    assert all(p["match_score"] < RELEVANT_SCORE and p["match_reason"] == "complement" for p in close)
    # « Le moins cher » is an oil (Lidl 1,79 €), not the chips at 0,79 €
    cheapest = min((p for r in results.values() for p in main_list(r)), key=lambda p: p["price"])
    assert (cheapest["store"], cheapest["price"]) == ("lidl", 1.79)


def test_tuna_query_keeps_tuna_in_oil(desktop):
    aldi = get(desktop, "/api/search/aldi", q="thon huile de tournesol")
    assert [p["name"] for p in main_list(aldi)] == ["Thon à l'huile de tournesol"]


def test_sauce_is_not_tomatoes(desktop):
    lidl = get(desktop, "/api/search/lidl", q="tomates")
    assert [p["name"] for p in main_list(lidl)] == ["Tomates pelées"]
    aldi = get(desktop, "/api/search/aldi", q="tomate")
    assert main_list(aldi) == []
    assert aldi["products"][0]["match_reason"] == "other_product"
    assert [p["name"] for p in main_list(get(desktop, "/api/search/aldi", q="sauce tomate"))] == [
        "Sauce tomate basilic"
    ]


def test_basket_picks_an_oil_never_the_tuna(desktop):
    page = desktop
    assert page.request.post(f"{page.base}/api/list", data={"query": "huile de tournesols"}).ok
    response = page.request.post(f"{page.base}/api/basket/compare", data={"stores": ["aldi", "lidl", "carrefour"]})
    assert response.ok
    baskets = {b["store"]: b for b in response.json()["stores"]}
    picked = {k: b["lines"][0]["product"]["name"] for k, b in baskets.items()}
    assert picked == {"aldi": "Huile de tournesol", "lidl": "Huile de tournesol", "carrefour": "Huile de tournesol"}
    assert {k: b["total"] for k, b in baskets.items()} == {"aldi": 1.89, "lidl": 1.79, "carrefour": 1.95}


def test_same_barcode_at_several_retailers(desktop):
    response = get(desktop, "/api/search", q="vinaigre de vin rouge", stores="carrefour,lidl")
    maille = [p for r in response["results"] for p in main_list(r) if p["ean"] == "3036810201006"]
    assert sorted((p["store"], p["price"]) for p in maille) == [("carrefour", 1.95), ("lidl", 2.09)]


def test_flags_units_and_order(desktop):
    aldi = get(desktop, "/api/search/aldi", q="vinaigre")
    cider = next(p for p in aldi["products"] if p["name"] == "Vinaigre de cidre bio")
    assert (cider["bio"], cider["old_price"], cider["unit"], cider["unit_price"]) == (True, 1.49, "L", 2.38)

    carrefour = get(desktop, "/api/search/carrefour", q="vinaigre")
    assert carrefour["products"][-1]["available"] is False  # unavailable last
    assert carrefour["products"][-1]["store_brand"] is True

    cream = get(desktop, "/api/search", q="crème fraîche", stores="carrefour,lidl")
    units = {r["store"]: (main_list(r)[0]["unit_price"], main_list(r)[0]["unit"]) for r in cream["results"]}
    assert units == {"carrefour": (4.6, "L"), "lidl": (7.25, "kg")}
