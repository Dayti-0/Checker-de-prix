"""Pure functions of the search page (rank, group, summary, suggestions...), run in the page with js_eval."""

import pytest

from tests.e2e.helpers import js_eval

RANK = "/static/js/views/search/rank.js"
GROUP = "/static/js/views/search/group.js"
SUGGEST = "/static/js/views/search/autocomplete.js"
ROW = "/static/js/views/search/product-row.js"
SUMMARY = "/static/js/views/search/summary.js"
ORDER = ["aldi", "lidl", "carrefour", "intermarche", "coursesu"]


def product(store, name, price, **extra):
    return {
        "store": store,
        "name": name,
        "price": price,
        "product_url": f"https://example.com/{store}/{name}-{price}".replace(" ", "-"),
        "relevance": 1,
        "match_score": 1,
        "available": True,
        **extra,
    }


OIL = [
    product("aldi", "Huile de tournesol", 1.89, unit_price=1.89, unit="L"),
    product("aldi", "Thon à l'huile de tournesol", 0.99, relevance=0.99, match_score=0.6, unit_price=6.19, unit="kg"),
    product("lidl", "Huile de tournesol", 1.79, unit_price=1.79, unit="L"),
    product("lidl", "Chips à l'huile de tournesol", 0.79, relevance=0.99, match_score=0.55),
    product("carrefour", "Huile de tournesol", 2.65, unit_price=2.65, unit="L", available=False),
    product("carrefour", "Huile de tournesol", 1.95, unit_price=1.95, unit="L"),
]


@pytest.fixture
def page(desktop):
    desktop.goto(desktop.base)
    return desktop


def test_relevant_and_close_products(page):
    relevant = js_eval(page, RANK, "relevantOf", {"products": OIL})
    assert [p["name"] for p in relevant] == ["Huile de tournesol"] * 4
    close = js_eval(page, RANK, "closeOf", {"products": OIL})
    assert [p["name"].split()[0] for p in close] == ["Thon", "Chips"]


def test_product_keys_are_unique_even_with_a_shared_link(page):
    """A site may link several products to the same page: they stay distinct rows (and « + »)."""
    home = "https://www.aldi.fr/"
    a = product("aldi", "Farine de blé T55", 0.79, product_url=home, quantity_label="1 kg")
    b = product("aldi", "Farine de blé T55", 1.49, product_url=home, quantity_label="2 kg")
    c = product("aldi", "Farine de seigle", 0.79, product_url=home, quantity_label="1 kg")
    keys = [js_eval(page, RANK, "productKey", p) for p in (a, b, c)]
    assert len(set(keys)) == 3, keys


def test_rank_by_price_is_stable_and_puts_the_unavailable_last(page):
    ranked = js_eval(page, RANK, "rank", OIL[::-1], {"sort": "price", "order": ORDER})
    assert [(p["store"], p["price"]) for p in ranked] == [
        ("lidl", 0.79),
        ("aldi", 0.99),
        ("lidl", 1.79),
        ("aldi", 1.89),
        ("carrefour", 1.95),
        ("carrefour", 2.65),  # unavailable: last whatever its price
    ]
    # Same prices: the order of the retailers, then the name (stable between two answers)
    same = [product("carrefour", "B", 1.0), product("aldi", "B", 1.0), product("aldi", "A", 1.0)]
    assert [(p["store"], p["name"]) for p in js_eval(page, RANK, "rank", same, {"order": ORDER})] == [
        ("aldi", "A"),
        ("aldi", "B"),
        ("carrefour", "B"),
    ]


def test_cheapest_is_never_a_close_product(page):
    cheapest = js_eval(page, RANK, "cheapest", OIL, ORDER)
    assert (cheapest["store"], cheapest["price"], cheapest["name"]) == ("lidl", 1.79, "Huile de tournesol")


def test_unit_prices_are_compared_in_the_dominant_unit_only(page):
    cream = [
        product("carrefour", "Crème fraîche épaisse", 0.92, unit_price=4.6, unit="L"),
        product("lidl", "Crème fraîche épaisse", 1.45, unit_price=7.25, unit="kg"),
        product("aldi", "Crème fraîche légère", 1.10, unit_price=5.5, unit="L"),
    ]
    assert js_eval(page, RANK, "dominantUnit", cream) == "L"
    ranked = js_eval(page, RANK, "rank", cream, {"sort": "unit", "unit": "L", "order": ORDER})
    # €/kg is not compared with €/L: the product in kg goes after
    assert [p["store"] for p in ranked] == ["carrefour", "aldi", "lidl"]
    summary = js_eval(
        page,
        RANK,
        "summarize",
        {
            "carrefour": {"status": "ok", "products": cream[:1]},
            "lidl": {"status": "ok", "products": cream[1:2]},
            "aldi": {"status": "ok", "products": cream[2:]},
        },
        ["aldi", "lidl", "carrefour"],
        {"sort": "unit"},
    )
    assert summary["headline"] == "Meilleur prix au L"
    lines = {line["key"]: line for line in summary["lines"]}
    assert lines["carrefour"]["value"] == 4.6
    assert lines["lidl"]["value"] is None  # its price per kg is not shown against €/L
    assert lines["aldi"]["value"] == 5.5
    assert summary["savings"] == 0.9
    # A tie between two units: kg first
    assert js_eval(page, RANK, "dominantUnit", cream[:2]) == "kg"


def test_summary_gaps_bars_and_savings(page):
    results = {
        "aldi": {"status": "ok", "products": OIL[:2]},
        "lidl": {"status": "ok", "products": OIL[2:4]},
        "carrefour": {"status": "ok", "products": OIL[4:]},
        "intermarche": {"status": "store_required", "products": []},
        "coursesu": {"status": "loading"},
    }
    s = js_eval(page, RANK, "summarize", results, ORDER, {"sort": "price"})
    assert s["headline"] == "Le moins cher"
    assert (s["best"]["store"], s["best"]["price"]) == ("lidl", 1.79)
    lines = {line["key"]: line for line in s["lines"]}
    assert {k: line["state"] for k, line in lines.items()} == {
        "aldi": "ok",
        "lidl": "ok",
        "carrefour": "ok",
        "intermarche": "error",
        "coursesu": "loading",
    }
    assert lines["aldi"]["gap"] == {"abs": 0.1, "pct": 6}
    assert lines["lidl"]["gap"] is None
    assert lines["carrefour"]["value"] == 1.95  # the unavailable 2,65 € is never its best price
    assert lines["carrefour"]["bar"] == 100 and lines["lidl"]["bar"] == 92
    assert s["savings"] == 0.16
    assert (s["done"], s["total"]) == (4, 5)
    assert js_eval(page, RANK, "gapText", {"abs": 0.1, "pct": 13}, "kg") == "+0,10 €/kg, +13 %"
    assert js_eval(page, RANK, "gapText", None) == ""


def test_group_by_barcode(page):
    ean = "3036810201006"
    ranked = [
        product("carrefour", "Vinaigre de vin rouge", 1.95, ean=ean),
        product("aldi", "Vinaigre de cidre bio", 1.99),
        product("intermarche", "Vinaigre de vin rouge", 2.05, ean=ean),
        product("lidl", "Vinaigre de vin rouge", 2.09, ean=ean),
        product("lidl", "Vinaigre blanc", 0.49),
    ]
    groups = js_eval(page, GROUP, "group", ranked)
    assert [[p["store"] for p in g["products"]] for g in groups] == [
        ["carrefour", "intermarche", "lidl"],
        ["aldi"],
        ["lidl"],
    ]
    assert groups[0]["key"] == f"ean:{ean}"
    assert js_eval(page, GROUP, "storeCount", groups[0]) == 3
    # Never a fuzzy grouping: same name without barcode stays apart
    alone = [product("aldi", "Vinaigre", 1.0), product("lidl", "Vinaigre", 1.0)]
    assert len(js_eval(page, GROUP, "group", alone)) == 2


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("chocolat noir 100 g", ["chocolat noir", "chocolat", "noir"]),
        ("eau 1,5 l", ["eau"]),
        ("eau minérale 6x1,5L", ["eau minérale", "eau", "minérale"]),
        ("huile d'olive", ["huile", "olive"]),
        ("chocolat", []),
        ("eau -javel", ["eau"]),
    ],
)
def test_shorter_queries(page, query, expected):
    assert js_eval(page, RANK, "shorterQueries", query) == expected


def test_suggestions_prefix_first_then_frequency(page):
    sources = {
        "recent": [{"q": "huile de tournesol", "n": 1, "t": 0}, {"q": "farine", "n": 3, "t": 0}],
        "list": ["sucre", "huile d'olive"],
        "foods": ["Huile de colza", "Thé", "Chou", "Échalotes", "Pâtes", "Sauce soja", "Lait", "Café moulu"],
    }
    values = lambda typed: [s["value"] for s in js_eval(page, SUGGEST, "suggest", typed, sources)]  # noqa: E731
    # Prefix first (recent, then list, then common products), then « a word starts with »
    assert values("hu") == ["huile de tournesol", "huile d'olive", "Huile de colza"]
    assert values("sau") == ["Sauce soja"]
    assert values("so") == ["Sauce soja"]  # a word of the name starts with « so »
    # Accents and case do not matter; the accents of the names are kept
    assert values("ECHA") == ["Échalotes"]
    assert values("pate") == ["Pâtes"]
    # Empty: the recent searches only, the most searched first
    assert values("") == ["farine", "huile de tournesol"]
    assert js_eval(page, SUGGEST, "suggest", "hu", sources)[0]["source"] == "recent"
    assert js_eval(page, SUGGEST, "matchLevel", "Café moulu", "mou") == 1
    assert js_eval(page, SUGGEST, "matchLevel", "Café moulu", "oul") == 2
    assert js_eval(page, SUGGEST, "matchLevel", "Café moulu", "xyz") == -1


def test_texts_of_a_row(page):
    assert js_eval(page, ROW, "brandText", "CARREFOUR CLASSIC'") == "Carrefour Classic'"
    assert js_eval(page, ROW, "brandText", "SAINT-ELOI") == "Saint-Eloi"
    assert js_eval(page, ROW, "brandText", "Vita D'or") == "Vita D'or"
    assert js_eval(page, ROW, "brandText", "U") == "U"
    assert js_eval(page, ROW, "unitLabel", {"unit_price": 0.27, "unit": "pièce", "count_label": "œuf"}) == "0,27 €/œuf"
    assert js_eval(page, ROW, "unitLabel", {"unit_price": 1.79, "unit": "L"}) == "1,79 €/L"
    assert (
        js_eval(
            page,
            ROW,
            "productLabel",
            {"store": "carrefour", "name": "Huile de tournesol", "brand": "LESIEUR", "price": 2.65},
        )
        == "Huile de tournesol Lesieur (Carrefour, 2,65 €)"
    )


def test_freshness_texts(page):
    now = 1_800_000_000_000
    assert js_eval(page, SUMMARY, "freshnessText", now / 1000 - 60, now) == ""
    assert js_eval(page, SUMMARY, "freshnessText", now / 1000 - 2 * 3600, now) == "prix d'il y a 2 h"
    assert js_eval(page, SUMMARY, "freshnessText", now / 1000 - 26 * 3600, now) == "prix d'hier"
    assert js_eval(page, SUMMARY, "freshnessText", now / 1000 - 9 * 86400, now).startswith("prix du ")
    assert js_eval(page, SUMMARY, "slowAfter", None) == 15000
    assert js_eval(page, SUMMARY, "slowAfter", 20000) == 30000
