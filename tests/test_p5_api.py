"""API of the list and of the basket (P5): live basket (B59), « Changer » (B60), prices seen in
the store (B71), pasted lists (B67), usual items and templates (B68), export (B69), version (B70)."""

import asyncio
import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from backend import config, main
from backend.api import basket as basket_api
from backend.models import Product
from backend.scrapers.base import BlockedError, StoreRequiredError
from backend.services import matching, search
from tests.conftest import run

CATALOG = {
    "aldi": [
        ("Farine de blé T55", 0.79, "1 kg"),
        ("Sucre en poudre", 1.09, "1 kg"),
        ("Lait demi-écrémé", 0.95, "1 L"),
        ("Gâteau à la farine de riz", 0.50, "300 g"),
    ],
    "lidl": [
        ("Farine de blé T45", 0.75, "1 kg"),
        ("Sucre en poudre", 0.99, "1 kg"),
    ],
    "carrefour": [
        ("Farine de blé T45", 0.85, "1 kg"),
        ("Farine fluide Francine", 1.89, "1 kg"),
        ("Sucre en poudre", 1.15, "1 kg"),
        ("Lait demi-écrémé", 1.05, "1 L"),
        ("Beurre doux", 2.10, "250 g"),
    ],
    "intermarche": StoreRequiredError("Choisissez votre magasin Intermarché dans les réglages."),
    "coursesu": BlockedError("Courses U affiche une vérification anti-robot."),
}


def url(store, name):
    return f"https://{store}.example/{matching.query_key(name).replace(' ', '-')}"


def products_for(store, query):
    wanted = {matching.stem(w) for w in matching.keywords(query)}
    found = []
    for name, price, label in CATALOG[store]:
        if wanted & {matching.stem(t) for t in matching.tokenize(name)}:
            found.append(
                Product(store=store, name=name, price=price, quantity_label=label, product_url=url(store, name))
            )
    return found


class Sites:
    """Fake retailer sites: CATALOG, with every call recorded."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.catalog = dict(CATALOG)

    async def scrape(self, scraper, query, store):
        self.calls.append((scraper.key, query))
        value = self.catalog[scraper.key]
        if isinstance(value, Exception):
            raise value
        return products_for(scraper.key, query)

    def count(self, store):
        return sum(1 for key, _ in self.calls if key == store)


@pytest.fixture
def sites(monkeypatch):
    fake = Sites()
    monkeypatch.setattr(search, "_scrape", fake.scrape)
    search.reset_circuit()
    yield fake
    search.reset_circuit()


@pytest.fixture
def client(sites):
    with TestClient(main.app) as c:
        yield c


def add(client, query, **body):
    response = client.post("/api/list", json={"query": query, **body})
    assert response.status_code == 200, response.text
    return response.json()


def events_of(response) -> list[tuple[str, dict, str | None]]:
    """(event, data, id) of a Server-Sent Events answer."""
    events, name, data, event_id = [], None, None, None
    for line in response.iter_lines():
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: "):
            data = json.loads(line[6:])
        elif line.startswith("id: "):
            event_id = line[4:]
        elif line == "" and name:
            events.append((name, data, event_id))
            name, data, event_id = None, None, None
    return events


def stream(client, **params):
    with client.stream("GET", "/api/basket/compare/stream", params=params) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        return events_of(response)


def totals(comparison):
    return {b["store"]: (b["total"], b["estimated_total"], b["found_count"]) for b in comparison["stores"]}


# --- B57 / B59: comparison and live basket ----------------------------------------------


def test_post_and_stream_give_the_same_comparison(client, sites):
    add(client, "farine", quantity=2)
    add(client, "sucre")
    add(client, "lait")
    add(client, "beurre")
    stores = "aldi,lidl,carrefour,intermarche,coursesu"
    posted = client.post("/api/basket/compare", json={"stores": stores.split(",")}).json()
    # Carrefour has everything; Lidl (2 missing) and Aldi (1 missing) by estimated total
    assert posted["ranking"] == ["carrefour", "lidl", "aldi"]
    assert posted["best_store"] == "carrefour"
    baskets = {b["store"]: b for b in posted["stores"]}
    assert baskets["intermarche"]["status"] == "unchecked" and baskets["intermarche"]["action"] == "choose_store"
    assert baskets["coursesu"]["action"] == "unblock" and baskets["coursesu"]["unchecked_count"] == 4
    assert baskets["lidl"]["missing"] == 2 and baskets["lidl"]["estimated"]

    events = stream(client, stores=stores)
    names = [name for name, _, _ in events]
    assert names[0] == "start" and names[-1] == "done"
    start = events[0][1]
    assert [i["query"] for i in start["items"]] == ["farine", "sucre", "lait", "beurre"]
    assert [s["store"] for s in start["stores"]] == stores.split(",")
    assert start["total"] == 20
    lines = [data for name, data, _ in events if name == "line"]
    assert len(lines) == 20 and lines[-1]["done"] == 20 and lines[-1]["total"] == 20
    assert {(d["store"], d["item_id"]) for d in lines} == {
        (s, i["id"]) for s in stores.split(",") for i in start["items"]
    }
    finished = {data["store"]: data for name, data, _ in events if name == "store"}
    assert finished["aldi"]["status"] == "ok"
    assert finished["intermarche"]["status"] == "store_required"
    assert finished["coursesu"]["status"] == "blocked"
    done = events[-1][1]["comparison"]
    assert totals(done) == totals(posted)
    assert done["ranking"] == posted["ranking"] and done["plans"] == posted["plans"]
    assert events[-1][2].startswith("done-")


def test_blocked_retailer_is_called_once_for_ten_items(client, sites):
    for query in ("farine", "sucre", "lait", "beurre", "riz", "pâtes", "café", "thé", "sel", "poivre"):
        add(client, query)
    sites.catalog["lidl"] = RuntimeError("Le site ne répond pas")
    events = stream(client, stores="aldi,lidl,coursesu")
    done = events[-1][1]["comparison"]
    assert sites.count("coursesu") == 1
    assert sites.count("lidl") == 1
    assert sites.count("aldi") == 10
    baskets = {b["store"]: b for b in done["stores"]}
    assert baskets["coursesu"]["unchecked_count"] == 10 and baskets["coursesu"]["reason"] == "blocked"
    assert all(li["status"] == "unchecked" for li in baskets["lidl"]["lines"])
    assert baskets["lidl"]["action"] == "retry"


def test_short_circuit_serves_older_prices_without_calling_the_site(client, sites):
    add(client, "farine")
    add(client, "sucre")
    client.post("/api/basket/compare", json={"stores": ["lidl"]})
    # Seven hours later the site is blocked: the first item tries, the second one is read in the cache
    with sqlite3.connect(config.DB_PATH, timeout=5) as db:
        db.execute("UPDATE search_cache SET created_at = created_at - 7 * 3600")
    db.close()
    sites.catalog["lidl"] = BlockedError("Lidl affiche une vérification.")
    sites.calls.clear()
    comparison = client.post("/api/basket/compare", json={"stores": ["lidl"]}).json()
    assert sites.count("lidl") == 1
    lidl = comparison["stores"][0]
    assert [li["status"] for li in lidl["lines"]] == ["found", "found"]
    assert all(li["stale"] for li in lidl["lines"])
    assert (lidl["reason"], lidl["action"], lidl["stale_count"]) == ("blocked", "unblock", 2)
    assert "vérification requise" in lidl["lines"][1]["message"]


def test_cache_only_never_calls_the_sites(client, sites):
    add(client, "farine")
    add(client, "sucre")
    client.post("/api/basket/compare", json={"stores": ["aldi"]})
    add(client, "lait")
    sites.calls.clear()
    comparison = client.post("/api/basket/compare", json={"stores": ["aldi"], "cache_only": True}).json()
    assert sites.calls == []
    assert comparison["cache_only"]
    lines = comparison["stores"][0]["lines"]
    assert [li["status"] for li in lines] == ["found", "found", "unchecked"]
    assert lines[2]["message"] == "Prix pas encore lus chez Aldi."
    # A retailer never searched: its card says why and offers a real comparison
    alone = client.post("/api/basket/compare", json={"stores": ["lidl"], "cache_only": True}).json()["stores"][0]
    assert (alone["status"], alone["action"], alone["message"]) == ("unchecked", "retry", "Prix pas encore lus chez Lidl.")
    assert sites.calls == []


def test_finished_stream_is_not_started_again(client, sites):
    add(client, "farine")
    response = client.get("/api/basket/compare/stream", headers={"Last-Event-ID": "done-abc"})
    assert response.status_code == 204
    assert sites.calls == []


def test_first_event_before_any_retailer_answers(monkeypatch, sites):
    class Page:
        async def is_disconnected(self):
            return False

    async def slow(scraper, query, store):
        await asyncio.sleep(30)
        return []

    monkeypatch.setattr(search, "_scrape", slow)

    async def scenario():
        from backend.models import ListItemCreate
        from backend.services import shopping_list

        await shopping_list.add_item(ListItemCreate(query="farine"))
        events = basket_api.basket_events(Page(), ["aldi"], False, False)
        begin = time.monotonic()
        first = await asyncio.wait_for(anext(events), 3)
        elapsed = time.monotonic() - begin
        await events.aclose()
        return first, elapsed

    first, elapsed = run(scenario())
    assert first.startswith("id: ") and "event: start" in first
    assert elapsed < 3


def test_comparison_cancelled_when_the_page_leaves(monkeypatch, sites):
    cancelled = []

    class Page:
        def __init__(self):
            self.gone = False

        async def is_disconnected(self):
            return self.gone

    async def hanging(scraper, query, store):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.append(scraper.key)
            raise
        return []

    monkeypatch.setattr(search, "_scrape", hanging)
    monkeypatch.setattr(basket_api, "DISCONNECT_POLL_SECONDS", 0.05)

    async def scenario():
        from backend.models import ListItemCreate
        from backend.services import shopping_list

        await shopping_list.add_item(ListItemCreate(query="farine"))
        page = Page()
        events = basket_api.basket_events(page, ["aldi", "lidl"], False, False)
        received = [await anext(events)]
        await asyncio.sleep(0.2)  # the searches are running
        page.gone = True  # « Arrêter »: the EventSource is closed
        async for event in events:
            received.append(event)
        await asyncio.sleep(0.05)
        return received

    received = run(scenario())
    assert len(received) == 1 and "event: start" in received[0]
    assert sorted(cancelled) == ["aldi", "lidl"]


def test_last_basket(client, sites):
    assert client.get("/api/basket/last").status_code == 204
    add(client, "farine")
    compared = client.post("/api/basket/compare", json={"stores": ["aldi"]}).json()
    last = client.get("/api/basket/last").json()
    assert totals(last) == totals(compared)
    assert last["list_version"] == client.get("/api/list/version").json()["version"]
    add(client, "sucre")
    assert last["list_version"] < client.get("/api/list/version").json()["version"]


# --- B60: « Changer » ------------------------------------------------------------------


def test_change_the_product_then_exclude_then_back_to_auto(client, sites):
    flour = add(client, "farine")
    candidates = client.get(f"/api/basket/candidates/{flour['id']}/carrefour").json()
    assert [p["name"] for p in candidates["products"]] == ["Farine de blé T45", "Farine fluide Francine"]
    assert candidates["basis"] == "auto" and candidates["current_url"] == url("carrefour", "Farine de blé T45")
    assert candidates["auto_url"] == candidates["current_url"]

    francine = candidates["products"][1]
    sent = {**francine, "price": 0.01}  # the page never decides the price
    item = client.patch(f"/api/list/{flour['id']}", json={"set_pick": sent}).json()
    assert item["picks"]["carrefour"]["price"] == 1.89 and item["picks"]["carrefour"]["verified"]
    comparison = client.post("/api/basket/compare", json={"stores": ["carrefour", "aldi"]}).json()
    line = next(b for b in comparison["stores"] if b["store"] == "carrefour")["lines"][0]
    assert (line["basis"], line["picked"], line["line_total"]) == ("pick", True, 1.89)
    # Survives a reload
    assert client.get("/api/list").json()[0]["picks"]["carrefour"]["name"] == "Farine fluide Francine"
    candidates = client.get(f"/api/basket/candidates/{flour['id']}/carrefour").json()
    assert candidates["basis"] == "pick" and candidates["current_url"] == url("carrefour", "Farine fluide Francine")

    # « Pas disponible ici »
    item = client.patch(f"/api/list/{flour['id']}", json={"exclude_store": "carrefour"}).json()
    assert item["excluded"] == ["carrefour"] and "carrefour" not in item["picks"]
    comparison = client.post("/api/basket/compare", json={"stores": ["carrefour", "aldi"]}).json()
    carrefour = next(b for b in comparison["stores"] if b["store"] == "carrefour")
    assert carrefour["lines"][0]["status"] == "excluded"
    assert (carrefour["missing"], carrefour["excluded_count"]) == (0, 1)

    # « Revenir au choix automatique »
    item = client.patch(f"/api/list/{flour['id']}", json={"remove_pick": "carrefour"}).json()
    assert item["excluded"] == [] and item["picks"] == {}
    comparison = client.post("/api/basket/compare", json={"stores": ["carrefour"]}).json()
    assert comparison["stores"][0]["lines"][0]["basis"] == "auto"


def test_candidates_errors(client, sites):
    flour = add(client, "farine")
    assert client.get(f"/api/basket/candidates/{flour['id']}/inconnue").status_code == 404
    assert client.get("/api/basket/candidates/999/aldi").status_code == 404
    blocked = client.get(f"/api/basket/candidates/{flour['id']}/coursesu").json()
    assert blocked["status"] == "blocked" and blocked["products"] == []


def test_set_pick_of_an_unknown_retailer_is_refused(client, sites):
    flour = add(client, "farine")
    response = client.patch(f"/api/list/{flour['id']}", json={"set_pick": {"store": "x", "name": "F", "price": 1}})
    assert response.status_code == 422


# --- B71: price seen in the store ----------------------------------------------------------


def test_price_seen_in_the_store_then_expired(client, sites):
    milk = add(client, "lait", quantity=2)
    seen = time.time() - 3 * 86400
    body = {"manual_price": {"store": "intermarche", "name": "Lait Pâturages", "price": 1.02, "seen_at": seen}}
    item = client.patch(f"/api/list/{milk['id']}", json=body).json()
    pick = item["picks"]["intermarche"]
    assert (pick["source"], pick["price"], pick["picked_at"]) == ("manual", 1.02, pytest.approx(seen))
    sites.calls.clear()
    comparison = client.post("/api/basket/compare", json={"stores": ["intermarche"]}).json()
    assert sites.calls == []  # no search for a price typed by hand
    inter = comparison["stores"][0]
    line = inter["lines"][0]
    assert (line["status"], line["manual"], line["line_total"]) == ("found", True, 2.04)
    assert (inter["status"], inter["manual_count"], inter["complete"]) == ("ok", 1, True)
    # One week setting: expired, shown but not counted
    assert client.patch("/api/basket/prefs", json={"manual_weeks": 1}).json()["manual_weeks"] == 1
    client.patch(
        f"/api/list/{milk['id']}", json={"manual_price": {**body["manual_price"], "seen_at": seen - 7 * 86400}}
    )
    comparison = client.post("/api/basket/compare", json={"stores": ["intermarche"]}).json()
    line = comparison["stores"][0]["lines"][0]
    assert (line["status"], line["expired"], line["line_total"]) == ("unchecked", True, None)
    assert line["pick"]["price"] == 1.02


def test_manual_price_validation(client, sites):
    milk = add(client, "lait")
    for bad in ({"store": "aldi", "name": "", "price": 1}, {"store": "aldi", "name": "Lait", "price": 0}):
        assert client.patch(f"/api/list/{milk['id']}", json={"manual_price": bad}).status_code == 422


def test_basket_prefs(client, sites):
    assert client.get("/api/basket/prefs").json() == {"min_saving": 3.0, "manual_weeks": 6}
    assert client.patch("/api/basket/prefs", json={"min_saving": 1.5}).json() == {"min_saving": 1.5, "manual_weeks": 6}
    assert client.get("/api/basket/prefs").json()["min_saving"] == 1.5
    assert client.patch("/api/basket/prefs", json={"min_saving": -1}).status_code == 422
    add(client, "farine")
    assert client.post("/api/basket/compare", json={"stores": ["aldi"]}).json()["min_saving"] == 1.5


# --- B65 / B67 / B68 / B69 / B70: the list --------------------------------------------------


def test_version_follows_every_change(client, sites):
    versions = [client.get("/api/list/version").json()["version"]]
    item = add(client, "farine")
    versions.append(client.get("/api/list/version").json()["version"])
    client.patch(f"/api/list/{item['id']}", json={"quantity": 3})
    versions.append(client.get("/api/list/version").json()["version"])
    client.delete(f"/api/list/{item['id']}")
    versions.append(client.get("/api/list/version").json()["version"])
    assert versions == sorted(set(versions)) and len(versions) == 4


def test_paste_a_list(client, sites):
    add(client, "beurre")
    text = "2 lait demi-écrémé\nfarine 1kg\n- beurre\n• œufs x12\n3x yaourts"
    preview = client.post("/api/list/parse", json={"text": text}).json()
    assert [(p["query"], p["quantity"], p["target"], p["existing"]) for p in preview] == [
        ("lait demi-écrémé", 2, None, False),
        ("farine", 1, "1 kg", False),
        ("beurre", 1, None, True),
        ("œufs", 1, "12", False),
        ("yaourts", 3, None, False),
    ]
    assert preview[0]["category"] == "Crèmerie"
    assert client.get("/api/list").json()[0]["query"] == "beurre"  # nothing written by the preview
    items = client.post("/api/list/bulk", json={"items": preview}).json()
    assert [(i["query"], i["quantity"]) for i in items] == [
        ("beurre", 2),
        ("lait demi-écrémé", 2),
        ("farine", 1),
        ("œufs", 1),
        ("yaourts", 3),
    ]
    assert items[2]["target"] == "1 kg"


def test_fifteen_pasted_lines_give_fifteen_items(client, sites):
    names = "pommes poires bananes carottes poireaux riz pâtes sucre sel café thé miel confiture lessive éponges"
    text = "\n".join(names.split())
    preview = client.post("/api/list/parse", json={"text": text}).json()
    assert len(preview) == 15
    items = client.post("/api/list/bulk", json={"items": preview}).json()
    assert len(items) == 15
    assert next(i for i in items if i["query"] == "lessive")["category"] == "Entretien"


def test_aisles_notes_and_left_out_items(client, sites):
    assert "Entretien" in client.get("/api/list/categories").json()
    item = add(client, "lessive", note="la grande")
    assert (item["category"], item["category_set"], item["note"]) == ("Entretien", False, "la grande")
    item = client.patch(f"/api/list/{item['id']}", json={"category": "Hygiène et beauté", "compare": False}).json()
    assert (item["category"], item["category_set"], item["compare"]) == ("Hygiène et beauté", True, False)
    assert client.patch(f"/api/list/{item['id']}", json={"category": "Rayon inventé"}).status_code == 422
    item = client.patch(f"/api/list/{item['id']}", json={"category": "", "note": ""}).json()
    assert (item["category"], item["category_set"], item["note"]) == ("Entretien", False, None)
    add(client, "farine")
    comparison = client.post("/api/basket/compare", json={"stores": ["aldi"]}).json()
    assert comparison["skipped_item_ids"] == [item["id"]] and comparison["item_count"] == 1


def test_templates_round_trip(client, sites):
    flour = add(client, "farine", quantity=2, target="2 kg")
    candidates = client.get(f"/api/basket/candidates/{flour['id']}/lidl").json()
    client.patch(f"/api/list/{flour['id']}", json={"set_pick": candidates["products"][0], "exclude_store": "aldi"})
    add(client, "lait", note="demi-écrémé")
    before = client.get("/api/list").json()
    saved = client.post("/api/templates", json={"name": "Courses de la semaine"}).json()
    assert (saved["name"], saved["item_count"]) == ("Courses de la semaine", 2)
    assert client.get("/api/templates").json()[0]["id"] == saved["id"]
    assert client.get(f"/api/templates/{saved['id']}").json()["queries"] == ["farine", "lait"]

    client.delete("/api/list")
    assert client.get("/api/list").json() == []
    after = client.post(f"/api/templates/{saved['id']}/apply", json={"mode": "replace"}).json()

    def same(items):
        keep = ("query", "quantity", "picks", "target", "note", "excluded", "compare", "category")
        return [{k: i[k] for k in keep} for i in items]

    assert same(after) == same(before)
    # Merged into the list: quantities added
    merged = client.post(f"/api/templates/{saved['id']}/apply", json={"mode": "merge"}).json()
    assert [i["quantity"] for i in merged] == [4, 2]
    # Same name in another case: replaced
    again = client.post("/api/templates", json={"name": "courses de la semaine"}).json()
    assert again["id"] == saved["id"] and len(client.get("/api/templates").json()) == 1
    assert client.delete(f"/api/templates/{saved['id']}").status_code == 204
    assert client.delete(f"/api/templates/{saved['id']}").status_code == 404
    assert client.post(f"/api/templates/{saved['id']}/apply", json={}).status_code == 404
    assert client.get(f"/api/templates/{saved['id']}").status_code == 404


def test_template_errors(client, sites):
    assert client.post("/api/templates", json={"name": "Vide"}).status_code == 400
    add(client, "farine")
    assert client.post("/api/templates", json={"name": "   "}).status_code == 422
    assert client.post("/api/templates", json={"name": ""}).status_code == 422


def test_usual_items(client, sites):
    first = add(client, "Café moulu")
    client.delete(f"/api/list/{first['id']}")
    assert client.get("/api/list/usual").json() == []
    again = add(client, "café moulu")
    assert client.get("/api/list/usual").json() == []  # in the list: not proposed
    client.delete(f"/api/list/{again['id']}")
    assert client.get("/api/list/usual").json() == [{"query": "café moulu", "count": 2}]
    assert client.delete("/api/list/usual", params={"query": "Café moulu"}).status_code == 204
    assert client.get("/api/list/usual").json() == []


def test_export_text_and_csv(client, sites):
    add(client, "farine", quantity=2)
    add(client, "lessive", note="=HYPERLINK(1)")
    text = client.get("/api/list/export").text
    assert text.splitlines()[0] == "Ma liste de courses (2 articles)"
    assert "Épicerie sucrée :" in text and "- farine x2" in text
    client.post("/api/basket/compare", json={"stores": ["aldi", "lidl"]})
    by_store = client.get("/api/list/export", params={"store": "lidl"}).text
    assert "LIDL" in by_store and "- farine x2 : Farine de blé T45, 1,50 €" in by_store
    assert "Total Lidl : 1,50 €" in by_store
    response = client.get("/api/list/export", params={"format": "csv", "plan": 0, "download": True})
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == 'attachment; filename="ma-liste.csv"'
    csv_text = response.content.decode("utf-8")
    assert csv_text.startswith("﻿Enseigne;Rayon;Article")
    assert "'=HYPERLINK(1)" in csv_text  # never a formula in a spreadsheet
    assert client.get("/api/list/export", params={"store": "inconnue"}).status_code == 404
    assert client.get("/api/list/export", params={"format": "pdf"}).status_code == 422


def test_restore_ticks_and_finish(client, sites):
    flour = add(client, "farine", quantity=2, target="2 kg")
    client.patch(f"/api/list/{flour['id']}", json={"exclude_store": "aldi"})
    deleted = next(i for i in client.get("/api/list").json() if i["id"] == flour["id"])
    client.delete(f"/api/list/{flour['id']}")
    assert client.get("/api/list").json() == []
    restored = client.post("/api/list/restore", json={"id": flour["id"]}).json()
    assert restored == [deleted]  # exactly as it was: same id, target, « pas disponible ici », date
    sugar = add(client, "sucre")
    now = time.time()
    checks = [
        {"id": flour["id"], "checked": True, "checked_at": now - 60},
        {"id": sugar["id"], "checked": True, "checked_at": now - 30},
        {"id": sugar["id"], "checked": False, "checked_at": now - 90},  # older: ignored
        {"id": 999, "checked": True},
    ]
    items = client.post("/api/list/checks", json={"checks": checks}).json()
    assert [i["checked"] for i in items] == [True, True]
    items = client.post("/api/list/finish", json={"mode": "uncheck"}).json()
    assert [i["checked"] for i in items] == [False, False]
    client.post("/api/list/checks", json={"checks": [{"id": sugar["id"], "checked": True}]})
    items = client.post("/api/list/finish", json={"mode": "remove"}).json()
    assert [i["query"] for i in items] == ["farine"]


def test_undo_puts_back_what_the_server_kept(client, sites):
    """« Annuler » sends ids only: a price or a product described by the page is never taken."""
    sugar = add(client, "sucre")
    picked = client.patch(
        f"/api/list/{sugar['id']}",
        json={"set_pick": {"store": "lidl", "name": "Sucre en poudre", "price": 0.99, "product_url": url("lidl", "x")}},
    ).json()
    assert picked["picks"]["lidl"]["verified"] is False  # never read by PrixMalin
    client.delete(f"/api/list/{sugar['id']}")
    forged = {**picked, "quantity": 9, "picks": {"lidl": {**picked["picks"]["lidl"], "price": 0.01, "verified": True}}}
    items = client.post("/api/list/restore", json=forged).json()
    assert items == [picked]
    # Only once: the line has left the server's trash
    again = client.post("/api/list/restore", json={"id": sugar["id"]})
    assert (again.status_code, again.json()["code"]) == (404, "restore_expired")
    assert again.json()["detail"] == "Cet article ne peut plus être rétabli."
    assert client.post("/api/list/restore", json={}).status_code == 422


def test_undo_after_emptying_the_list(client, sites):
    items = [add(client, q) for q in ("sucre", "farine", "beurre")]
    before = client.get("/api/list").json()
    assert client.delete("/api/list").status_code == 204
    add(client, "farine", quantity=3)  # added again meanwhile: one line, its settings come back
    restored = client.post("/api/list/restore", json={"ids": [i["id"] for i in items]}).json()
    assert [i["query"] for i in restored] == ["sucre", "beurre", "farine"]
    by_query = {i["query"]: i for i in restored}
    assert by_query["sucre"] == next(i for i in before if i["query"] == "sucre")
    assert by_query["farine"]["quantity"] == 1
    gone = client.post("/api/list/restore", json={"ids": [items[0]["id"], 12345]})
    assert gone.json()["detail"] == "Ces articles ne peuvent plus être rétablis."


def test_undo_window(client, sites, monkeypatch):
    from backend.services import shopping_list

    sugar = add(client, "sucre")
    later = time.time() + shopping_list.TRASH_SECONDS + 1
    client.delete(f"/api/list/{sugar['id']}")
    monkeypatch.setattr(shopping_list.time, "time", lambda: later)
    assert client.post("/api/list/restore", json={"id": sugar["id"]}).status_code == 404
    # The lines deleted long ago are forgotten at the next deletion
    flour = add(client, "farine")
    client.delete(f"/api/list/{flour['id']}")
    with sqlite3.connect(config.DB_PATH) as db:
        assert [r[0] for r in db.execute("SELECT id FROM list_trash")] == [flour["id"]]
    db.close()
