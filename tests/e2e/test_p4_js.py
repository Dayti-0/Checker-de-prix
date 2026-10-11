"""Pure JS functions of P4 (status/shared.js, status/index.js, home cards), run in the page."""

from tests.e2e.helpers import js_eval

SHARED = "/static/js/views/status/shared.js"
STATUS = "/static/js/views/status/index.js"


def test_distance_texts(desktop):
    page = desktop
    page.goto(page.base)
    location = {"postal_code": "34320", "city": "Roujan"}
    same = {"postal_code": "34320", "city": "ROUJAN", "distance_km": 0.4}
    assert js_eval(page, SHARED, "distanceText", same, location) == "même commune"
    assert js_eval(page, SHARED, "distanceText", {"distance_km": 0.3}, location) == "≈ 1 km"
    assert js_eval(page, SHARED, "distanceText", {"distance_km": 15.4}, location) == "≈ 15 km"
    assert js_eval(page, SHARED, "distanceText", {"distance_km": None}, location) == ""
    assert js_eval(page, SHARED, "km", 2.44) == "2,4 km"


def test_status_texts(desktop):
    page = desktop
    page.goto(page.base)
    assert js_eval(page, STATUS, "duration", 850) == "850 ms"
    assert js_eval(page, STATUS, "duration", 2345) == "2,3 s"
    assert js_eval(page, STATUS, "percent", 0.8) == "80 %"
    ok = {"status": "ok", "elapsed_ms": 1200, "products": [{}, {}]}
    assert js_eval(page, STATUS, "testText", ok) == "2 produits trouvés en 1,2 s"
    one = {"status": "ok", "elapsed_ms": 300, "products": [{}]}
    assert js_eval(page, STATUS, "testText", one) == "1 produit trouvé en 300 ms"
    assert js_eval(page, STATUS, "testText", {"status": "empty", "elapsed_ms": 900, "products": []}) == (
        "Aucun produit (900 ms)"
    )
    blocked = {"status": "blocked", "message": "Vérification anti-robot", "products": []}
    assert js_eval(page, STATUS, "testText", blocked) == "Vérification anti-robot"


def test_home_card_texts(desktop):
    page = desktop
    page.goto(page.base)
    card = "/static/js/views/home/cards/status.js"
    fine = [{"label": "Aldi", "state": "ok", "consecutive_failures": 0}]
    assert js_eval(page, card, "alertText", fine) == ""
    blocked = [{"label": "Courses U", "state": "blocked", "consecutive_failures": 4}]
    assert (
        js_eval(page, card, "alertText", blocked)
        == "Courses U demande une vérification anti-robot depuis 4 recherches."
    )
    two = [
        {"label": "Aldi", "state": "broken", "consecutive_failures": 3},
        {"label": "Lidl", "state": "failing", "consecutive_failures": 3},
    ]
    assert (
        js_eval(page, card, "alertText", two) == "Aldi, Lidl ne donnent plus de résultats depuis plusieurs recherches."
    )

    setup = "/static/js/views/home/cards/setup.js"
    retailers = [
        {"key": "aldi", "label": "Aldi", "needs_store": False, "store": None},
        {"key": "intermarche", "label": "Intermarché", "needs_store": True, "store": None},
        {"key": "coursesu", "label": "Courses U", "needs_store": True, "store": {"name": "Super U Roujan"}},
    ]
    steps = js_eval(page, setup, "missingSteps", {"location": None, "stores": {}}, retailers)
    assert [s["key"] for s in steps] == ["location", "intermarche"]
    assert steps[1]["href"] == "#/reglages?enseigne=intermarche"
    assert js_eval(page, setup, "missingSteps", {"location": {"postal_code": "34320"}}, retailers[:1]) == []
