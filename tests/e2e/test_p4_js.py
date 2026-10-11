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


def test_stores_proposed_by_the_assistant(desktop):
    page = desktop
    page.goto(page.base)
    onboarding = "/static/js/views/onboarding/index.js"
    url = "https://www.coursesu.com/drive-superu-{}".format
    nearest = [{"id": str(i), "name": f"Super U {i}", "url": url(i), "distance_km": i * 5.0} for i in range(1, 9)]
    # No store yet: the 3 nearest, the nearest checked
    proposed = js_eval(page, onboarding, "proposedStores", nearest, None)
    assert [s["id"] for s in proposed["stores"]] == ["1", "2", "3"] and proposed["choice"] == 0
    # The store chosen is among them: it is checked
    proposed = js_eval(page, onboarding, "proposedStores", nearest, {"url": url(2), "auto": False})
    assert proposed["choice"] == 1 and proposed["stores"][1]["current"]
    # Further than the 3 nearest: added first with what the list knows of it
    proposed = js_eval(page, onboarding, "proposedStores", nearest, {"url": url(6), "name": "U 6"})
    assert [s["id"] for s in proposed["stores"]] == ["6", "1", "2", "3"] and proposed["choice"] == 0
    assert proposed["stores"][0]["distance_km"] == 30.0 and proposed["stores"][0]["current"]
    # Not in the list at all (address pasted by hand)
    far = {"id": None, "name": "Super U Eysines", "url": url("eysines"), "distance_km": None}
    proposed = js_eval(page, onboarding, "proposedStores", nearest, far)
    assert proposed["stores"][0]["name"] == "Super U Eysines" and proposed["stores"][0]["id"] == ""
    # Intermarché: compared by store number
    shops = [{"id": "06814", "name": "Lattes"}, {"id": "08012", "name": "Montpellier"}]
    assert js_eval(page, onboarding, "proposedStores", shops, {"id": "08012"})["choice"] == 1
    assert js_eval(page, onboarding, "proposedStores", [], None) == {"stores": [], "choice": ""}
