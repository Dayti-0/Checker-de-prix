"""Honest basket comparison (B57), automatic choice (B58), old prices and ghost picks (B63),
prices seen in the store (B71): pure functions of services/basket.py, simulated scores."""

import pytest

from backend.models import ListItem, Pick, Product, StoreResult
from backend.services import basket, optimizer
from backend.services.basket import (
    StoreInfo,
    build_comparison,
    choose_auto,
    choose_line,
    needs_search,
    packs_for,
    parse_target,
    reference_for,
)
from backend.services.matching import RELEVANT_SCORE
from backend.services.shopping_list import pick_from, plural

NOW = 1_760_000_000.0
DAY = 86400.0
WEEKS_6 = 6 * 7 * DAY
LABELS = {
    "aldi": "Aldi",
    "lidl": "Lidl",
    "carrefour": "Carrefour",
    "intermarche": "Intermarché",
    "coursesu": "Courses U",
}


def prod(store, name, price, **kw):
    kw.setdefault("product_url", f"https://{store}.example/{name.replace(' ', '-')}")
    return Product(store=store, name=name, price=price, **kw)


def close(store, name, price, **kw):
    """A « Produit proche »: never chosen by the basket (simulated score)."""
    return prod(store, name, price, relevance=0.5, match_score=RELEVANT_SCORE - 0.2, match_reason="complement", **kw)


def ok(store, products, **kw):
    return StoreResult(store=store, label=LABELS[store], status="ok", products=products, fetched_at=NOW - 60, **kw)


def failed(store, status, message="Impossible"):
    return StoreResult(store=store, label=LABELS[store], status=status, message=message)


def item(item_id, query, **kw):
    return ListItem(id=item_id, query=query, **kw)


def infos(*keys, **failures):
    return [StoreInfo(key=k, label=LABELS[k], failure=failures.get(k)) for k in keys]


# --- Quantities ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 kg", (1.0, "kg")),
        ("6 L", (6.0, "L")),
        ("500 g", (0.5, "kg")),
        ("12", (12.0, "pièce")),
        ("12 œufs", (12.0, "pièce")),
        ("6 x 1,5 L", (9.0, "L")),
        ("500 grammes", (0.5, "kg")),
        ("2 kilos", (2.0, "kg")),
        ("75 centilitres", (0.75, "L")),
        ("1/2 litre", (0.5, "L")),
        ("", None),
        (None, None),
        ("beaucoup", None),
    ],
)
def test_parse_target(text, expected):
    assert parse_target(text) == expected


def test_packs_for_target():
    assert packs_for((6.0, "L"), (1.0, "L")) == 6
    assert packs_for((6.0, "L"), (6.0, "L")) == 1
    assert packs_for((1.0, "kg"), (0.4, "kg")) == 3
    assert packs_for((12.0, "pièce"), (6.0, "pièce")) == 2
    assert packs_for((1.0, "kg"), (1.0, "L")) is None  # never kg against L
    assert packs_for((50.0, "L"), (0.25, "L")) is None  # 200 packs: not a sensible product
    assert packs_for(None, (1.0, "L")) is None


# --- B58: automatic choice ------------------------------------------------------------


def test_water_takes_the_cheapest_litre_not_the_cheapest_bottle():
    products = [prod("aldi", "Eau minérale 50cl", 0.30), prod("aldi", "Eau minérale 6x1,5L", 1.62)]
    water = item(1, "eau")
    line = choose_line(water, "aldi", ok("aldi", products), reference=reference_for(water, [products]), now=NOW)
    assert line.status == "found" and line.basis == "auto"
    assert line.product.name == "Eau minérale 6x1,5L"
    assert line.line_total == 1.62 and line.packs == 1


def test_reference_keeps_the_size_bought_elsewhere():
    """At Carrefour the 1,5 L bottle is the cheapest per litre in the usual size (6 x 1,5 L too big)."""
    carrefour = [
        prod("carrefour", "Eau de source 50cl", 0.35),
        prod("carrefour", "Eau de source 1,5L", 0.45),
        prod("carrefour", "Eau de source 6x1,5L", 1.74),
    ]
    aldi = [prod("aldi", "Eau minérale 1,5L", 0.40)]
    lidl = [prod("lidl", "Eau minérale 1L", 0.39)]
    water = item(1, "eau")
    reference = reference_for(water, [carrefour, aldi, lidl])
    assert reference == (1.5, "L")  # median of the medians of each retailer
    product, packs, basis = choose_auto(carrefour, 1, None, reference)
    assert (product.name, packs, basis) == ("Eau de source 1,5L", 1, "auto")


def test_reference_of_a_chosen_product():
    water = item(1, "eau", picks={"lidl": Pick(store="lidl", name="Eau 6x1,5L", price=1.5)})
    assert reference_for(water, [[prod("aldi", "Eau 50cl", 0.3)]]) == (9.0, "L")


def test_milk_target_6_litres_pack_against_bottles():
    milk = item(2, "lait", target="6 L")
    cheap_pack = [prod("lidl", "Lait demi-écrémé 6x1L", 5.40), prod("lidl", "Lait demi-écrémé 1L", 0.95)]
    line = choose_line(milk, "lidl", ok("lidl", cheap_pack), now=NOW)
    assert (line.product.name, line.packs, line.line_total) == ("Lait demi-écrémé 6x1L", 1, 5.40)
    dear_pack = [prod("lidl", "Lait demi-écrémé 6x1L", 6.00), prod("lidl", "Lait demi-écrémé 1L", 0.95)]
    line = choose_line(milk, "lidl", ok("lidl", dear_pack), now=NOW)
    assert (line.product.name, line.packs, line.line_total) == ("Lait demi-écrémé 1L", 6, 5.70)


def test_eggs_target_in_pieces():
    eggs = item(3, "oeufs", target="12")
    products = [prod("aldi", "Oeufs frais x6", 1.49), prod("aldi", "Oeufs frais x12", 3.20)]
    line = choose_line(eggs, "aldi", ok("aldi", products), now=NOW)
    assert (line.product.name, line.packs, line.line_total) == ("Oeufs frais x6", 2, 2.98)


def test_target_unusable_falls_back_to_the_quantity():
    flour = item(4, "farine", quantity=2, target="2 L")  # litres of flour: no product in L
    products = [prod("aldi", "Farine T55 1kg", 0.79)]
    line = choose_line(flour, "aldi", ok("aldi", products), now=NOW)
    assert (line.packs, line.line_total) == (2, 1.58)


def test_same_barcode_preferred_at_the_other_retailers():
    chosen = Pick(store="carrefour", name="Moutarde Maille", price=1.95, ean="3036810201006", source="site")
    mustard = item(5, "moutarde", picks={"carrefour": chosen})
    lidl = [
        prod("lidl", "Moutarde de Dijon", 0.89),
        prod("lidl", "Moutarde Maille", 2.09, ean="3036810201006"),
    ]
    line = choose_line(mustard, "lidl", ok("lidl", lidl), now=NOW)
    assert (line.product.name, line.basis, line.picked) == ("Moutarde Maille", "ean", False)
    # Not sold there: the automatic choice as usual
    line = choose_line(mustard, "lidl", ok("lidl", lidl[:1]), now=NOW)
    assert (line.product.name, line.basis) == ("Moutarde de Dijon", "auto")


def test_never_a_close_product_and_no_fallback_to_the_best_score():
    oil = item(6, "huile de tournesol")
    products = [
        close("carrefour", "Thon à l'huile de tournesol", 0.99),
        close("carrefour", "Chips à l'huile de tournesol", 0.79),
    ]
    line = choose_line(oil, "carrefour", ok("carrefour", products), now=NOW)
    assert line.status == "not_found" and line.product is None and line.line_total is None
    assert choose_auto(products) is None
    # With a relevant product, the cheaper close ones are still ignored
    products.append(prod("carrefour", "Huile de tournesol", 1.95))
    assert choose_line(oil, "carrefour", ok("carrefour", products), now=NOW).product.name == "Huile de tournesol"


def test_unavailable_and_priceless_products_are_not_chosen():
    flour = item(7, "farine")
    products = [
        prod("aldi", "Farine T45", 0.50, available=False),
        prod("aldi", "Farine T55", None),
        prod("aldi", "Farine T65", 0.99),
    ]
    assert choose_line(flour, "aldi", ok("aldi", products), now=NOW).product.name == "Farine T65"


def test_lowest_price_when_no_contents_are_known():
    products = [prod("aldi", "Sucre en poudre", 1.20), prod("aldi", "Sucre roux", 1.10)]
    assert choose_auto(products)[0].name == "Sucre roux"


# --- B63: chosen products, old prices ----------------------------------------------------


def chosen(store, name, price, **kw):
    kw.setdefault("product_url", f"https://{store}.example/{name.replace(' ', '-')}")
    kw.setdefault("picked_at", NOW - DAY)
    kw.setdefault("price_at", NOW - DAY)
    return Pick(store=store, name=name, price=price, **kw)


def test_chosen_product_takes_the_fresh_price():
    pick = chosen("carrefour", "Farine Francine", 1.70)
    flour = item(8, "farine", quantity=2, picks={"carrefour": pick})
    products = [prod("carrefour", "Farine T45", 0.85), prod("carrefour", "Farine Francine", 1.89)]
    line = choose_line(flour, "carrefour", ok("carrefour", products), now=NOW)
    assert (line.basis, line.picked, line.line_total, line.stale) == ("pick", True, 3.78, False)
    assert line.pick.price == 1.70  # what was saved, for the page
    assert line.alternatives == 2


def test_chosen_product_missing_from_the_results_is_stale():
    pick = chosen("carrefour", "Farine Francine", 1.89, price_at=NOW - 3 * DAY)
    flour = item(8, "farine", picks={"carrefour": pick})
    line = choose_line(flour, "carrefour", ok("carrefour", [prod("carrefour", "Farine T45", 0.85)]), now=NOW)
    assert (line.status, line.basis, line.stale, line.line_total) == ("found", "pick", True, 1.89)
    assert line.message.startswith("Prix du ") and line.message.endswith(", produit non retrouvé")
    assert line.fetched_at == NOW - 3 * DAY


def test_ghost_pick_older_than_a_week_gives_way_to_the_automatic_choice():
    pick = chosen("carrefour", "Farine Francine", 1.89, price_at=NOW - 8 * DAY)
    flour = item(8, "farine", picks={"carrefour": pick})
    line = choose_line(flour, "carrefour", ok("carrefour", [prod("carrefour", "Farine T45", 0.85)]), now=NOW)
    assert (line.basis, line.product.name, line.pick_issue) == ("auto", "Farine T45", "not_found")
    assert line.message == "Le produit choisi n'a pas été retrouvé."
    # Nothing else there: not found, never the ghost
    line = choose_line(flour, "carrefour", ok("carrefour", []), now=NOW)
    assert (line.status, line.product) == ("not_found", None)


def test_unavailable_chosen_product_is_replaced():
    pick = chosen("carrefour", "Farine Francine", 1.89)
    flour = item(8, "farine", picks={"carrefour": pick})
    products = [prod("carrefour", "Farine Francine", 1.89, available=False), prod("carrefour", "Farine T45", 0.85)]
    line = choose_line(flour, "carrefour", ok("carrefour", products), now=NOW)
    assert (line.basis, line.product.name, line.pick_issue) == ("auto", "Farine T45", "unavailable")


def test_unverified_pick_is_counted_with_its_flag():
    pick = chosen("lidl", "Farine T45", 0.10, verified=False, price_at=None, picked_at=NOW - DAY)
    flour = item(8, "farine", picks={"lidl": pick})
    line = choose_line(flour, "lidl", ok("lidl", [prod("lidl", "Farine bio", 1.20)]), now=NOW)
    assert (line.basis, line.stale, line.verified, line.line_total) == ("pick", True, False, 0.10)


def test_chosen_product_found_by_barcode():
    pick = chosen("lidl", "Farine T45", 0.75, product_url="https://lidl.example/old-address", ean="3560070472888")
    flour = item(8, "farine", picks={"lidl": pick})
    products = [prod("lidl", "Farine de blé T45", 0.79, ean="3560070472888")]
    line = choose_line(flour, "lidl", ok("lidl", products), now=NOW)
    assert (line.basis, line.line_total, line.stale) == ("pick", 0.79, False)


def test_old_prices_of_a_failing_site_are_marked():
    result = ok("aldi", [prod("aldi", "Farine T55", 0.79)], stale=True, problem="blocked")
    result.message = "Prix du 03/10 à 14 h (Aldi : vérification requise)"
    line = choose_line(item(9, "farine"), "aldi", result, now=NOW)
    assert (line.status, line.stale, line.message) == ("found", True, result.message)


def test_server_ignores_the_price_sent_by_the_page():
    sent = prod("lidl", "Farine T45", 0.01)
    cached = [prod("lidl", "Farine T45", 0.75), prod("lidl", "Farine T55", 0.79)]
    pick = pick_from(sent, cached, NOW - 600, NOW)
    assert (pick.price, pick.verified, pick.price_at, pick.picked_at) == (0.75, True, NOW - 600, NOW)
    # By barcode when the address changed
    by_ean = pick_from(
        prod("lidl", "Farine", 0.01, ean="3560070472888", product_url="https://lidl.example/x"),
        [prod("lidl", "Farine T45", 0.75, ean="3560070472888")],
        NOW - 600,
        NOW,
    )
    assert (by_ean.price, by_ean.verified) == (0.75, True)
    # Never read: kept, marked « prix non vérifié »
    unknown = pick_from(sent, [], None, NOW)
    assert (unknown.price, unknown.verified, unknown.price_at) == (0.01, False, None)


# --- B71: prices seen in the store ------------------------------------------------------


def manual(store, price, days_ago, **kw):
    return Pick(
        store=store,
        name="Lait vu en magasin",
        price=price,
        source="manual",
        picked_at=NOW - days_ago * DAY,
        price_at=NOW - days_ago * DAY,
        **kw,
    )


def test_manual_price_counted_with_its_flag_then_expired():
    milk = item(10, "lait", quantity=2, picks={"intermarche": manual("intermarche", 1.02, 10)})
    line = choose_line(milk, "intermarche", None, now=NOW, manual_max_age=WEEKS_6)
    assert (line.status, line.basis, line.manual, line.picked, line.line_total) == ("found", "manual", True, True, 2.04)
    assert line.fetched_at == NOW - 10 * DAY
    assert line.expires_at == NOW - 10 * DAY + WEEKS_6  # « à mettre à jour avant le … »
    assert not needs_search(milk, "intermarche", NOW, WEEKS_6)  # no call to the site
    # Six weeks later: shown (pick), not counted
    old = item(10, "lait", picks={"intermarche": manual("intermarche", 1.02, 43)})
    assert needs_search(old, "intermarche", NOW, WEEKS_6)
    line = choose_line(old, "intermarche", failed("intermarche", "store_required", "Magasin à choisir"), now=NOW)
    assert (line.status, line.expired, line.pick_issue, line.line_total) == ("unchecked", True, "expired", None)
    assert line.expires_at == NOW - 43 * DAY + WEEKS_6
    assert line.pick.price == 1.02
    # Expired, but the site answers: its product is counted
    line = choose_line(old, "intermarche", ok("intermarche", [prod("intermarche", "Lait 1L", 1.05)]), now=NOW)
    assert (line.basis, line.expired, line.line_total) == ("auto", True, 1.05)


def test_manual_price_after_a_shorter_setting():
    milk = item(10, "lait", picks={"lidl": manual("lidl", 0.99, 10)})
    assert choose_line(milk, "lidl", None, now=NOW, manual_max_age=7 * DAY).expired


# --- B57: honest comparison -------------------------------------------------------------


def four_items():
    return [item(1, "farine"), item(2, "sucre"), item(3, "lait"), item(4, "beurre")]


def catalog_results(items, catalog, statuses=None):
    """{(store, item id): result} from {store: {query: [(name, price)]}}."""
    statuses = statuses or {}
    results = {}
    for store, by_query in catalog.items():
        for it in items:
            if store in statuses:
                results[(store, it.id)] = failed(store, *statuses[store])
            else:
                found = [prod(store, name, price) for name, price in by_query.get(it.query, [])]
                results[(store, it.id)] = ok(store, found)
    return results


def test_line_statuses():
    items = [item(1, "farine", excluded=["aldi"]), item(2, "sucre")]
    results = {
        ("aldi", 2): ok("aldi", [prod("aldi", "Sucre", 1.0)]),
        ("lidl", 1): ok("lidl", []),
        ("lidl", 2): ok("lidl", [close("lidl", "Bonbons au sucre", 0.5)]),
        ("intermarche", 1): failed("intermarche", "store_required", "Choisissez votre magasin Intermarché."),
        ("intermarche", 2): failed("intermarche", "store_required", "Choisissez votre magasin Intermarché."),
    }
    comparison = build_comparison(items, infos("aldi", "lidl", "intermarche"), results, now=NOW)
    lines = {(b.store, li.item_id): li for b in comparison.stores for li in b.lines}
    assert lines[("aldi", 1)].status == "excluded"
    assert lines[("aldi", 2)].status == "found"
    assert lines[("lidl", 1)].status == "not_found"
    assert lines[("lidl", 2)].status == "not_found"  # only a close product
    assert lines[("intermarche", 1)].status == "unchecked"
    assert lines[("intermarche", 1)].message == "Choisissez votre magasin Intermarché."


def test_lidl_with_two_missing_items_is_no_longer_cheaper_than_aldi_with_one():
    items = four_items()
    catalog = {
        "aldi": {"farine": [("Farine T55", 0.79)], "sucre": [("Sucre", 1.09)], "lait": [("Lait 1L", 0.95)]},
        "lidl": {"farine": [("Farine T45", 0.79)], "sucre": [("Sucre", 1.09)]},
        "carrefour": {
            "farine": [("Farine T45", 0.85)],
            "sucre": [("Sucre", 1.15)],
            "lait": [("Lait 1L", 1.05)],
            "beurre": [("Beurre doux", 2.10)],
        },
    }
    comparison = build_comparison(items, infos("aldi", "lidl", "carrefour"), catalog_results(items, catalog), now=NOW)
    baskets = {b.store: b for b in comparison.stores}
    aldi, lidl, carrefour = baskets["aldi"], baskets["lidl"], baskets["carrefour"]
    # Raw totals: Lidl looks the cheapest, only because two items are missing
    assert (aldi.total, lidl.total, carrefour.total) == (2.83, 1.88, 5.15)
    assert (aldi.missing, lidl.missing, carrefour.missing) == (1, 2, 0)
    # The median of the other retailers is added for each missing item
    assert aldi.estimated_total == 4.93 and aldi.estimated  # + butter 2,10
    assert lidl.estimated_total == 4.98 and lidl.estimated  # + milk median(0,95 ; 1,05) + butter 2,10
    assert [li.estimate for li in lidl.lines] == [None, None, 1.0, 2.1]
    assert carrefour.estimated_total == 5.15 and not carrefour.estimated
    # Complete basket first, then the incomplete ones by estimated total: Lidl after Aldi
    assert comparison.ranking == ["carrefour", "aldi", "lidl"]
    assert comparison.best_store == "carrefour"
    assert [b.rank for b in comparison.stores] == [1, 2, 3]
    # Two items found everywhere: « Sur les 2 articles communs : 1,88 € »
    assert comparison.common_item_ids == [1, 2] and comparison.common_count == 2
    assert (aldi.common_total, lidl.common_total, carrefour.common_total) == (1.88, 1.88, 2.0)
    assert (aldi.found_count, aldi.item_count, aldi.complete, carrefour.complete) == (3, 4, False, True)


def test_no_complete_basket_names_the_retailer_with_the_most_items():
    items = four_items()
    catalog = {
        "aldi": {"farine": [("Farine", 0.79)], "sucre": [("Sucre", 1.09)], "lait": [("Lait", 0.95)]},
        "lidl": {"farine": [("Farine", 0.75)], "sucre": [("Sucre", 0.99)]},
    }
    comparison = build_comparison(items, infos("aldi", "lidl"), catalog_results(items, catalog), now=NOW)
    assert comparison.best_store is None and comparison.complete_count == 0
    assert comparison.most_items_store == "aldi"
    aldi = comparison.stores[comparison.ranking.index("aldi")]
    assert (aldi.found_count, aldi.item_count) == (3, 4)


def test_retailer_that_could_not_be_searched_is_not_ranked():
    items = four_items()
    catalog = {
        "aldi": {q: [(q.title(), 1.0)] for q in ("farine", "sucre", "lait", "beurre")},
        "intermarche": {},
        "coursesu": {},
    }
    statuses = {
        "intermarche": ("store_required", "Choisissez votre magasin Intermarché."),
        "coursesu": ("blocked", "Courses U affiche une vérification anti-robot."),
    }
    failures = {k: failed(k, *v) for k, v in statuses.items()}
    comparison = build_comparison(
        items, infos("aldi", "intermarche", "coursesu", **failures), catalog_results(items, catalog, statuses), now=NOW
    )
    baskets = {b.store: b for b in comparison.stores}
    assert comparison.ranking == ["aldi"] and comparison.best_store == "aldi"
    inter, u = baskets["intermarche"], baskets["coursesu"]
    assert (inter.status, inter.ranked, inter.rank, inter.reason, inter.action) == (
        "unchecked",
        False,
        None,
        "store_required",
        "choose_store",
    )
    assert inter.message == "Choisissez votre magasin Intermarché."
    assert (u.status, u.reason, u.action, u.unchecked_count, u.missing) == ("unchecked", "blocked", "unblock", 4, 4)
    assert inter.estimated_total is None and inter.common_total is None
    # Unranked retailers come after the ranking
    assert [b.store for b in comparison.stores] == ["aldi", "intermarche", "coursesu"]


def test_retailer_with_less_than_half_of_the_items_is_not_ranked():
    items = four_items()
    catalog = {
        "aldi": {q: [(q.title(), 1.0)] for q in ("farine", "sucre", "lait", "beurre")},
        "lidl": {"farine": [("Farine", 0.10)]},
    }
    comparison = build_comparison(items, infos("aldi", "lidl"), catalog_results(items, catalog), now=NOW)
    lidl = next(b for b in comparison.stores if b.store == "lidl")
    assert comparison.ranking == ["aldi"] and not lidl.ranked and lidl.status == "ok"
    # The common items are those of the ranked retailers only
    assert comparison.common_count == 4


def test_an_item_not_available_here_makes_the_basket_incomplete():
    """« Pas disponible ici » is missing too: Lidl (0,99 € for the sugar alone) is never the
    « Panier le moins cher » nor « complet » against Aldi, which has everything for 1,88 €."""
    items = [item(1, "farine", excluded=["lidl"]), item(2, "sucre")]
    catalog = {
        "aldi": {"farine": [("Farine", 0.79)], "sucre": [("Sucre", 1.09)]},
        "lidl": {"farine": [("Farine", 0.75)], "sucre": [("Sucre", 0.99)]},
    }
    comparison = build_comparison(items, infos("aldi", "lidl"), catalog_results(items, catalog), now=NOW)
    baskets = {b.store: b for b in comparison.stores}
    aldi, lidl = baskets["aldi"], baskets["lidl"]
    assert (lidl.missing, lidl.excluded_count, lidl.not_found_count, lidl.unchecked_count) == (1, 1, 0, 0)
    assert not lidl.complete and aldi.complete
    # Estimated as an item not found: the median of the other retailers
    assert lidl.total == 0.99 and lidl.estimated_total == 1.78 and lidl.estimated
    assert lidl.lines[0].estimate == 0.79
    assert comparison.best_store == "aldi" and comparison.complete_count == 1
    assert comparison.ranking == ["aldi", "lidl"]
    assert (aldi.saving, lidl.saving) == (None, None)
    # The optimizer says the same: the single plan is Aldi, complete
    assert comparison.plans[0].kind == "single" and comparison.plans[0].stores[0].store == "aldi"
    assert comparison.plans[0].complete and comparison.plans[0].total == aldi.total


def test_the_cheapest_basket_with_an_item_not_available_is_not_the_cheapest_basket():
    """The case seen in the app: Lidl misses the juice (« pas disponible ici »), Aldi the
    washing powder (not found), Carrefour has everything. Carrefour is « Panier le moins
    cher » at its total, and its saving is computed on the totals of the complete baskets."""
    names = ("beurre", "sucre", "lessive", "jus d'orange", "huile", "farine")
    items = [item(i, q, excluded=["lidl"] if q == "jus d'orange" else []) for i, q in enumerate(names, start=1)]
    prices = {
        "lidl": {"beurre": 1.79, "sucre": 0.99, "lessive": 3.99, "jus d'orange": 5.94, "huile": 1.99, "farine": 0.75},
        "aldi": {"beurre": 1.89, "sucre": 1.09, "jus d'orange": 6.90, "huile": 2.09, "farine": 0.79},
        "carrefour": {
            "beurre": 2.10,
            "sucre": 1.15,
            "lessive": 4.49,
            "jus d'orange": 7.50,
            "huile": 2.29,
            "farine": 0.85,
        },
        "coursesu": {
            "beurre": 2.20,
            "sucre": 1.20,
            "lessive": 4.99,
            "jus d'orange": 7.90,
            "huile": 2.39,
            "farine": 0.89,
        },
    }
    catalog = {store: {q: [(q.title(), p)] for q, p in by_query.items()} for store, by_query in prices.items()}
    stores = infos("lidl", "aldi", "carrefour", "coursesu")
    comparison = build_comparison(items, stores, catalog_results(items, catalog), now=NOW)
    baskets = {b.store: b for b in comparison.stores}
    lidl, aldi, carrefour, u = baskets["lidl"], baskets["aldi"], baskets["carrefour"], baskets["coursesu"]
    assert (lidl.found_count, lidl.missing, lidl.complete, lidl.excluded_count) == (5, 1, False, 1)
    assert lidl.total == 9.51 and lidl.estimated_total == 17.01  # + median(6,90 ; 7,50 ; 7,90)
    assert (aldi.found_count, aldi.missing, aldi.complete) == (5, 1, False)
    assert comparison.best_store == "carrefour" and comparison.complete_count == 2
    assert comparison.ranking == ["carrefour", "coursesu", "lidl", "aldi"]
    assert (carrefour.saving, u.saving, lidl.saving) == (round(u.total - carrefour.total, 2), 0.0, None)
    # The optimizer agrees: the single plan is the basket of the verdict
    single = comparison.plans[0]
    assert single.kind == "single" and single.complete
    assert single.stores[0].store == comparison.best_store and single.total == carrefour.total
    # Lidl alone is never a complete plan
    lidl_alone = next(p for p in optimizer.all_plans(comparison.stores) if [s.store for s in p.stores] == ["lidl"])
    assert not lidl_alone.complete and lidl_alone.missing_item_ids == [4]


def test_items_left_out_of_the_comparison():
    items = [item(1, "farine"), item(2, "sucre", compare=False)]
    catalog = {"aldi": {"farine": [("Farine", 0.79)], "sucre": [("Sucre", 1.09)]}}
    comparison = build_comparison(items, infos("aldi"), catalog_results(items, catalog), now=NOW)
    assert (comparison.item_count, comparison.skipped_count, comparison.skipped_item_ids) == (1, 1, [2])
    assert comparison.stores[0].total == 0.79 and len(comparison.stores[0].lines) == 1


def test_split_total_and_plans_are_filled():
    items = four_items()[:2]
    catalog = {
        "aldi": {"farine": [("Farine", 0.79)], "sucre": [("Sucre", 1.09)]},
        "lidl": {"farine": [("Farine", 0.75)], "sucre": [("Sucre", 0.99)]},
    }
    comparison = build_comparison(items, infos("aldi", "lidl"), catalog_results(items, catalog), now=NOW)
    assert comparison.split_total == 1.74 and comparison.split_missing == 0
    assert comparison.plans[0].kind == "single" and comparison.plans[0].stores[0].store == "lidl"


def test_stale_pick_counted_when_the_site_fails():
    pick = chosen("carrefour", "Farine Francine", 1.89, price_at=NOW - 2 * DAY)
    flour = item(1, "farine", picks={"carrefour": pick})
    line = choose_line(flour, "carrefour", failed("carrefour", "blocked", "Vérification"), now=NOW)
    assert (line.status, line.stale, line.line_total) == ("found", True, 1.89)
    assert "vérification requise" in line.message


def test_basket_signature_follows_what_the_basket_depends_on():
    flour = item(1, "farine", quantity=2)
    base = basket.basket_signature([flour, item(2, "sucre")])
    assert base == basket.basket_signature([item(2, "sucre"), item(1, "farine", quantity=2)])
    # Ticks, notes and aisles: same basket
    same = item(1, "farine", quantity=2, checked=True, checked_at=NOW, note="T45", category="Boulangerie")
    assert basket.basket_signature([same, item(2, "sucre")]) == base
    # Items left out of the comparison do not count either
    assert basket.basket_signature([flour, item(2, "sucre"), item(3, "sel", compare=False)]) == base
    changed = [
        item(1, "farine", quantity=3),
        item(1, "farine", quantity=2, target="2 kg"),
        item(1, "farine", quantity=2, excluded=["lidl"]),
        item(1, "farine", quantity=2, picks={"lidl": Pick(**prod("lidl", "Farine T45", 0.75).model_dump())}),
    ]
    for other in changed:
        assert basket.basket_signature([other, item(2, "sucre")]) != base
    assert basket.basket_signature([flour]) != base


@pytest.mark.parametrize(
    ("n", "expected"),
    [(0, "0 article introuvable"), (1, "1 article introuvable"), (2, "2 articles introuvables")],
)
def test_plural_of_the_glossary(n, expected):
    assert plural(n, "article introuvable", "articles introuvables") == expected


def test_module_exports_of_the_contract():
    for name in ("add_item", "get_list", "update_item", "compare_basket", "choose_line", "MAX_ITEMS"):
        assert hasattr(basket, name)
