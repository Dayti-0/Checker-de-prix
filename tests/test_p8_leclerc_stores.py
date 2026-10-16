"""E.Leclerc Drive: addresses of the drives, store finder, automatic choice, read-back, API (P8).

The answers of the store finder are SYNTHETIC (tests/fixtures/leclerc.py).
"""

import json

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.browser import BrowserUnavailable
from backend.models import Location, StoreOption, StoreSelection
from backend.repos import stores_cache
from backend.scrapers import SCRAPERS
from backend.scrapers import leclerc as lc
from backend.scrapers.base import BlockedError, HardBlockError
from backend.services import prefs, stores
from backend.services import settings as settings_service
from tests import fixtures
from tests.conftest import run

MONTPELLIER = Location(**fixtures.LECLERC_ORIGIN, department_code="34", department_name="Hérault")


# ---------------------------------------------------------------- addresses of the drives


@pytest.mark.parametrize(
    "url, base, no_pl, no_pr",
    [
        (
            "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges.aspx",
            "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges",
            "173301",
            "173301",
        ),
        (
            "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges/recherche.aspx?TexteRecherche=riz",
            "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges",
            "173301",
            "173301",
        ),
        (
            "https://FD12-Courses.LeclercDrive.fr/magasin-173301-173301-Bruges/fiche-produits-214087-Soda.aspx#x",
            "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges",
            "173301",
            "173301",
        ),
        (
            "  https://fd2-courses.leclercdrive.fr/magasin-027411-001261-ville-la-grand-annemasse-  ",
            "https://fd2-courses.leclercdrive.fr/magasin-027411-001261-ville-la-grand-annemasse-",
            "027411",
            "001261",
        ),
        (
            "https://fd9-courses.leclercdrive.fr/magasin-053701-053701-La-Ville-aux-Dames/",
            "https://fd9-courses.leclercdrive.fr/magasin-053701-053701-La-Ville-aux-Dames",
            "053701",
            "053701",
        ),
        (
            "https://fd10-courses.leclercdrive.fr/magasin-085111-Reims-Jean-Jaures/recherche.aspx?TexteRecherche=",
            "https://fd10-courses.leclercdrive.fr/magasin-085111-Reims-Jean-Jaures",
            "085111",
            None,
        ),
        (
            "https://fd9-courses.leclercdrive.fr/magasin-010901-saint-jean-du-falga.aspx?utm_source=x",
            "https://fd9-courses.leclercdrive.fr/magasin-010901-saint-jean-du-falga",
            "010901",
            None,
        ),
        (
            "https://fd3-courses.leclercdrive.fr/magasin-093401-093401",
            "https://fd3-courses.leclercdrive.fr/magasin-093401-093401",
            "093401",
            "093401",
        ),
    ],
)
def test_parse_store_url_accepts_the_pages_of_a_drive(url, base, no_pl, no_pr):
    ref = lc.parse_store_url(url)
    assert ref is not None
    assert (ref.base, ref.no_pl, ref.no_pr) == (base, no_pl, no_pr)


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "http://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges.aspx",
        "javascript:alert(1)",
        "https://fd12-courses.leclercdrive.fr.example.com/magasin-173301-173301-Bruges.aspx",
        "https://evil.leclercdrive.fr/magasin-173301-173301-Bruges.aspx",
        "https://fd12-courses-traiteur.leclercdrive.fr/magasin-173301-173301-Bruges.aspx",
        "https://m-courses.leclercdrive.fr/magasin-974601/recherche/farine",
        "https://www.leclercdrive.fr/region-occitanie-pyrenees-mediterranee/montpellier/drive-montpellier.aspx",
        "https://fd12-courses.leclercdrive.fr/magasin-17330-Bruges.aspx",
        "https://fd12-courses.leclercdrive.fr/magasin-1733011-Bruges.aspx",
        "https://fd12-courses.leclercdrive.fr/",
        "https://fd12-courses.leclercdrive.fr:8443/magasin-173301-173301-Bruges.aspx",
        "https://user@fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges.aspx",
        "https://fd123-courses.leclercdrive.fr/magasin-173301-173301-Bruges.aspx",
        "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges<script>.aspx",
        "https://fd12-courses.leclercdrive.fr/magasin-173301-" + "x" * 300,
    ],
)
def test_parse_store_url_refuses_the_rest(url):
    assert lc.parse_store_url(url) is None


def test_store_name_of():
    ref = lc.parse_store_url
    assert lc.store_name_of(ref("https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges")) == (
        "E.Leclerc Drive Bruges"
    )
    assert lc.store_name_of(
        ref("https://fd2-courses.leclercdrive.fr/magasin-027411-001261-ville-la-grand-annemasse-")
    ) == ("E.Leclerc Drive Ville La Grand Annemasse")
    assert (
        lc.store_name_of(ref("https://fd3-courses.leclercdrive.fr/magasin-093401-093401"))
        == "E.Leclerc Drive n° 093401"
    )
    assert lc.store_name_of(ref("https://fd3-courses.leclercdrive.fr/magasin-093401-093401"), "Le Crès") == (
        "E.Leclerc Drive Le Crès"
    )
    assert lc.store_name_of(ref("https://fd3-courses.leclercdrive.fr/magasin-093401"), "E.Leclerc Drive X") == (
        "E.Leclerc Drive X"
    )


@pytest.mark.parametrize(
    "point, expected",
    [
        (
            {
                "noPL": "053701",
                "noPR": "053701",
                "name": "La Ville-aux-Dames",
                "urlSiteCourse": "https://fd9-courses.leclercdrive.fr/",
            },
            "https://fd9-courses.leclercdrive.fr/magasin-053701-053701-La-Ville-aux-Dames",
        ),
        (
            {"noPL": "053701", "name": "La Ville-aux-Dames", "urlBase": "fd9-courses.leclercdrive.fr"},
            "https://fd9-courses.leclercdrive.fr/magasin-053701-053701-La-Ville-aux-Dames",
        ),
        (
            {
                "noPL": "173301",
                "name": "Bruges",
                "urlSiteCourse": "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges.aspx",
            },
            "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges",
        ),
        (
            {"noPL": "085111", "name": "Reims Jean Jaurès", "urlSiteCourse": "https://fd1-courses.leclercdrive.fr"},
            "https://fd1-courses.leclercdrive.fr/magasin-085111-085111-Reims-Jean-Jaures",
        ),
        ({"noPL": 93401, "name": "Le Crès"}, "https://fd1-courses.leclercdrive.fr/magasin-093401-093401-Le-Cres"),
        (
            {"noPL": "093401", "name": "X", "urlSiteCourse": "https://evil.example.com/magasin-093401.aspx"},
            "https://fd1-courses.leclercdrive.fr/magasin-093401-093401-X",
        ),
        ({"noPL": "abc", "name": "X"}, None),
        ({"name": "X"}, None),
    ],
)
def test_store_base_from_point(point, expected):
    assert lc.store_base_from_point(point) == expected


def test_parse_nearby():
    parsed = lc.parse_nearby(fixtures.LECLERC_NEARBY)
    assert [(s.id, s.name, s.services) for s in parsed] == [
        ("093401", "E.Leclerc Drive Le Crès Montpellier", ["Drive"]),
        ("093401", "E.Leclerc Drive Montpellier Comédie", ["Retrait piéton"]),
        ("190501", "E.Leclerc Drive Saint-Jean-de-Védas", ["Drive"]),
        ("190601", "E.Leclerc Drive Lattes", ["Drive"]),
        ("190801", "E.Leclerc Drive Mauguio", ["Drive"]),
    ]
    cres, relay, vedas, lattes, mauguio = parsed
    assert cres.url == "https://fd3-courses.leclercdrive.fr/magasin-093401-093401-Le-Cres-Montpellier"
    assert relay.url == "https://fd3-courses.leclercdrive.fr/magasin-093401-193402-Montpellier-Comedie"
    assert vedas.url == "https://fd3-courses.leclercdrive.fr/magasin-190501-190501-Saint-Jean-de-Vedas"
    assert lattes.url == "https://fd1-courses.leclercdrive.fr/magasin-190601-190601-Lattes"
    assert mauguio.url == "https://fd1-courses.leclercdrive.fr/magasin-190801-190801-Mauguio"
    assert (cres.address, cres.postal_code, cres.city) == ("Route de Nîmes, 34920 Le Crès", "34920", "Le Crès")
    assert (cres.lat, cres.lon, cres.distance_km) == (43.6481, 3.9395, 6.1)
    assert (vedas.lat, vedas.distance_km) == (None, 5.0)
    assert all(lc.parse_store_url(s.url) for s in parsed)
    # Shapes that are not a list of points
    assert lc.parse_nearby({"message": "Bad request"}) == []
    assert lc.parse_nearby(None) == [] and lc.parse_nearby({"points": "x"}) == []
    assert lc.nearby_points({"x": 1}) is None and lc.nearby_points([]) == []


def test_parse_nearby_distances_in_metres():
    data = {"points": [{"noPL": "1", "name": "A", "distance": 1500}, {"noPL": "2", "name": "B", "distance": 800}]}
    assert [s.distance_km for s in lc.parse_nearby(data)] == [1.5, 0.8]


def test_place_and_coordinates():
    assert lc.place_of(fixtures.LECLERC_AUTOCOMPLETE)["id"] == "woosmap-34000-synthetique"
    assert lc.place_of({"postalCodes": []}) is None and lc.place_of(None) is None
    assert lc.coordinates_of(fixtures.LECLERC_COORDINATES) == (43.6119, 3.8772)
    assert lc.coordinates_of({"lat": "x"}) is None


def test_rank_leclerc_stores():
    ranked = stores.rank_leclerc_stores(lc.parse_nearby(fixtures.LECLERC_NEARBY), MONTPELLIER)
    assert [s.city for s in ranked] == ["Montpellier", "Saint-Jean-de-Védas", "Lattes", "Le Crès", "Mauguio"]
    assert ranked[0].distance_km < 1  # computed from the coordinates
    assert ranked[1].distance_km == 5.0  # given by the site (no coordinates)
    assert 5 < ranked[2].distance_km < 6
    assert stores.first_drive(ranked).city == "Saint-Jean-de-Védas"  # never the pick-up point
    assert stores.first_drive([s for s in ranked if s.services != ["Drive"]]) is None


def test_site_store_selection():
    known = lc.parse_nearby(fixtures.LECLERC_NEARBY)
    cres = known[0]
    # 1. the address of the tab, named by the list
    chosen = lc.site_store_selection(cres.url + "/recherche.aspx?TexteRecherche=riz", "", None, known)
    assert (chosen.id, chosen.name, chosen.url, chosen.address) == (
        "093401",
        "E.Leclerc Drive Le Crès Montpellier",
        cres.url,
        "Route de Nîmes, 34920 Le Crès",
    )
    # 2. the banner of the page (real home page of Bruges), when the tab shows another address
    chosen = lc.site_store_selection("https://www.leclercdrive.fr/", fixtures.LECLERC_HOME_HTML, None, known)
    assert (chosen.id, chosen.name, chosen.url) == (
        "173301",
        "E.Leclerc Drive Bruges",
        "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges",
    )
    # The tab on Bruges: its name comes from the banner
    chosen = lc.site_store_selection(fixtures.LECLERC_HOME_URL, fixtures.LECLERC_HOME_HTML, None, [])
    assert chosen.name == "E.Leclerc Drive Bruges"
    # 3. the cookie of the site, matched with the last list
    chosen = lc.site_store_selection("https://www.leclercdrive.fr/", "", "@d=2%7c190501", known)
    assert (chosen.id, chosen.url) == ("190501", known[2].url)
    # Nothing to read
    assert lc.site_store_selection("https://www.leclercdrive.fr/", "", "@d=2%7c999999", known) is None
    assert lc.site_store_selection("about:blank", None, None, None) is None


# ---------------------------------------------------------------- store finder, cache and automatic choice


@pytest.fixture
def nearby(monkeypatch):
    """The store finder answers LECLERC_NEARBY (parsed); ``calls`` lists the locations asked."""
    calls = []
    answer = {"value": lc.parse_nearby(fixtures.LECLERC_NEARBY)}

    async def fetch(location):
        calls.append(location)
        value = answer["value"]
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return await value(location)
        return [s.model_copy() for s in value]

    monkeypatch.setattr(stores, "fetch_leclerc_nearby", fetch)
    return calls, answer


@pytest.fixture
def located():
    run(settings_service.modify(lambda s: setattr(s, "location", MONTPELLIER)))


def test_nearest_leclerc_stores_are_cached(nearby):
    calls, _ = nearby

    async def scenario():
        first = await stores.nearest_leclerc_stores(MONTPELLIER)
        again = await stores.nearest_leclerc_stores(MONTPELLIER, limit=2)
        refreshed = await stores.nearest_leclerc_stores(MONTPELLIER, refresh=True)
        last = await stores.cached_leclerc_stores()
        return first, again, refreshed, last

    first, again, refreshed, last = run(scenario())
    assert len(first) == 5 and len(again) == 2 and len(refreshed) == 5
    assert len(calls) == 2  # cached 7 days, read again when asked
    assert len(last) == 5
    assert stores.leclerc_cache_key(MONTPELLIER) == "leclerc:nearby:34000:43.612:3.877"
    assert stores.leclerc_cache_key(Location(postal_code="34000")) == "leclerc:nearby:34000:-:-"
    with pytest.raises(Exception) as error:
        run(stores.nearest_leclerc_stores(None))
    assert getattr(error.value, "status_code", None) == 400


def test_empty_answer_is_not_cached(nearby):
    calls, answer = nearby
    answer["value"] = []
    assert run(stores.nearest_leclerc_stores(MONTPELLIER)) == []
    assert run(stores.nearest_leclerc_stores(MONTPELLIER)) == []
    assert len(calls) == 2


def test_auto_pick_without_location(nearby):
    result = run(stores.auto_pick_leclerc())
    assert result.status == "no_location" and result.settings.stores == {}


def test_auto_pick_chooses_the_nearest_drive(nearby, located):
    result = run(stores.auto_pick_leclerc())
    assert result.status == "chosen" and result.message is None
    saved = result.settings.stores["leclerc"]
    # The pedestrian pick-up point is nearer, but it is not a drive
    assert (saved.id, saved.name, saved.url, saved.auto, saved.distance_km) == (
        "190501",
        "E.Leclerc Drive Saint-Jean-de-Védas",
        "https://fd3-courses.leclercdrive.fr/magasin-190501-190501-Saint-Jean-de-Vedas",
        True,
        5.0,
    )
    assert result.store.name == saved.name
    # Courses U is left alone
    assert "coursesu" not in result.settings.stores


def test_auto_pick_keeps_the_drive_chosen_by_the_user(nearby, located):
    manual = StoreSelection(id="173301", url=fixtures.LECLERC_BASE, name="E.Leclerc Drive Bruges")
    run(settings_service.set_store("leclerc", manual))
    result = run(stores.auto_pick_leclerc())
    assert result.status == "kept" and result.settings.stores["leclerc"] == manual
    calls, _ = nearby
    assert calls == []  # the site is not asked


def test_auto_pick_initial_once_per_postal_code(nearby, located):
    assert run(stores.auto_pick_leclerc(initial=True)).status == "chosen"
    # Removed by the user: never chosen again at startup for this postal code
    run(stores.forget_leclerc_store())
    run(settings_service.remove_store("leclerc"))
    result = run(stores.auto_pick_leclerc(initial=True))
    assert result.status == "kept" and "leclerc" not in result.settings.stores
    assert run(prefs.get(stores.LECLERC_PREFS_SECTION, stores.AutoPickPrefs)).auto_done_for == "34000"
    # Without « initial » (new postal code typed) it is chosen again
    assert run(stores.auto_pick_leclerc()).status == "chosen"


def test_initial_auto_pick_waits_for_a_pending_check(nearby, located, monkeypatch):
    """A page load does not ask the store finder again while its check is not validated."""
    calls, _ = nearby
    monkeypatch.setattr(stores.browser, "check_pending", lambda key: key == "leclerc")
    result = run(stores.auto_pick_leclerc(initial=True))
    assert (result.status, result.message) == ("blocked", lc.CAPTCHA_MESSAGE)
    assert calls == []
    # A new postal code (not « initial ») asks it: the user expects an answer
    assert run(stores.auto_pick_leclerc()).status == "chosen" and len(calls) == 1


def test_auto_pick_reports_a_far_drive(nearby, located):
    _, answer = nearby
    far = StoreOption(id="190801", name="E.Leclerc Drive Loin", url=lc.store_base_from_point({"noPL": "190801"}))
    far.services = ["Drive"]
    far.distance_km = 55.0
    answer["value"] = [far]
    result = run(stores.auto_pick_leclerc())
    assert result.status == "chosen"
    assert result.message == "Aucun drive E.Leclerc à moins de 40 km."


def test_auto_pick_without_drive(nearby, located):
    _, answer = nearby
    answer["value"] = [s for s in lc.parse_nearby(fixtures.LECLERC_NEARBY) if "Drive" not in s.services]
    result = run(stores.auto_pick_leclerc())
    assert (result.status, result.message) == ("none", "Aucun drive E.Leclerc trouvé.")


@pytest.mark.parametrize(
    "error, status, message",
    [
        (BlockedError(lc.CAPTCHA_MESSAGE), "blocked", lc.CAPTCHA_MESSAGE),
        (HardBlockError("E.Leclerc bloque temporairement cette connexion."), "blocked", None),
        (TimeoutError(), "timeout", "E.Leclerc n'a pas répondu à temps. Réessayez dans un instant."),
        (RuntimeError("Target closed"), "error", stores.LECLERC_AUTO_FAILED),
        (
            BrowserUnavailable("E.Leclerc nécessite Google Chrome ou Microsoft Edge installé sur l'ordinateur."),
            "error",
            "E.Leclerc nécessite Google Chrome ou Microsoft Edge installé sur l'ordinateur.",
        ),
    ],
)
def test_auto_pick_failures_are_reported(nearby, located, error, status, message):
    _, answer = nearby
    answer["value"] = error
    result = run(stores.auto_pick_leclerc())
    assert result.status == status
    assert result.message == (message or str(error))
    assert "leclerc" not in result.settings.stores


def test_auto_pick_follows_a_town_chosen_during_the_read(nearby, located):
    calls, answer = nearby
    lattes = Location(postal_code="34970", city="Lattes", lat=43.5672, lon=3.9000)

    async def moved(location):
        if len(calls) == 1:  # the user saves another postal code meanwhile
            await settings_service.modify(lambda s: setattr(s, "location", lattes))
        return lc.parse_nearby(fixtures.LECLERC_NEARBY)

    answer["value"] = moved
    result = run(stores.auto_pick_leclerc())
    assert result.status == "chosen" and result.settings.location == lattes
    assert [c.postal_code for c in calls] == ["34000", "34970"]
    assert result.store.city == "Lattes" and result.settings.stores["leclerc"].distance_km == 0


def fake_site(monkeypatch, info):
    async def fetch():
        if isinstance(info, Exception):
            raise info
        return info

    monkeypatch.setattr(stores, "fetch_leclerc_site_store", fetch)


def test_read_back_leclerc(monkeypatch, nearby):
    run(stores.nearest_leclerc_stores(MONTPELLIER))  # the last list names the drive
    scraper = SCRAPERS["leclerc"]
    scraper.site_opened_at = None
    fake_site(
        monkeypatch, {"url": "https://fd3-courses.leclercdrive.fr/magasin-093401-093401-Le-Cres-Montpellier.aspx"}
    )
    # Not opened with « Ouvrir le site »: nothing is read
    assert run(stores.read_back_leclerc(opened_only=True)).status == "none"
    scraper.setup_url(None)
    result = run(stores.read_back_leclerc(opened_only=True))
    assert result.status == "chosen"
    saved = result.settings.stores["leclerc"]
    assert (saved.id, saved.name, saved.address, saved.auto) == (
        "093401",
        "E.Leclerc Drive Le Crès Montpellier",
        "Route de Nîmes, 34920 Le Crès",
        False,
    )
    assert scraper.site_opened_at is None
    assert run(stores.read_back_leclerc()).status == "kept"
    # The banner of a drive not in the list
    fake_site(monkeypatch, {"url": "https://www.leclercdrive.fr/", "html": fixtures.LECLERC_HOME_HTML})
    result = run(stores.read_back_leclerc())
    assert result.status == "chosen" and result.store.name == "E.Leclerc Drive Bruges"
    fake_site(monkeypatch, {"url": "https://www.leclercdrive.fr/", "html": "", "cookie": None})
    assert run(stores.read_back_leclerc()).status == "none"
    fake_site(monkeypatch, None)
    assert run(stores.read_back_leclerc()).status == "none"
    fake_site(monkeypatch, BlockedError(lc.CAPTCHA_MESSAGE))
    assert run(stores.read_back_leclerc()).status == "blocked"
    fake_site(monkeypatch, TimeoutError())
    result = run(stores.read_back_leclerc())
    assert (result.status, result.message) == ("timeout", "E.Leclerc n'a pas répondu à temps.")
    fake_site(monkeypatch, RuntimeError("Target closed"))
    assert run(stores.read_back_leclerc()).status == "error"


def test_setup_url_of_the_drive():
    scraper = SCRAPERS["leclerc"]
    assert scraper.setup_url(None) == "https://www.leclercdrive.fr/"
    store = StoreSelection(id="173301", url=fixtures.LECLERC_BASE)
    assert scraper.setup_url(store) == fixtures.LECLERC_HOME_URL
    assert scraper.site_opened_at is not None
    scraper.site_opened_at = None


# ---------------------------------------------------------------- API


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def test_api_retailers_describes_leclerc(client):
    retailers = {r["key"]: r for r in client.get("/api/retailers").json()}
    leclerc = retailers["leclerc"]
    assert (leclerc["label"], leclerc["needs_store"], leclerc["finds_stores"], leclerc["auto_store"]) == (
        "E.Leclerc",
        True,
        True,
        True,
    )
    assert leclerc["store_url_example"] == lc.STORE_URL_EXAMPLE
    assert leclerc["home_url"] == "https://www.leclercdrive.fr/" and not leclerc["national"]
    assert retailers["coursesu"]["auto_store"] and retailers["coursesu"]["store_url_example"]
    assert not retailers["intermarche"]["auto_store"] and retailers["intermarche"]["store_url_example"] is None


def test_api_leclerc_stores(client, nearby, located):
    body = client.get("/api/retailers/leclerc/stores").json()
    assert [s["city"] for s in body] == ["Montpellier", "Saint-Jean-de-Védas", "Lattes", "Le Crès", "Mauguio"]
    assert body[0]["services"] == ["Retrait piéton"]


def test_api_leclerc_stores_needs_a_location(client, nearby):
    response = client.get("/api/retailers/leclerc/stores")
    assert response.status_code == 400
    assert response.json()["detail"] == "Indiquez d'abord votre code postal."


@pytest.mark.parametrize(
    "error, status, detail",
    [
        (BlockedError(lc.CAPTCHA_MESSAGE), 502, lc.CAPTCHA_MESSAGE),
        (TimeoutError(), 504, "E.Leclerc n'a pas répondu à temps."),
    ],
)
def test_api_leclerc_stores_errors(client, nearby, located, error, status, detail):
    _, answer = nearby
    answer["value"] = error
    response = client.get("/api/retailers/leclerc/stores")
    assert (response.status_code, response.json()["detail"]) == (status, detail)


def test_api_auto_from_site_and_remove(client, nearby, located, monkeypatch):
    result = client.post("/api/retailers/leclerc/store/auto?initial=true").json()
    assert result["status"] == "chosen" and result["settings"]["stores"]["leclerc"]["auto"] is True
    fake_site(monkeypatch, {"url": fixtures.LECLERC_HOME_URL, "html": fixtures.LECLERC_HOME_HTML})
    SCRAPERS["leclerc"].site_opened_at = 1.0
    result = client.post("/api/retailers/leclerc/store/from-site?opened_only=true").json()
    assert result["status"] == "chosen"
    assert result["settings"]["stores"]["leclerc"]["name"] == "E.Leclerc Drive Bruges"
    assert client.post("/api/retailers/leclerc/store/auto").json()["status"] == "kept"
    assert client.delete("/api/retailers/leclerc/store").status_code == 200
    result = client.post("/api/retailers/leclerc/store/auto?initial=true").json()
    assert result["status"] == "kept" and "leclerc" not in result["settings"]["stores"]


def test_api_auto_never_fails(client):
    response = client.post("/api/retailers/leclerc/store/auto")
    assert response.status_code == 200 and response.json()["status"] == "no_location"


@pytest.mark.parametrize("path", ["/api/retailers/aldi/store/auto", "/api/retailers/intermarche/store/from-site"])
def test_api_auto_only_for_its_retailers(client, path):
    response = client.post(path)
    assert response.status_code == 404
    assert response.json()["detail"] == "PrixMalin ne choisit pas lui-même le magasin de cette enseigne."
    assert client.get("/api/retailers/aldi/stores").status_code == 404
    assert client.post("/api/retailers/inconnue/store/auto").status_code == 404


def test_api_pasted_address(client):
    url = "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges/recherche.aspx?TexteRecherche=riz"
    saved = client.put("/api/retailers/leclerc/store", json={"url": url}).json()["stores"]["leclerc"]
    assert saved == {
        "id": "173301",
        "name": "E.Leclerc Drive Bruges",
        "url": "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges",
        "address": None,
        "auto": False,
        "distance_km": None,
    }
    for bad in (
        "https://www.leclercdrive.fr/region-occitanie/",
        "http://fd12-courses.leclercdrive.fr/magasin-173301",
        "",
    ):
        response = client.put("/api/retailers/leclerc/store", json={"url": bad})
        assert response.status_code == 400
        assert response.json()["detail"] == f"Adresse invalide. Exemple : {lc.STORE_URL_EXAMPLE}"
    # An identifier that is not the one of the address
    response = client.put("/api/retailers/leclerc/store", json={"id": "093401", "url": url})
    assert (response.status_code, response.json()["detail"]) == (422, "Identifiant de magasin invalide.")
    assert client.put("/api/retailers/leclerc/store", json={"id": "12/34", "url": url}).status_code == 422


def test_api_choose_a_listed_drive(client, nearby, located):
    option = client.get("/api/retailers/leclerc/stores").json()[3]
    body = {k: option[k] for k in ("id", "name", "address", "url", "distance_km")}
    saved = client.put("/api/retailers/leclerc/store", json=body).json()["stores"]["leclerc"]
    assert (saved["id"], saved["name"], saved["url"], saved["address"]) == (
        "093401",
        "E.Leclerc Drive Le Crès Montpellier",
        "https://fd3-courses.leclercdrive.fr/magasin-093401-093401-Le-Cres-Montpellier",
        "Route de Nîmes, 34920 Le Crès",
    )
    assert json.loads(run(stores_cache.get(stores.LECLERC_LAST_KEY))[0])
