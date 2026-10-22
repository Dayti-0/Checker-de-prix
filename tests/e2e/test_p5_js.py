"""Pure functions of « Ma liste », « Mon panier » and « En magasin », run in the page (js_eval)."""

import pytest

from tests.e2e.helpers import js_eval

LIST = "/static/js/views/list/model.js"
BASKET = "/static/js/views/basket/model.js"
SHARE = "/static/js/views/list/share-sheet.js"
EDIT = "/static/js/views/list/edit-sheet.js"
SHOPPING = "/static/js/views/shopping/index.js"

OCT_3 = 1791028800  # 3 October 2026, noon (UTC)
NOV_14 = 1794657600


@pytest.fixture
def page(desktop):
    desktop.goto(desktop.base)
    return desktop


def line(store_status="found", **kw):
    return {"status": store_status, "line_total": None, "basis": "auto", "verified": True, **kw}


def store(key, label, **kw):
    base = {
        "store": key,
        "label": label,
        "status": "ok",
        "total": 0,
        "found_count": 0,
        "item_count": 4,
        "missing": 0,
        "not_found_count": 0,
        "unchecked_count": 0,
        "excluded_count": 0,
        "complete": False,
        "ranked": True,
        "estimated": False,
        "estimated_total": None,
        "common_total": None,
        "saving": None,
        "lines": [],
    }
    return {**base, **kw}


def test_list_helpers(page):
    assert js_eval(page, LIST, "dayText", OCT_3) == "03/10"
    assert js_eval(page, LIST, "dayText", None) == ""
    assert js_eval(page, LIST, "pickParts", {"name": "Farine T45", "price": 0.75}) == {
        "name": "Farine T45",
        "price": "0,75 €",
        "note": "",
    }
    manual = {"name": "Lessive", "price": 4.5, "source": "manual", "picked_at": OCT_3}
    assert js_eval(page, LIST, "pickParts", manual)["note"] == "saisi le 03/10"
    unverified = {"name": "Beurre", "price": 1.9, "verified": False}
    assert js_eval(page, LIST, "pickParts", unverified)["note"] == "prix non vérifié"
    assert js_eval(page, LIST, "quantityText", {"quantity": 2}) == "× 2"
    assert js_eval(page, LIST, "quantityText", {"quantity": 1}) == ""
    assert js_eval(page, LIST, "quantityText", {"quantity": 3, "target": "6 L"}) == ""
    assert js_eval(page, LIST, "counterText", 3, 7, 12.4) == "3/7 · 12,40 €"
    assert js_eval(page, LIST, "counterText", 0, 7, 0) == "0/7"


def test_missing_items_follow_the_glossary(page):
    assert js_eval(page, LIST, "missingText", 0) == "0 article introuvable"
    assert js_eval(page, LIST, "missingText", 1) == "1 article introuvable"
    assert js_eval(page, LIST, "missingText", 2) == "2 articles introuvables"


def test_aisles_in_the_order_of_a_store(page):
    items = [
        {"id": 1, "query": "lessive", "category": "Entretien"},
        {"id": 2, "query": "beurre", "category": "Crèmerie"},
        {"id": 3, "query": "truc", "category": ""},
        {"id": 4, "query": "lait", "category": "Crèmerie"},
        {"id": 5, "query": "machin", "category": "Rayon inconnu"},
    ]
    order = ["Fruits et légumes", "Crèmerie", "Entretien"]
    groups = js_eval(page, LIST, "groupByAisle", items, order)
    assert [(g["name"], [i["id"] for i in g["items"]]) for g in groups] == [
        ("Crèmerie", [2, 4]),
        ("Entretien", [1]),
        ("Autres", [3]),
        ("Rayon inconnu", [5]),
    ]


def test_latest_tick_wins_in_the_offline_queue(page):
    queue = [{"id": 1, "checked": True, "checked_at": 10}, {"id": 2, "checked": True, "checked_at": 10}]
    merged = js_eval(page, LIST, "mergeCheck", queue, {"id": 1, "checked": False, "checked_at": 20})
    assert sorted((c["id"], c["checked"]) for c in merged) == [(1, False), (2, True)]
    older = js_eval(page, LIST, "mergeCheck", queue, {"id": 2, "checked": False, "checked_at": 5})
    assert sorted((c["id"], c["checked"]) for c in older) == [(1, True), (2, True)]


def test_verdict_is_honest(page):
    carrefour = store("carrefour", "Carrefour", total=19.39, found_count=4, complete=True, saving=None)
    aldi = store(
        "aldi", "Aldi", total=9.88, found_count=3, missing=1, not_found_count=1, estimated=True, estimated_total=15.12
    )
    complete = {"item_count": 4, "best_store": "carrefour", "stores": [carrefour, aldi]}
    v = js_eval(page, BASKET, "verdict", complete)
    assert (v["kind"], v["label"]) == ("best", "Panier le moins cher")
    assert (v["storeLabel"], v["value"]) == ("Carrefour", "19,39 €")
    assert v["sub"] == "Seule enseigne avec tous les articles"

    lidl = store(
        "lidl", "Lidl", total=5.20, found_count=2, missing=2, not_found_count=2, estimated=True, estimated_total=15.57
    )
    partial = {"item_count": 4, "best_store": None, "most_items_store": "aldi", "stores": [aldi, lidl]}
    v = js_eval(page, BASKET, "verdict", partial)
    assert v["kind"] == "most"
    assert v["label"] == "Paniers incomplets"
    assert v["text"] == "Aucune enseigne n'a tout : Aldi en a le plus (3/4)"
    assert (v["value"], v["valueLabel"], v["sub"]) == ("15,12 €", "estimé", "Chez Aldi : 1 article introuvable")
    assert "Panier le moins cher" not in str(v)

    # Two retailers with as many items: both are named, the cheaper one leads
    tied = store(
        "lidl", "Lidl", total=7.77, found_count=3, missing=1, not_found_count=1, estimated=True, estimated_total=15.57
    )
    blocked = store("coursesu", "Courses U", total=0, found_count=3, status="unchecked")
    v = js_eval(page, BASKET, "verdict", {"item_count": 4, "most_items_store": "aldi", "stores": [aldi, tied, blocked]})
    assert v["text"] == "Aucune enseigne n'a tout : Aldi et Lidl en ont le plus (3/4)"
    assert v["sub"] == "Total estimé le plus bas : Aldi · Chez Aldi : 1 article introuvable"

    # No retailer with half of the items: the amount says what it covers
    few = store("carrefour", "Carrefour", total=18.24, found_count=5, missing=6, estimated=False, estimated_total=18.24)
    v = js_eval(page, BASKET, "verdict", {"item_count": 11, "most_items_store": "carrefour", "stores": [few]})
    assert (v["value"], v["valueLabel"]) == ("18,24 €", "pour 5 articles")

    nothing = {"item_count": 4, "best_store": None, "most_items_store": None, "stores": []}
    assert js_eval(page, BASKET, "verdict", nothing)["kind"] == "none"
    assert js_eval(page, BASKET, "verdict", {"item_count": 0, "stores": []})["kind"] == "empty"

    cheaper = store("lidl", "Lidl", total=17.0, found_count=4, complete=True, saving=2.39)
    two = {"item_count": 4, "best_store": "lidl", "stores": [cheaper, carrefour]}
    assert js_eval(page, BASKET, "verdict", two)["sub"] == "2,39 € de moins que le panier complet le plus cher"


def test_a_basket_with_an_item_not_available_is_never_the_cheapest(page):
    """Even in a comparison saved by an older version (« best_store » and « complete » on a
    basket where the juice is « pas disponible ici »): « Paniers incomplets », its estimated total."""
    lidl = store(
        "lidl",
        "Lidl",
        total=10.31,
        found_count=5,
        item_count=6,
        missing=0,
        excluded_count=1,
        complete=True,
        saving=2.08,
        estimated=True,
        estimated_total=18.11,
    )
    old = {"item_count": 6, "best_store": "lidl", "most_items_store": None, "stores": [lidl]}
    v = js_eval(page, BASKET, "verdict", old)
    assert (v["kind"], v["label"], v["value"], v["valueLabel"]) == ("most", "Paniers incomplets", "18,11 €", "estimé")
    assert v["text"] == "Aucune enseigne n'a tout : Lidl en a le plus (5/6)"
    assert v["sub"] == "Chez Lidl : 1 article pas disponible"
    assert "Panier le moins cher" not in str(v) and "complet" not in v["text"]
    assert js_eval(page, BASKET, "isComplete", lidl, 6) is False
    assert js_eval(page, BASKET, "isComplete", {**lidl, "found_count": 6}, 6) is True


def test_what_a_basket_does_not_count(page):
    lidl = store("lidl", "Lidl", found_count=1, item_count=6, not_found_count=1, unchecked_count=4)
    assert js_eval(page, BASKET, "absentParts", lidl) == ["1 article introuvable", "4 articles non vérifiés"]
    both = store("lidl", "Lidl", excluded_count=2, unchecked_count=1)
    assert js_eval(page, BASKET, "absentParts", both) == ["1 article non vérifié", "2 articles pas disponibles ici"]
    assert js_eval(page, BASKET, "absentParts", both, "") == ["1 article non vérifié", "2 articles pas disponibles"]
    # Why it is not ranked: the search stopped, or too few items
    stopped = {**lidl, "ranked": False, "reason": "timeout"}
    assert js_eval(page, BASKET, "unrankedText", stopped) == (
        "Pas classée : recherche interrompue (Trop lent à répondre)."
    )
    few = store("lidl", "Lidl", ranked=False, found_count=1, not_found_count=5, item_count=6)
    assert js_eval(page, BASKET, "unrankedText", few) == "Pas classée : moins de la moitié des articles trouvés."
    texts = js_eval(page, BASKET, "storeTexts", {"item_count": 6, "stores": [stopped]}, stopped, 0)
    assert texts["missing"] == "1 article introuvable · 4 articles non vérifiés"


def test_texts_of_a_retailer_card(page):
    aldi = store(
        "aldi",
        "Aldi",
        total=9.88,
        found_count=3,
        missing=1,
        not_found_count=1,
        estimated=True,
        estimated_total=15.12,
        common_total=4.86,
    )
    comparison = {"item_count": 4, "common_count": 3, "stores": [aldi]}
    texts = js_eval(page, BASKET, "storeTexts", comparison, aldi, 0)
    assert texts["count"] == "3/4 articles"
    assert (texts["total"], texts["estimate"], texts["missing"]) == ("9,88 €", "15,12 €", "1 article introuvable")
    assert texts["common"] == "Sur les 3 articles communs : 4,86 €"
    one = {"item_count": 4, "common_count": 1, "stores": [aldi]}
    assert js_eval(page, BASKET, "commonText", one, aldi) == "Sur l'article commun : 4,86 €"
    # Nothing to say when every item is common
    every = {"item_count": 4, "common_count": 4, "stores": [aldi]}
    assert js_eval(page, BASKET, "commonText", every, aldi) == ""


def test_offers_of_an_item_cheapest_first(page):
    order = page.evaluate(
        """async () => {
            const { itemOffers } = await import("/static/js/views/basket/model.js");
            const lines = {
                a: { status: "unchecked" },
                b: { status: "found", line_total: 2.1 },
                c: { status: "not_found" },
                d: { status: "found", line_total: 1.9 },
                e: { status: "excluded" },
            };
            const stores = ["a", "b", "c", "d", "e", "f"].map((s) => ({ store: s, label: s.toUpperCase() }));
            return itemOffers(stores, 7, (store, id) => (id === 7 ? lines[store] : null)).map((o) => o.store);
        }"""
    )
    # Found from the cheapest, then « pas disponible ici », not found, not searched, not read yet
    assert order == ["d", "b", "e", "c", "a", "f"]
    lines = js_eval(
        page,
        BASKET,
        "cheapest",
        [line(line_total=2.0), line(line_total=1.5), line("not_found"), None],
    )
    assert lines == 1.5
    assert js_eval(page, BASKET, "cheapest", [line("not_found")]) is None


def test_notes_of_a_cell(page):
    now = (OCT_3 + 3 * 3600) * 1000
    notes = js_eval(page, BASKET, "cellNotes", line(basis="pick", fetched_at=OCT_3), now)
    assert notes == [{"kind": "pick", "text": "votre choix"}, {"kind": "muted", "text": "prix d'il y a 3 h"}]
    manual = line(basis="manual", manual=True, pick={"picked_at": OCT_3}, expires_at=NOV_14)
    assert [n["text"] for n in js_eval(page, BASKET, "cellNotes", manual, now)] == [
        "saisi le 03/10",
        "à mettre à jour avant le 14/11",
    ]
    stale = line(basis="pick", stale=True, message="Prix du 12/09, produit non retrouvé")
    assert {"kind": "warn", "text": "Prix du 12/09, produit non retrouvé"} in js_eval(
        page, BASKET, "cellNotes", stale, now
    )
    expired = line("not_found", pick_issue="expired")
    assert js_eval(page, BASKET, "cellNotes", expired, now) == [
        {"kind": "warn", "text": "prix saisi trop ancien, non compté"}
    ]
    assert js_eval(page, BASKET, "cellNotes", line(verified=False, basis="ean"), now) == [
        {"kind": "muted", "text": "même code-barres"},
        {"kind": "warn", "text": "prix non vérifié"},
    ]


def test_small_texts_of_the_basket(page):
    assert js_eval(page, BASKET, "progressText", 12, 40) == "12/40 recherches"
    assert js_eval(page, BASKET, "progressText", 0, 1) == "0/1 recherche"
    assert js_eval(page, BASKET, "reasonLabel", "store_required") == "Magasin à choisir"
    assert js_eval(page, BASKET, "reasonLabel", "blocked") == "Vérification requise"
    assert js_eval(page, BASKET, "planTitle", {"complete": True, "stores": [{"label": "Carrefour"}]}) == (
        "Tout chez Carrefour"
    )
    # Never « Tout chez » when an item is missing
    assert js_eval(page, BASKET, "planTitle", {"complete": False, "stores": [{"label": "Aldi"}]}) == (
        "Chez Aldi seulement"
    )
    pair = {"stores": [{"label": "Aldi"}, {"label": "Lidl"}]}
    assert js_eval(page, BASKET, "planTitle", pair) == "Aldi + Lidl"
    # The amount of a plan is never bare when an item is missing
    full = {"complete": True, "estimated": False, "total": 19.39, "stores": [{"item_ids": [1, 2]}]}
    assert js_eval(page, BASKET, "planAmountText", full) == "19,39 €"
    guess = {**full, "complete": False, "estimated": True, "total": 14.75, "estimated_total": 19.99}
    assert js_eval(page, BASKET, "planAmountText", guess) == "19,99 € estimé"
    part = {"complete": False, "estimated": False, "total": 9.88, "stores": [{"item_ids": [1, 2, 3]}]}
    assert js_eval(page, BASKET, "planAmountText", part) == "9,88 € pour 3 articles"
    # « introuvable » only when no retailer of the plan has it, else « manquant »
    comparison = {
        "stores": [
            {"store": "aldi", "lines": [{"item_id": 4, "status": "not_found"}, {"item_id": 5, "status": "excluded"}]},
            {"store": "lidl", "lines": [{"item_id": 4, "status": "not_found"}, {"item_id": 5, "status": "unchecked"}]},
        ]
    }
    plan = {"missing": 1, "missing_item_ids": [4], "stores": [{"store": "aldi"}, {"store": "lidl"}]}
    assert js_eval(page, BASKET, "planMissingText", plan, comparison) == "1 article introuvable"
    plan = {**plan, "missing": 2, "missing_item_ids": [4, 5]}
    assert js_eval(page, BASKET, "planMissingText", plan, comparison) == "2 articles manquants"
    now = (OCT_3 + 86400 * 2) * 1000
    assert js_eval(page, BASKET, "priceAge", OCT_3, now) == "prix d'il y a 2 jours"
    assert js_eval(page, BASKET, "priceAge", OCT_3, (OCT_3 + 86400) * 1000) == "prix d'hier"


def test_share_groupings_and_export_address(page):
    assert js_eval(page, SHARE, "groupings", None) == [{"value": "", "label": "Par rayon"}]
    comparison = {
        "outdated": False,
        "plans": [
            {"stores": [{"label": "Carrefour", "item_ids": [1, 2]}], "total": 19.39, "complete": True},
            {"stores": [{"label": "Aldi"}, {"label": "Lidl"}], "total": 14.67, "complete": True},
            # Incomplete: the title and the amount of the basket page
            {
                "stores": [{"label": "Aldi", "item_ids": [1]}],
                "total": 14.75,
                "estimated": True,
                "estimated_total": 19.99,
                "complete": False,
            },
        ],
        "stores": [
            {"store": "carrefour", "label": "Carrefour", "ranked": True},
            {"store": "intermarche", "label": "Intermarché", "ranked": False},
        ],
    }
    assert js_eval(page, SHARE, "groupings", comparison) == [
        {"value": "", "label": "Par rayon"},
        {"value": "plan:0", "label": "Tout chez Carrefour (19,39 €)"},
        {"value": "plan:1", "label": "Aldi + Lidl (14,67 €)"},
        {"value": "plan:2", "label": "Chez Aldi seulement (19,99 € estimé)"},
        {"value": "store:carrefour", "label": "Chez Carrefour"},
    ]
    assert js_eval(page, SHARE, "groupings", {**comparison, "outdated": True}) == [{"value": "", "label": "Par rayon"}]
    assert js_eval(page, SHARE, "exportQuery", "plan:1", "csv", True) == "format=csv&plan=1&download=true"
    assert js_eval(page, SHARE, "exportQuery", "store:aldi") == "format=txt&store=aldi"
    assert js_eval(page, SHARE, "exportQuery", "") == "format=txt"


def test_only_the_changed_fields_are_sent(page):
    item = {
        "query": "lessive",
        "quantity": 1,
        "target": None,
        "note": None,
        "category": "Entretien",
        "category_set": False,
        "compare": True,
    }
    same = {"query": "lessive ", "quantity": "1", "target": "", "note": "", "category": "", "compare": True}
    assert js_eval(page, EDIT, "changes", item, same) == {}
    changed = {
        "query": "Lessive liquide",
        "quantity": "150",
        "target": "2 L",
        "note": "sans parfum",
        "category": "Hygiène",
        "compare": False,
    }
    assert js_eval(page, EDIT, "changes", item, changed) == {
        "query": "Lessive liquide",
        "quantity": 99,
        "target": "2 L",
        "note": "sans parfum",
        "category": "Hygiène",
        "compare": False,
    }
    chosen = {**item, "category": "Hygiène", "category_set": True, "target": "2 L"}
    back = {**same, "category": "", "target": ""}
    assert js_eval(page, EDIT, "changes", chosen, back) == {"category": "", "target": ""}


def test_title_of_a_trip(page):
    def group(key, label):
        return {"store": key, "label": label, "aisles": []}

    other = group(None, "Autres articles")
    pair = {"plan": 1, "store": None, "unknown": False, "stores": [group("lidl", "Lidl"), group("aldi", "Aldi"), other]}
    assert js_eval(page, SHOPPING, "tripTitle", pair) == "Lidl + Aldi"
    single = {**pair, "plan": 0, "stores": [group("carrefour", "Carrefour"), other]}
    assert js_eval(page, SHOPPING, "tripTitle", single) == "Chez Carrefour"
    one = {"plan": None, "store": "aldi", "unknown": False, "stores": [group("aldi", "Aldi")]}
    assert js_eval(page, SHOPPING, "tripTitle", one) == "Chez Aldi"
    # A plan no longer in the last basket, or no plan at all: the whole list by aisle
    gone = {"plan": 3, "store": None, "unknown": True, "stores": [group(None, "Ma liste")]}
    assert js_eval(page, SHOPPING, "tripTitle", gone) == "Ma liste par rayon"
    whole = {"plan": None, "store": None, "unknown": False, "stores": [group(None, "Ma liste")]}
    assert js_eval(page, SHOPPING, "tripTitle", whole) == "Ma liste par rayon"
