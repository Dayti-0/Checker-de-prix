import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.models import Location, Product, StoreOption
from backend.services import search, settings


@pytest.fixture
def client(monkeypatch):
    async def scrape(scraper, query, store):
        return [Product(store=scraper.key, name=f"{query} {scraper.label}", price=1.0, product_url="https://x/p")]

    monkeypatch.setattr(search, "_scrape", scrape)
    with TestClient(main.app) as c:
        yield c


def test_index_and_static(client):
    assert "PrixMalin" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200


def test_search_endpoints(client):
    one = client.get("/api/search/aldi", params={"q": "farine"}).json()
    assert one["status"] == "ok" and one["products"][0]["name"] == "farine Aldi"
    many = client.get("/api/search", params={"q": "farine", "stores": "aldi,lidl,inconnu"}).json()
    assert [r["store"] for r in many["results"]] == ["aldi", "lidl"]
    assert client.get("/api/search/inconnu", params={"q": "x"}).status_code == 404
    assert client.get("/api/search/aldi").status_code == 422


def test_retailers_and_store_selection(client):
    retailers = client.get("/api/retailers").json()
    assert [r["key"] for r in retailers] == ["aldi", "lidl", "carrefour", "intermarche", "coursesu"]

    bad = client.put("/api/retailers/coursesu/store", json={"url": "https://example.com"})
    assert bad.status_code == 400
    ok = client.put("/api/retailers/coursesu/store", json={"url": "https://www.coursesu.com/drive-superu-roujan/"})
    assert ok.json()["stores"]["coursesu"] == {
        "id": None, "name": "Super U Roujan", "url": "https://www.coursesu.com/drive-superu-roujan", "address": None,
    }
    assert client.put("/api/retailers/aldi/store", json={"id": "1"}).status_code == 400
    assert client.put("/api/retailers/intermarche/store", json={"id": "06814", "name": "Lattes"}).status_code == 200
    stores = client.delete("/api/retailers/coursesu/store").json()["stores"]
    assert list(stores) == ["intermarche"]


def test_location(client, monkeypatch):
    async def geocode(postal_code):
        return [Location(postal_code=postal_code, city="Montpellier", lat=43.61, lon=3.87)]

    monkeypatch.setattr(settings, "geocode", geocode)
    assert client.post("/api/settings/location", json={"postal_code": "3400"}).status_code == 422
    res = client.post("/api/settings/location", json={"postal_code": "34000"}).json()
    assert res["settings"]["location"]["city"] == "Montpellier"


def test_intermarche_stores_need_location(client, monkeypatch):
    assert client.get("/api/retailers/intermarche/stores").status_code == 400

    async def geocode(postal_code):
        return [Location(postal_code=postal_code, city="Lattes", lat=43.57, lon=3.9)]

    async def run(key, fn, *args, timeout=None):
        return [StoreOption(id="06814", name="Intermarché Hyper Lattes", distance_km=0.9)]

    monkeypatch.setattr(settings, "geocode", geocode)
    monkeypatch.setattr(main.browser, "run", run)
    client.post("/api/settings/location", json={"postal_code": "34970"})
    assert client.get("/api/retailers/intermarche/stores").json()[0]["id"] == "06814"


def test_shopping_list_and_basket(client):
    item = client.post("/api/list", json={"query": "farine", "quantity": 2}).json()
    assert item["quantity"] == 2
    client.post("/api/list", json={"query": "sucre"})
    assert len(client.get("/api/list").json()) == 2
    assert client.patch(f"/api/list/{item['id']}", json={"quantity": 3}).json()["quantity"] == 3
    assert client.patch("/api/list/999", json={"quantity": 3}).status_code == 404

    comparison = client.post("/api/basket/compare", json={"stores": ["aldi", "lidl"]}).json()
    assert {s["store"]: s["total"] for s in comparison["stores"]} == {"aldi": 4.0, "lidl": 4.0}
    assert comparison["split_total"] == 4.0

    assert client.delete(f"/api/list/{item['id']}").status_code == 204
    assert client.delete("/api/list").status_code == 204
    assert client.get("/api/list").json() == []


def test_browser_status(client):
    status = client.get("/api/browser").json()
    assert status["setup_mode"] is False
