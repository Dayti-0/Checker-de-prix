"""B51: Courses U store nearest to the postal code (directory, ranking, choice, revisit).

The directory fixtures are SYNTHETIC (tests/fixtures/coursesu.py): they follow
the markup described by the research, not a capture of the real site.
"""

import asyncio
import json
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import config, main
from backend.browser import BrowserManager, BrowserUnavailable
from backend.models import Location, StoreOption, StoreSelection
from backend.repos import stores_cache
from backend.scrapers import SCRAPERS, common
from backend.scrapers import coursesu as cu
from backend.scrapers.base import BlockedError, StoreRequiredError
from backend.services import settings as settings_service
from backend.services import stores
from tests import fixtures
from tests.conftest import browser_missing, run

ROUJAN = Location(
    postal_code="34320", city="Roujan", lat=43.50, lon=3.32, department_code="34", department_name="Hérault"
)


def directory_stores() -> list[StoreOption]:
    return cu.parse_store_directory(fixtures.COURSESU_DIRECTORY_HTML)


# ---------------------------------------------------------------- parsing of the directory


def test_parse_store_directory():
    parsed = directory_stores()
    assert [(s.id, s.name, s.postal_code, s.city, s.url) for s in parsed] == [
        ("11111", "Super U Roujan", "34320", "Roujan", "https://www.coursesu.com/drive-superu-roujan"),
        ("22222", "Super U Pézenas", "34120", "Pézenas", "https://www.coursesu.com/drive-superu-pezenas"),
        (
            "33333",
            "U Express Montpellier Pres d'Arenes",
            "34070",
            "Montpellier",
            "https://www.coursesu.com/drive-uexpress-montpellierpresdarenes",
        ),
        ("95524", "Super U Eysines", "33320", "Eysines", "https://www.coursesu.com/drive-superu-eysines"),
    ]
    roujan = parsed[0]
    # <br> become « , » (the whole address is kept), entities are decoded
    assert roujan.address == "Avenue de Pézenas, Zone commerciale Cap Caroux, 34320 Roujan"
    assert roujan.services == ["Drive", "Livraison"]
    assert parsed[1].services == ["Drive", "Retrait"]
    assert all(cu.is_store_url(s.url) for s in parsed)
    assert all(s.lat is None and s.distance_km is None for s in parsed)


def test_parse_store_directory_reads_coordinates_and_ignores_garbage():
    html = (
        '<div data-wrapper-store-details data-store-id="5" data-lat="43.5" data-lng="3.3">'
        '<a href="https://www.coursesu.com/drive-hyperu-vallet">x</a></div>'
    )
    (store,) = cu.parse_store_directory(html)
    assert (store.lat, store.lon, store.name, store.id) == (43.5, 3.3, "Hyper U Vallet", "5")
    assert cu.parse_store_directory("") == []
    assert cu.parse_store_directory("<p>rien</p>") == []


@pytest.mark.parametrize(
    "entry, name",
    [
        # Name in the attribute of the entry, other elements inside it (indented markup)
        (
            '<div data-wrapper-store-details data-store-id="1" data-store-name="Super U Foo">\n'
            '  <div><span>Nom</span></div>\n  <a href="/drive-superu-foo">x</a></div>',
            "Super U Foo",
        ),
        # Element without value whose text is in a child element, after a line break
        (
            '<div data-wrapper-store-details data-store-id="2">\n  <h3 data-store-name>\n'
            '    <span>Super U Bar</span>\n  </h3>\n  <a href="/drive-superu-bar">x</a></div>',
            "Super U Bar",
        ),
        # Name cut by a tag
        (
            "<div data-wrapper-store-details><h3 data-store-name>Super U <b>Saint-Jean</b> &amp; Co</h3>"
            '<a href="/drive-superu-saintjean">x</a></div>',
            "Super U Saint-Jean & Co",
        ),
        # Attribute only, the element holds nothing but white space
        (
            "<div data-wrapper-store-details data-store-id=\"7\" data-store-name='U Express Lyon'>\n   "
            '<a href="/drive-uexpress-lyon">x</a></div>',
            "U Express Lyon",
        ),
        # Empty everywhere: the name comes from the link, never an empty name
        (
            '<div data-wrapper-store-details data-store-name="  "><h3 data-store-name> </h3>'
            '<a href="/drive-superu-vide">x</a></div>',
            "Super U Vide",
        ),
        # The entry carries the attribute without value: its text is not a name
        (
            "<div data-wrapper-store-details data-store-name><p>Drive</p><p>1 rue X, 34000 Montpellier</p>"
            '<a href="/drive-hyperu-mtp">Choisir</a></div>',
            "Hyper U Mtp",
        ),
    ],
)
def test_parse_store_directory_names(entry, name):
    (store,) = cu.parse_store_directory(entry)
    assert store.name == name


def test_parse_store_directory_addresses_with_child_elements():
    html = (
        '<div data-wrapper-store-details data-store-id="5"><h3 data-store-name>Super U Qux</h3>'
        '<div class="stores-text-address"><div>2 av X</div><div>34120 P&eacute;zenas</div></div>'
        '<a href="/drive-superu-qux">x</a></div>'
        '<div data-wrapper-store-details data-store-id="6"><h3 data-store-name>Super U Baz</h3>'
        '<p class="stores-text-address"><span>Route de B&eacute;ziers</span> <span>34120 P&eacute;zenas</span></p>'
        '<a href="/drive-superu-baz">x</a></div>'
    )
    qux, baz = cu.parse_store_directory(html)
    assert (qux.address, qux.postal_code, qux.city) == ("2 av X, 34120 Pézenas", "34120", "Pézenas")
    assert (baz.address, baz.postal_code, baz.city) == ("Route de Béziers 34120 Pézenas", "34120", "Pézenas")


def test_parse_store_directory_links_with_query_strings():
    html = (
        '<div data-wrapper-store-details data-store-id="6"><a href="/drive-superu-x?foo=1">x</a></div>'
        '<div data-wrapper-store-details data-store-id="7">'
        "<a href='https://www.coursesu.com/drive-SuperU-Upper/#horaires'>y</a></div>"
    )
    assert [(s.id, s.url) for s in cu.parse_store_directory(html)] == [
        ("6", "https://www.coursesu.com/drive-superu-x"),
        ("7", "https://www.coursesu.com/drive-superu-upper"),
    ]
    cards = [{"href": "/drive-superu-roujan?origin=annuaire", "text": "Avenue de Pézenas\n34320 Roujan", "id": "1"}]
    assert [s.url for s in cu.cards_to_stores(cards)] == ["https://www.coursesu.com/drive-superu-roujan"]
    selection = cu.site_store_selection({"link": "https://www.coursesu.com/drive-superu-eysines?x=1#y"})
    assert selection.url == "https://www.coursesu.com/drive-superu-eysines"


def test_cards_to_stores():
    cards = [
        {
            "href": "/drive-superu-roujan",
            "text": "Super U Roujan\nAvenue de Pézenas\n34320 Roujan\nDrive",
            "id": "11111",
        },
        {"href": "https://www.coursesu.com/drive-superu-roujan/", "text": "doublon", "id": "11111"},
        {"href": "/drive-uexpress-montpellier", "text": "U Express\n12 av. de Palavas, 34070 Montpellier", "id": None},
        {"href": "/drive-herault", "text": "Hérault 34000", "id": None},
        {"href": "/f-superu-roujan-informations", "text": "34320 Roujan", "id": None},
        "pas une carte",
    ]
    parsed = cu.cards_to_stores(cards)
    assert [(s.id, s.name, s.address, s.postal_code, s.city) for s in parsed] == [
        ("11111", "Super U Roujan", "Avenue de Pézenas, 34320 Roujan", "34320", "Roujan"),
        ("", "U Express Montpellier", "12 av. de Palavas, 34070 Montpellier", "34070", "Montpellier"),
    ]
    assert parsed[0].services == ["Drive"]


@pytest.mark.parametrize(
    "href, expected",
    [
        ("/drive-superu-roujan", "https://www.coursesu.com/drive-superu-roujan"),
        ("https://www.coursesu.com/drive-UEXPRESS-Lyon3bonnel/", "https://www.coursesu.com/drive-uexpress-lyon3bonnel"),
        ("/drive-marcheu-x", "https://www.coursesu.com/drive-marcheu-x"),
        ("/drive-superu-roujan?origin=annuaire", "https://www.coursesu.com/drive-superu-roujan"),
        ("https://www.coursesu.com/drive-superu-roujan/#horaires", "https://www.coursesu.com/drive-superu-roujan"),
        ("/drive-herault?page=2", None),
        ("/drive-herault", None),
        ("/drive-dept-paris", None),
        ("/drive-pieton-paris", None),
        ("/f-superu-roujan-informations", None),
        ("https://example.com/drive-superu-roujan", None),
        ("", None),
    ],
)
def test_store_url_from_href(href, expected):
    assert cu.store_url_from_href(href) == expected


def test_store_names_and_department_pages():
    assert cu.store_name_from_url("https://www.coursesu.com/drive-marketu-sete") == "Market U Sete"
    assert cu.store_name_from_url("https://www.coursesu.com/drive-uexpress-noves") == "U Express Noves"
    assert cu.department_slug("Hérault") == "herault"
    assert cu.department_slug("Côtes-d'Armor") == "cotes-darmor"
    assert cu.department_slug("Saône-et-Loire") == "saone-et-loire"
    assert cu.department_slug("Paris") == "dept-paris"


def test_challenge_detection():
    assert cu.is_challenge_response(403, "")
    assert cu.is_challenge_response(429, "")
    assert cu.is_challenge_response(200, fixtures.COURSESU_CHALLENGE_HTML)
    assert cu.is_challenge_response(200, '<iframe src="https://geo.captcha-delivery.com/x">')
    # Cloudflare scripts on a normal page: the directory is there
    assert not cu.is_challenge_response(200, fixtures.COURSESU_DIRECTORY_HTML)
    assert not cu.is_challenge_response(200, "<html>ok</html>")


def test_directory_keeps_the_message_of_other_blocks(monkeypatch):
    """A block that is not a check to pass (P3's hard block) keeps its own message."""

    class HardBlock(BlockedError):
        pass

    async def blocked(page, url, label):
        raise HardBlock("Courses U bloque temporairement cette connexion.")

    async def check(page, url, label):
        raise BlockedError("vérification")

    scraper = cu.CoursesUScraper()
    monkeypatch.setattr(cu, "ensure_origin", blocked)
    with pytest.raises(HardBlock):
        asyncio.run(scraper.fetch_store_directory(object()))
    monkeypatch.setattr(cu, "ensure_origin", check)
    with pytest.raises(BlockedError) as e:
        asyncio.run(scraper.fetch_store_directory(object()))
    assert str(e.value) == cu.DIRECTORY_BLOCKED


def test_site_store_selection():
    info = {"link": "https://www.coursesu.com/drive-superu-eysines", "id": "95524", "name": "EYSINES"}
    assert cu.site_store_selection(info) == StoreSelection(
        id="95524", name="Super U Eysines", url="https://www.coursesu.com/drive-superu-eysines"
    )
    assert cu.site_store_selection({"link": "https://www.coursesu.com/drive-superu-eysines", "id": "x"}).id is None
    assert cu.site_store_selection({"link": "https://www.coursesu.com/drive/home", "id": None}) is None
    assert cu.site_store_selection({"link": None}) is None
    assert cu.site_store_selection(None) is None
    assert cu.site_store_selection("pas un objet") is None
    # Without window.storeLink: the id (page or cookie) is looked up in the directory
    by_id = cu.site_store_selection({"link": None, "id": "22222"}, directory_stores())
    assert by_id == StoreSelection(
        id="22222",
        name="Super U Pézenas",
        url="https://www.coursesu.com/drive-superu-pezenas",
        address="Route de Béziers, 34120 Pézenas",
    )
    assert cu.site_store_selection({"id": "22222"}) is None  # no directory yet
    assert cu.site_store_selection({"id": "99999"}, directory_stores()) is None


def test_needs_store_visit():
    url = "https://www.coursesu.com/drive-superu-roujan"
    visit = cu.StoreVisit(url, generation=2, at=1000.0)
    assert cu.needs_store_visit(None, url, 2, 1000)
    assert not cu.needs_store_visit(visit, url, 2, 1000 + 60)
    assert cu.needs_store_visit(visit, url, 3, 1000 + 60)  # new browser context
    assert cu.needs_store_visit(visit, url, 2, 1000 + cu.REVISIT_SECONDS + 1)  # 20 min later
    assert cu.needs_store_visit(visit, "https://www.coursesu.com/drive-superu-pezenas", 2, 1000)


# ---------------------------------------------------------------- ranking


def index():
    return stores.build_commune_index(fixtures.COMMUNES_JSON)


def test_commune_index_and_locate():
    idx = index()
    assert [name for name, _, _ in idx["34320"]] == ["gabian", "roujan"]
    assert idx["34070"] == [["montpellier", 43.6109, 3.8767]]
    assert "99998" not in idx  # town without centre
    # A shared postal code resolves to the town of the address
    assert stores.locate("34320", "Roujan", idx) == (43.505, 3.3108)
    assert stores.locate("34320", "Gabian", idx) == (43.5106, 3.2742)
    assert stores.locate("34320", "Ailleurs", idx) == (43.5106, 3.2742)  # first town listed
    assert stores.locate("34320", None, idx) == (43.5106, 3.2742)
    assert stores.locate("00000", "Roujan", idx) is None
    assert stores.locate("34320", "Roujan", None) is None
    assert stores.build_commune_index("pas une liste") == {}


def test_normalize_town():
    assert stores.normalize_town("Saint-Jean-de-Védas") == "saint jean de vedas"
    assert stores.normalize_town("St Jean de Vedas") == "saint jean de vedas"
    assert stores.normalize_town("Ste-Foy-lès-Lyon") == "sainte foy les lyon"
    assert stores.normalize_town("Montpellier Cedex 2") == "montpellier"
    assert stores.normalize_town(None) == ""


def test_rank_stores_by_distance():
    ranked = stores.rank_stores(directory_stores(), ROUJAN, index())
    assert [s.city for s in ranked] == ["Roujan", "Pézenas", "Montpellier", "Eysines"]
    distances = [s.distance_km for s in ranked]
    assert distances[0] < 2
    assert 5 <= distances[1] <= 15
    assert 35 <= distances[2] <= 60
    assert distances[3] > 300
    assert stores.haversine_km(43.5, 3.32, 43.5, 3.32) == 0


def test_rank_stores_without_town_table():
    near_pezenas = Location(postal_code="34120", city="Pézenas")
    ranked = stores.rank_stores(directory_stores(), near_pezenas, None)
    # Same postal code, then the same department, then the others
    assert [s.city for s in ranked] == ["Pézenas", "Roujan", "Montpellier", "Eysines"]
    assert all(s.distance_km is None for s in ranked)
    assert stores.department_of("97410") == "974"
    assert stores.department_of("34320") == "34"


def test_rank_stores_uses_coordinates_of_the_directory():
    far = StoreOption(id="1", name="Loin", postal_code="34320", city="Roujan", lat=48.85, lon=2.35)
    near = StoreOption(id="2", name="Près", postal_code="75001", city="Paris")
    ranked = stores.rank_stores([far, near], ROUJAN, {"75001": [["paris", 43.51, 3.33]]})
    assert [s.name for s in ranked] == ["Près", "Loin"]


# ---------------------------------------------------------------- caches and services


def mock_transport(handler):
    return httpx.MockTransport(handler)


def test_commune_index_is_downloaded_once(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json=fixtures.COMMUNES_JSON)

    monkeypatch.setattr(settings_service, "HTTP_TRANSPORT", mock_transport(handler))

    async def scenario():
        first = await stores.commune_index()
        second = await stores.commune_index()
        return first, second

    first, second = run(scenario())
    assert first == second == json.loads(json.dumps(index()))
    assert len(calls) == 1
    assert "fields=nom%2CcodesPostaux%2Ccentre" in calls[0]


def test_commune_index_failure_uses_the_old_table(monkeypatch):
    def failing(request):
        raise httpx.ConnectError("hors ligne")

    monkeypatch.setattr(settings_service, "HTTP_TRANSPORT", mock_transport(failing))

    async def scenario():
        nothing = await stores.commune_index()
        await stores_cache.put(stores.COMMUNES_KEY, json.dumps({"34320": [["roujan", 43.5, 3.3]]}), now=1)
        old = await stores.commune_index()
        return nothing, old

    nothing, old = run(scenario())
    assert nothing is None
    assert old == {"34320": [["roujan", 43.5, 3.3]]}


def fake_directory(monkeypatch, result, calls=None):
    async def fetch(department_name):
        if calls is not None:
            calls.append(department_name)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(stores, "fetch_coursesu_directory", fetch)


def many_stores(n=60):
    base = directory_stores()
    extra = [
        StoreOption(id=str(1000 + i), name=f"Super U {i}", url=f"https://www.coursesu.com/drive-superu-x{i}")
        for i in range(n - len(base))
    ]
    return base + extra


def test_directory_cache(monkeypatch):
    calls = []
    fake_directory(monkeypatch, {"stores": many_stores(), "method": "blocs"}, calls)

    async def scenario():
        a = await stores.coursesu_directory("Hérault")
        b = await stores.coursesu_directory("Hérault")
        c = await stores.coursesu_directory("Hérault", refresh=True)
        return a, b, c

    a, b, c = run(scenario())
    assert len(a) == len(b) == len(c) == 60
    assert calls == ["Hérault", "Hérault"]  # the second call came from the cache


def test_small_or_department_directories_are_not_cached(monkeypatch):
    calls = []
    fake_directory(monkeypatch, {"stores": directory_stores(), "method": "blocs"}, calls)

    async def scenario():
        await stores.coursesu_directory()
        await stores.coursesu_directory()

    run(scenario())
    assert len(calls) == 2


def test_nearest_stores(monkeypatch):
    fake_directory(monkeypatch, {"stores": directory_stores(), "method": "blocs"})

    async def table(refresh=False):
        return index()

    monkeypatch.setattr(stores, "commune_index", table)
    nearest = run(stores.nearest_coursesu_stores(ROUJAN, limit=2))
    assert [s.name for s in nearest] == ["Super U Roujan", "Super U Pézenas"]
    with pytest.raises(stores.AppError) as e:
        run(stores.nearest_coursesu_stores(None))
    assert e.value.status_code == 400


def test_nearest_stores_without_town_table_geocodes_the_department(monkeypatch):
    fake_directory(monkeypatch, {"stores": directory_stores(), "method": "blocs"})
    looked_up = []

    async def no_table(refresh=False):
        return None

    async def geocode(postal_code):
        looked_up.append(postal_code)
        towns = {"34320": [("Roujan", 43.505, 3.31)], "34120": [("Pézenas", 43.459, 3.42)], "34070": []}
        return [Location(postal_code=postal_code, city=c, lat=a, lon=o) for c, a, o in towns[postal_code]]

    monkeypatch.setattr(stores, "commune_index", no_table)
    monkeypatch.setattr(settings_service, "geocode", geocode)
    nearest = run(stores.nearest_coursesu_stores(ROUJAN))
    # Only the postal codes of the department (34) are looked up; Eysines (33) has no distance
    assert sorted(looked_up) == ["34070", "34120", "34320"]
    assert [s.city for s in nearest] == ["Roujan", "Pézenas", "Montpellier", "Eysines"]
    assert nearest[0].distance_km is not None and nearest[-1].distance_km is None

    # Known postal codes are not looked up again
    looked_up.clear()
    run(stores.nearest_coursesu_stores(ROUJAN))
    assert looked_up == ["34070"]


def test_postal_index_stops_without_geo_service(monkeypatch):
    async def down(postal_code):
        raise settings_service.GeocodingUnavailable("hors ligne")

    monkeypatch.setattr(settings_service, "geocode", down)
    assert run(stores.postal_index(directory_stores(), ROUJAN)) == {}


# ---------------------------------------------------------------- automatic choice


@pytest.fixture
def located(monkeypatch):
    """The location of the user is Roujan; the directory and the town table are fixtures."""
    fake_directory(monkeypatch, {"stores": directory_stores(), "method": "blocs"})

    async def table(refresh=False):
        return index()

    monkeypatch.setattr(stores, "commune_index", table)

    async def set_location():
        await settings_service.modify(lambda s: setattr(s, "location", ROUJAN))

    run(set_location())


def test_auto_pick_without_location():
    result = run(stores.auto_pick_coursesu())
    assert result.status == "no_location"
    assert result.settings.stores == {}


def test_auto_pick_chooses_the_nearest(located):
    result = run(stores.auto_pick_coursesu())
    assert result.status == "chosen"
    assert result.message is None
    saved = result.settings.stores["coursesu"]
    assert (saved.name, saved.url, saved.id, saved.auto) == (
        "Super U Roujan",
        "https://www.coursesu.com/drive-superu-roujan",
        "11111",
        True,
    )
    assert saved.distance_km < 2
    assert saved.address.endswith("34320 Roujan")


def test_auto_pick_keeps_the_store_chosen_by_the_user(located):
    manual = StoreSelection(url="https://www.coursesu.com/drive-superu-eysines", name="Super U Eysines")
    run(settings_service.set_store("coursesu", manual))
    result = run(stores.auto_pick_coursesu())
    assert result.status == "kept"
    assert result.settings.stores["coursesu"] == manual


def test_auto_pick_replaces_an_automatic_choice(located):
    old = StoreSelection(url="https://www.coursesu.com/drive-superu-eysines", name="Super U Eysines", auto=True)
    run(settings_service.set_store("coursesu", old))
    result = run(stores.auto_pick_coursesu())
    assert result.status == "chosen"
    assert result.settings.stores["coursesu"].name == "Super U Roujan"


def test_auto_pick_reports_a_far_store(monkeypatch, located):
    fake_directory(monkeypatch, {"stores": directory_stores()[3:], "method": "blocs"})
    result = run(stores.auto_pick_coursesu())
    assert result.status == "chosen"
    assert result.message == "Aucun drive Courses U à moins de 40 km."


@pytest.mark.parametrize(
    "error, status, message",
    [
        (BlockedError(cu.DIRECTORY_BLOCKED), "blocked", cu.DIRECTORY_BLOCKED),
        (TimeoutError(), "timeout", "Courses U n'a pas répondu à temps. Réessayez dans un instant."),
        (RuntimeError("Target closed"), "error", stores.AUTO_FAILED),
        (BrowserUnavailable("Aucun navigateur utilisable."), "error", stores.AUTO_FAILED),
    ],
)
def test_auto_pick_failures_are_reported(monkeypatch, located, error, status, message):
    fake_directory(monkeypatch, error)
    result = run(stores.auto_pick_coursesu())
    assert (result.status, result.message) == (status, message)
    assert "coursesu" not in result.settings.stores


def test_auto_pick_without_store(monkeypatch, located):
    fake_directory(monkeypatch, {"stores": [], "method": "département"})
    assert run(stores.auto_pick_coursesu()).status == "none"


def fake_site_store(monkeypatch, info):
    """The pages of the Courses U site show the store ``info`` (``{link, id, name}``)."""

    async def browser_run(key, fn, *args, timeout=None, priority="interactive"):
        assert (key, fn.__name__) == ("coursesu", "read_site_store")
        if isinstance(info, Exception):
            raise info
        return info

    monkeypatch.setattr(stores.browser, "run", browser_run)


def save_directory():
    run(stores_cache.put(stores.DIRECTORY_KEY, json.dumps([s.model_dump() for s in directory_stores()])))


def test_read_back_saves_the_store_chosen_on_the_site(monkeypatch):
    save_directory()
    fake_site_store(monkeypatch, {"link": "https://www.coursesu.com/drive-superu-pezenas", "id": None})
    result = run(stores.read_back_coursesu())
    assert result.status == "chosen"
    saved = result.settings.stores["coursesu"]
    # Name and address of the directory
    assert (saved.name, saved.address, saved.id, saved.auto) == (
        "Super U Pézenas",
        "Route de Béziers, 34120 Pézenas",
        "22222",
        False,
    )
    # Same store again: nothing changes
    assert run(stores.read_back_coursesu()).status == "kept"


def test_read_back_uses_the_last_small_directory(monkeypatch):
    """A directory too small to be cached for 7 days still names the store read back."""
    fake_directory(monkeypatch, {"stores": directory_stores(), "method": "liens"})
    run(stores.coursesu_directory())
    fake_site_store(monkeypatch, {"link": "https://www.coursesu.com/drive-superu-pezenas"})
    result = run(stores.read_back_coursesu())
    assert result.settings.stores["coursesu"].name == "Super U Pézenas"


def test_read_back_by_store_id(monkeypatch):
    """No window.storeLink on the page: the id of the storeId cookie is enough."""
    save_directory()
    fake_site_store(monkeypatch, {"link": None, "id": "95524", "name": None})
    result = run(stores.read_back_coursesu())
    assert result.status == "chosen"
    assert result.settings.stores["coursesu"].url == "https://www.coursesu.com/drive-superu-eysines"


def test_read_back_without_store_or_with_errors(monkeypatch):
    fake_site_store(monkeypatch, {"link": None, "id": None, "name": None})
    assert run(stores.read_back_coursesu()).status == "none"
    fake_site_store(monkeypatch, None)
    assert run(stores.read_back_coursesu()).status == "none"
    fake_site_store(monkeypatch, {"link": "https://www.coursesu.com/drive-superu-roujan", "id": "11111"})
    result = run(stores.read_back_coursesu())
    assert result.status == "chosen" and result.store.name == "Super U Roujan"
    fake_site_store(monkeypatch, BlockedError("bloqué"))
    assert run(stores.read_back_coursesu()).status == "blocked"
    fake_site_store(monkeypatch, TimeoutError())
    assert run(stores.read_back_coursesu()).status == "timeout"
    fake_site_store(monkeypatch, RuntimeError("Target closed"))
    assert run(stores.read_back_coursesu()).status == "error"


def test_initial_auto_pick_runs_once_per_postal_code(monkeypatch, located):
    calls = []
    fake_directory(monkeypatch, {"stores": directory_stores(), "method": "blocs"}, calls)
    assert run(stores.auto_pick_coursesu(initial=True)).status == "chosen"
    assert len(calls) == 1
    # A page loaded again: the automatic store stays, the site is not read again
    assert run(stores.auto_pick_coursesu(initial=True)).status == "kept"
    assert len(calls) == 1
    # The store removed by the user is not chosen again when a page loads...
    run(stores.forget_coursesu_store())
    run(settings_service.remove_store("coursesu"))
    result = run(stores.auto_pick_coursesu(initial=True))
    assert result.status == "kept" and "coursesu" not in result.settings.stores
    assert len(calls) == 1
    # ...but a new postal code (not initial) chooses again
    assert run(stores.auto_pick_coursesu()).status == "chosen"
    assert len(calls) == 2


def test_initial_auto_pick_retries_after_a_failure(monkeypatch, located):
    fake_directory(monkeypatch, BlockedError(cu.DIRECTORY_BLOCKED))
    assert run(stores.auto_pick_coursesu(initial=True)).status == "blocked"
    fake_directory(monkeypatch, {"stores": directory_stores(), "method": "blocs"})
    assert run(stores.auto_pick_coursesu(initial=True)).status == "chosen"


def test_read_back_only_after_the_site_was_opened(monkeypatch):
    save_directory()
    fake_site_store(monkeypatch, {"link": "https://www.coursesu.com/drive-superu-pezenas"})
    scraper = SCRAPERS["coursesu"]
    monkeypatch.setattr(scraper, "site_opened_at", None)
    # Another site was opened: Courses U is not read
    assert run(stores.read_back_coursesu(opened_only=True)).status == "none"
    # « Ouvrir le site » on Courses U asks for its page (POST /api/browser/setup)
    assert scraper.setup_url(None) == cu.BASE_URL + "/"
    assert scraper.site_opened_at is not None
    assert run(stores.read_back_coursesu(opened_only=True)).status == "chosen"
    assert scraper.site_opened_at is None
    assert run(stores.read_back_coursesu(opened_only=True)).status == "none"


# ---------------------------------------------------------------- API


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def test_api_coursesu_stores_needs_a_location(client):
    response = client.get("/api/retailers/coursesu/stores")
    assert response.status_code == 400
    assert response.json()["detail"] == "Indiquez d'abord votre code postal."


def test_api_coursesu_stores_sorted(client, located):
    response = client.get("/api/retailers/coursesu/stores")
    assert response.status_code == 200
    body = response.json()
    assert [s["name"] for s in body] == [
        "Super U Roujan",
        "Super U Pézenas",
        "U Express Montpellier Pres d'Arenes",
        "Super U Eysines",
    ]
    assert body[0]["url"] == "https://www.coursesu.com/drive-superu-roujan"
    assert body[0]["services"] == ["Drive", "Livraison"]


@pytest.mark.parametrize(
    "error, status, detail",
    [
        (BlockedError(cu.DIRECTORY_BLOCKED), 502, cu.DIRECTORY_BLOCKED),
        (TimeoutError(), 504, "Courses U n'a pas répondu à temps."),
        (RuntimeError("Target closed\nplus"), 502, "Recherche des magasins impossible : Target closed"),
    ],
)
def test_api_coursesu_stores_errors(client, located, monkeypatch, error, status, detail):
    fake_directory(monkeypatch, error)
    response = client.get("/api/retailers/coursesu/stores")
    assert (response.status_code, response.json()["detail"]) == (status, detail)


def test_api_choose_a_listed_store(client, located):
    option = client.get("/api/retailers/coursesu/stores").json()[1]
    body = {k: option[k] for k in ("id", "name", "address", "url", "distance_km")}
    saved = client.put("/api/retailers/coursesu/store", json=body).json()["stores"]["coursesu"]
    assert saved == {
        "id": "22222",
        "name": "Super U Pézenas",
        "url": "https://www.coursesu.com/drive-superu-pezenas",
        "address": "Route de Béziers, 34120 Pézenas",
        "auto": False,
        "distance_km": option["distance_km"],
    }
    retailers = {r["key"]: r for r in client.get("/api/retailers").json()}
    assert retailers["coursesu"]["store"]["name"] == "Super U Pézenas"
    assert retailers["coursesu"]["finds_stores"] and retailers["intermarche"]["finds_stores"]
    assert retailers["aldi"]["national"] and retailers["lidl"]["national"]
    assert not retailers["carrefour"]["national"]


def test_api_pasted_address_with_query_string(client):
    url = "https://www.coursesu.com/drive-SuperU-Roujan/?utm_source=partage#horaires"
    saved = client.put("/api/retailers/coursesu/store", json={"url": url}).json()["stores"]["coursesu"]
    assert (saved["url"], saved["name"]) == ("https://www.coursesu.com/drive-superu-roujan", "Super U Roujan")
    # Other pages of the site stay refused
    response = client.put("/api/retailers/coursesu/store", json={"url": "https://www.coursesu.com/recherche?q=farine"})
    assert response.status_code == 400


def test_api_auto_and_from_site(client, located, monkeypatch):
    result = client.post("/api/retailers/coursesu/store/auto").json()
    assert result["status"] == "chosen"
    assert result["store"]["name"] == "Super U Roujan"
    assert result["settings"]["stores"]["coursesu"]["auto"] is True

    fake_site_store(monkeypatch, {"link": "https://www.coursesu.com/drive-superu-eysines", "id": "95524"})
    result = client.post("/api/retailers/coursesu/store/from-site").json()
    assert result["status"] == "chosen"
    assert result["settings"]["stores"]["coursesu"]["name"] == "Super U Eysines"
    # The user chose this one: the automatic choice keeps it
    assert client.post("/api/retailers/coursesu/store/auto").json()["status"] == "kept"


def test_api_remove_coursesu_store_stops_the_initial_auto_pick(client, located):
    assert client.post("/api/retailers/coursesu/store/auto?initial=true").json()["status"] == "chosen"
    assert client.delete("/api/retailers/coursesu/store").status_code == 200
    result = client.post("/api/retailers/coursesu/store/auto?initial=true").json()
    assert result["status"] == "kept"
    assert "coursesu" not in result["settings"]["stores"]
    assert client.post("/api/retailers/coursesu/store/from-site?opened_only=true").json()["status"] == "none"


def test_api_auto_never_fails(client):
    result = client.post("/api/retailers/coursesu/store/auto")
    assert result.status_code == 200
    assert result.json()["status"] == "no_location"


# ---------------------------------------------------------------- in Chromium (sites simulated)


@pytest.fixture(scope="module")
def manager(tmp_path_factory):
    m = BrowserManager(tmp_path_factory.mktemp("profile-p4"))

    async def probe(page):
        return True

    try:
        asyncio.run(m.run("probe", probe, timeout=60))
    except BrowserUnavailable as e:
        browser_missing(f"Chromium indisponible : {e}")
    yield m
    asyncio.run(m.shutdown())


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(config, "MIN_REQUEST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(common, "CHALLENGE_WAIT_SECONDS", 1)
    scraper = SCRAPERS["coursesu"]
    monkeypatch.setattr(scraper, "_visit", None)
    return scraper


def html(body, status=200):
    return lambda route: route.fulfill(status=status, content_type="text/html; charset=utf-8", body=body)


async def offline(page):
    await page.route("**/*", lambda route: route.abort())


async def home(page):
    await offline(page)
    await page.route("https://www.coursesu.com/", html(fixtures.HOME_PAGE))


def test_browser_directory_puts_roujan_first(manager, fast):
    async def scenario(page):
        await home(page)
        await page.route("https://www.coursesu.com/drive-france", html(fixtures.COURSESU_DIRECTORY_HTML))
        return await fast.fetch_store_directory(page, "Hérault")

    result = asyncio.run(manager.run("coursesu-dir", scenario, timeout=60))
    assert result["method"] == "blocs"
    ranked = stores.rank_stores(result["stores"], ROUJAN, index())
    assert ranked[0].name == "Super U Roujan"
    # Fewer than 50 stores: the page is kept to fix the reader
    assert (config.DEBUG_DIR / "coursesu-stores.html").read_text(encoding="utf-8") == fixtures.COURSESU_DIRECTORY_HTML


def test_browser_directory_link_based_reader(manager, fast):
    async def scenario(page):
        await home(page)
        await page.route("https://www.coursesu.com/drive-france", html(fixtures.COURSESU_DIRECTORY_ALT_HTML))
        return await fast.fetch_store_directory(page)

    result = asyncio.run(manager.run("coursesu-alt", scenario, timeout=60))
    assert result["method"] == "liens"
    assert [(s.id, s.name, s.address) for s in result["stores"]] == [
        ("11111", "Super U Roujan", "Avenue de Pézenas, 34320 Roujan"),
        ("22222", "Super U Pezenas", "Route de Béziers, 34120 Pézenas"),
        ("", "U Express Montpellierpresdarenes", "12 avenue de Palavas, 34070 Montpellier"),
        ("95524", "Super U Eysines", "Avenue du Médoc, 33320 Eysines"),
    ]
    assert result["stores"][0].services == ["Drive", "Livraison"]


def test_browser_directory_department_page(manager, fast):
    async def scenario(page):
        await home(page)
        await page.route("https://www.coursesu.com/drive-france", html("<html><body>Bientôt</body></html>"))
        await page.route("https://www.coursesu.com/drive-herault", html(fixtures.COURSESU_DIRECTORY_HTML))
        return await fast.fetch_store_directory(page, "Hérault")

    (config.DEBUG_DIR / cu.DEPARTMENT_SNAPSHOT).unlink(missing_ok=True)
    result = asyncio.run(manager.run("coursesu-dept", scenario, timeout=60))
    assert result["method"] == "département"
    assert len(result["stores"]) == 4
    # The snapshot to send is the page of /drive-france that gave nothing, not the
    # department page that worked
    assert "Bientôt" in (config.DEBUG_DIR / cu.DIRECTORY_SNAPSHOT).read_text(encoding="utf-8")
    assert not (config.DEBUG_DIR / cu.DEPARTMENT_SNAPSHOT).exists()


def test_browser_directory_department_page_without_stores_is_kept_apart(manager, fast):
    async def scenario(page):
        await home(page)
        await page.route("https://www.coursesu.com/drive-france", html("<html><body>Bientôt</body></html>"))
        await page.route("https://www.coursesu.com/drive-herault", html("<html><body>Département vide</body></html>"))
        return await fast.fetch_store_directory(page, "Hérault")

    (config.DEBUG_DIR / cu.DEPARTMENT_SNAPSHOT).unlink(missing_ok=True)
    result = asyncio.run(manager.run("coursesu-dept-empty", scenario, timeout=60))
    assert result == {"stores": [], "method": "département"}
    assert "Bientôt" in (config.DEBUG_DIR / cu.DIRECTORY_SNAPSHOT).read_text(encoding="utf-8")
    assert "Département vide" in (config.DEBUG_DIR / cu.DEPARTMENT_SNAPSHOT).read_text(encoding="utf-8")


def test_browser_directory_link_based_reader_with_query_strings(manager, fast):
    page_html = fixtures.COURSESU_DIRECTORY_ALT_HTML.replace(
        'href="https://www.coursesu.com/drive-superu-roujan"',
        'href="https://www.coursesu.com/drive-superu-roujan?origin=annuaire"',
    )
    assert page_html != fixtures.COURSESU_DIRECTORY_ALT_HTML

    async def scenario(page):
        await home(page)
        await page.route("https://www.coursesu.com/drive-france", html(page_html))
        return await fast.fetch_store_directory(page)

    result = asyncio.run(manager.run("coursesu-alt-query", scenario, timeout=60))
    assert result["method"] == "liens"
    assert result["stores"][0].url == "https://www.coursesu.com/drive-superu-roujan"
    assert len(result["stores"]) == 4


def test_browser_directory_challenge_then_page(manager, fast):
    """fetch() meets a check: the page itself is loaded and the check passes."""
    served = []

    async def scenario(page):
        await home(page)

        async def directory(route):
            served.append(route.request.resource_type)
            if len(served) == 1:
                await route.fulfill(status=403, content_type="text/html", body=fixtures.COURSESU_CHALLENGE_HTML)
            else:
                await route.fulfill(status=200, content_type="text/html", body=fixtures.COURSESU_DIRECTORY_HTML)

        await page.route("https://www.coursesu.com/drive-france", directory)
        return await fast.fetch_store_directory(page)

    result = asyncio.run(manager.run("coursesu-challenge-ok", scenario, timeout=60))
    assert served == ["fetch", "document"]
    assert len(result["stores"]) == 4


def test_browser_directory_blocked(manager, fast):
    async def scenario(page):
        await home(page)
        await page.route("https://www.coursesu.com/drive-france", html(fixtures.COURSESU_CHALLENGE_HTML, status=403))
        return await fast.fetch_store_directory(page)

    with pytest.raises(BlockedError) as e:
        asyncio.run(manager.run("coursesu-blocked", scenario, timeout=60))
    assert str(e.value) == cu.DIRECTORY_BLOCKED


def test_browser_read_site_store(manager, fast):
    page_with_store = (
        "<html><head><title>Courses U</title><script>"
        "window.storeLink = 'https://www.coursesu.com/drive-superu-eysines';"
        "window.dataLayerNC = {store_id: '95524', store_name: 'EYSINES'};"
        "</script></head><body>Accueil</body></html>"
    )

    async def scenario(page):
        await offline(page)
        await page.route("https://www.coursesu.com/", html(page_with_store))
        return await fast.read_site_store(page)

    info = asyncio.run(manager.run("coursesu-site", scenario, timeout=60))
    assert info == {"link": "https://www.coursesu.com/drive-superu-eysines", "id": "95524", "name": "EYSINES"}
    assert cu.site_store_selection(info) == StoreSelection(
        id="95524", name="Super U Eysines", url="https://www.coursesu.com/drive-superu-eysines"
    )

    async def no_store(page):
        await home(page)
        return await fast.read_site_store(page)

    nothing = asyncio.run(manager.run("coursesu-site-none", no_store, timeout=60))
    assert nothing == {"link": None, "id": None, "name": None}
    assert cu.site_store_selection(nothing) is None


STORE = StoreSelection(url="https://www.coursesu.com/drive-superu-roujan", name="Super U Roujan", id="11111")

NO_PRICE_PAGE = """<html><body><div class="product-tile" data-pid="1">
<div class="pdp-link"><a href="/p/farine/1.html">Farine de blé T45 U, 1kg</a></div></div></body></html>"""


def test_browser_store_page_revisited_when_the_context_changes(manager, fast, monkeypatch):
    visits = []

    async def scenario(page):
        await offline(page)

        async def store_page(route):
            visits.append(route.request.url)
            await route.fulfill(status=200, content_type="text/html", body=fixtures.HOME_PAGE)

        await page.route("https://www.coursesu.com/drive-superu-roujan", store_page)
        await page.route(re.compile(r"https://www\.coursesu\.com/recherche.*"), html(fixtures.COURSESU_PAGE))
        first = await fast.search(page, "farine", STORE)
        await fast.search(page, "farine", STORE)  # same context: no new visit
        monkeypatch.setattr(cu.browser, "context_generation", cu.browser.context_generation + 1)
        await fast.search(page, "farine", STORE)
        return first

    products = asyncio.run(manager.run("coursesu-revisit", scenario, timeout=90))
    assert products[0].price == 0.95
    assert len(visits) == 2


def test_browser_store_page_visited_again_when_prices_are_missing(manager, fast):
    served = []

    async def scenario(page):
        await offline(page)
        await page.route("https://www.coursesu.com/drive-superu-roujan", html(fixtures.HOME_PAGE))

        async def results(route):
            served.append(route.request.url)
            body = NO_PRICE_PAGE if len(served) == 1 else fixtures.COURSESU_PAGE
            await route.fulfill(status=200, content_type="text/html", body=body)

        await page.route(re.compile(r"https://www\.coursesu\.com/recherche.*"), results)
        return await fast.search(page, "farine", STORE)

    products = asyncio.run(manager.run("coursesu-noprice", scenario, timeout=90))
    assert len(served) == 2
    assert products[0].price == 0.95


def test_browser_store_gone(manager, fast):
    async def scenario(page):
        await offline(page)
        await page.route("https://www.coursesu.com/drive-superu-roujan", html("<html>Page introuvable</html>", 404))
        return await fast.search(page, "farine", STORE)

    with pytest.raises(StoreRequiredError) as e:
        asyncio.run(manager.run("coursesu-gone", scenario, timeout=60))
    assert str(e.value) == cu.STORE_GONE
