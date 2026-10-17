from backend.models import ListItemCreate, ListItemUpdate, Product, StoreSelection
from backend.scrapers.base import BlockedError, StoreRequiredError
from backend.services import basket, search, settings
from tests.conftest import run


def product(store, name, price, **kw):
    return Product(store=store, name=name, price=price, product_url=f"https://{store}.example/{name}", **kw)


def fake_scrape(catalog, calls=None):
    async def scrape(scraper, query, store):
        if calls is not None:
            calls.append((scraper.key, query))
        value = catalog.get(scraper.key, [])
        if isinstance(value, Exception):
            raise value
        return [p.model_copy() for p in value]

    return scrape


def test_search_sorts_relevant_first_then_by_price(monkeypatch):
    catalog = {
        "aldi": [
            product("aldi", "Gâteau à l'huile", 0.5),
            product("aldi", "Huile de tournesol 1L", 1.99),
            product("aldi", "Huile tournesol 3L", 4.99),
            product("aldi", "Huile de tournesol 1L", 1.99),
        ]
    }
    monkeypatch.setattr(search, "_scrape", fake_scrape(catalog))
    result = run(search.search_store("aldi", "huile de tournesol"))
    assert result.status == "ok"
    assert [p.name for p in result.products] == ["Huile de tournesol 1L", "Huile tournesol 3L", "Gâteau à l'huile"]
    assert result.products[1].unit_price == 1.66
    assert result.products[2].relevance == 0.5


def test_search_uses_cache_until_refresh(monkeypatch):
    calls = []
    monkeypatch.setattr(search, "_scrape", fake_scrape({"lidl": [product("lidl", "Farine", 0.75)]}, calls))

    async def scenario():
        first = await search.search_store("lidl", "Farine")
        second = await search.search_store("lidl", "farine ")
        third = await search.search_store("lidl", "farine", refresh=True)
        return first, second, third

    first, second, third = run(scenario())
    assert not first.cached and second.cached and not third.cached
    assert len(calls) == 2


def test_search_error_statuses(monkeypatch):
    catalog = {
        "carrefour": BlockedError("Carrefour affiche une vérification"),
        "intermarche": StoreRequiredError("Choisissez votre magasin"),
        "aldi": [],
        "lidl": RuntimeError("Page.goto: net::ERR_NAME_NOT_RESOLVED at https://www.lidl.fr/"),
        "coursesu": [product("coursesu", "Farine U", None)],
    }
    monkeypatch.setattr(search, "_scrape", fake_scrape(catalog))
    response = run(search.search_all("farine"))
    statuses = {r.store: r.status for r in response.results}
    assert statuses == {
        "aldi": "empty",
        "lidl": "error",
        "carrefour": "blocked",
        "intermarche": "store_required",
        "coursesu": "store_required",  # products without price and no store chosen
    }
    lidl = next(r for r in response.results if r.store == "lidl")
    assert "injoignable" in lidl.message


def test_search_timeout(monkeypatch):
    async def slow(scraper, query, store):
        raise TimeoutError

    monkeypatch.setattr(search, "_scrape", slow)
    assert run(search.search_store("aldi", "farine")).status == "timeout"


def test_cache_depends_on_selected_store(monkeypatch):
    calls = []
    monkeypatch.setattr(search, "_scrape", fake_scrape({"intermarche": [product("intermarche", "Farine", 1.0)]}, calls))

    async def scenario():
        await settings.set_store("intermarche", StoreSelection(id="1", name="A"))
        await search.search_store("intermarche", "farine")
        await settings.set_store("intermarche", StoreSelection(id="2", name="B"))
        return await search.search_store("intermarche", "farine")

    result = run(scenario())
    assert len(calls) == 2
    assert result.store_label == "B"


def test_list_merges_same_query():
    async def scenario():
        await basket.add_item(ListItemCreate(query="Farine", quantity=1))
        await basket.add_item(ListItemCreate(query="farine ", quantity=2))
        await basket.add_item(ListItemCreate(query="Farine", product=product("aldi", "Farine T55", 0.79)))
        items = await basket.get_list()
        updated = await basket.update_item(items[0].id, ListItemUpdate(quantity=5, remove_pick="aldi"))
        return items, updated

    items, updated = run(scenario())
    assert len(items) == 1
    assert items[0].quantity == 3
    assert items[0].picks["aldi"].name == "Farine T55"
    assert updated.quantity == 5 and updated.picks == {}


def test_basket_comparison(monkeypatch):
    catalog = {
        "aldi": [product("aldi", "Farine T55 1kg", 0.79), product("aldi", "Huile de tournesol 1L", 1.99)],
        "lidl": [product("lidl", "Farine de blé 1kg", 0.75)],
        "carrefour": [
            product("carrefour", "Farine T45 Carrefour", 0.85),
            product("carrefour", "Farine Francine", 1.89),
            product("carrefour", "Huile de tournesol Lesieur 1L", 2.49),
        ],
    }
    monkeypatch.setattr(search, "_scrape", fake_scrape(catalog))

    async def scenario():
        await basket.add_item(ListItemCreate(query="farine", quantity=2))
        await basket.add_item(ListItemCreate(query="huile de tournesol"))
        # The user prefers Francine at Carrefour
        await basket.add_item(ListItemCreate(query="farine", product=catalog["carrefour"][1]))
        return await basket.compare_basket(["aldi", "lidl", "carrefour"])

    comparison = run(scenario())
    by_store = {b.store: b for b in comparison.stores}
    assert by_store["aldi"].total == 3.57 and by_store["aldi"].missing == 0
    assert by_store["lidl"].total == 1.5 and by_store["lidl"].missing == 1
    assert by_store["carrefour"].total == 6.27
    assert by_store["carrefour"].lines[0].picked
    assert comparison.best_store == "aldi"
    assert comparison.split_total == 1.5 + 1.99
    assert comparison.split_missing == 0
