"""B52: settings of the location and of the stores (geocoding, atomic writes, validation)."""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.errors import AppError
from backend.models import Location, LocationRequest, OnboardingUpdate, Settings, StoreSelection
from backend.services import settings as settings_service
from tests.conftest import run

GEO_ROUJAN = [
    {
        "nom": "Roujan",
        "centre": {"type": "Point", "coordinates": [3.3108, 43.505]},
        "codeDepartement": "34",
        "departement": {"code": "34", "nom": "Hérault"},
    },
    {
        "nom": "Gabian",
        "centre": {"type": "Point", "coordinates": [3.2742, 43.5106]},
        "codeDepartement": "34",
        "departement": {"code": "34", "nom": "Hérault"},
    },
]

IGN_ROUJAN = {
    "features": [
        {
            "properties": {"postcode": "34320", "city": "Roujan", "context": "34, Hérault, Occitanie"},
            "geometry": {"coordinates": [3.31, 43.5]},
        },
        # Another postal code: ignored
        {"properties": {"postcode": "34120", "city": "Pézenas"}, "geometry": {"coordinates": [3.42, 43.45]}},
        {"properties": {"postcode": "34320"}},  # no coordinates
    ]
}


def use_network(monkeypatch, handler):
    """Answer the geo services with ``handler(request)`` (an httpx.MockTransport)."""
    calls = []

    def recorded(request):
        calls.append(request.url.host)
        return handler(request)

    monkeypatch.setattr(settings_service, "HTTP_TRANSPORT", httpx.MockTransport(recorded))
    return calls


# ---------------------------------------------------------------- geocoding


def test_geocode_success(monkeypatch):
    def handler(request):
        assert request.url.params["codePostal"] == "34320"
        assert "departement" in request.url.params["fields"]
        return httpx.Response(200, json=GEO_ROUJAN)

    calls = use_network(monkeypatch, handler)
    towns = run(settings_service.geocode("34320"))
    assert calls == ["geo.api.gouv.fr"]
    assert towns[0] == Location(
        postal_code="34320",
        city="Roujan",
        lat=43.505,
        lon=3.3108,
        department_code="34",
        department_name="Hérault",
    )
    assert [t.city for t in towns] == ["Roujan", "Gabian"]


def test_geocode_falls_back_to_ign(monkeypatch):
    def handler(request):
        if request.url.host == "geo.api.gouv.fr":
            return httpx.Response(503)
        assert request.url.params["q"] == "34320"
        return httpx.Response(200, json=IGN_ROUJAN)

    calls = use_network(monkeypatch, handler)
    towns = run(settings_service.geocode("34320"))
    assert calls == ["geo.api.gouv.fr", "data.geopf.fr"]
    assert towns == [
        Location(
            postal_code="34320", city="Roujan", lat=43.5, lon=3.31, department_code="34", department_name="Hérault"
        )
    ]


def test_geocode_empty_answers_mean_unknown_postal_code(monkeypatch):
    def handler(request):
        if request.url.host == "geo.api.gouv.fr":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"features": []})

    calls = use_network(monkeypatch, handler)
    assert run(settings_service.geocode("00000")) == []
    # The IGN geocoder is asked too before giving up
    assert calls == ["geo.api.gouv.fr", "data.geopf.fr"]


def test_geocode_without_any_service(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("hors ligne")

    use_network(monkeypatch, handler)
    with pytest.raises(settings_service.GeocodingUnavailable) as error:
        run(settings_service.geocode("34320"))
    assert error.value.status_code == 503
    assert "ne répond pas" in error.value.message


def test_geocode_ignores_garbage(monkeypatch):
    def handler(request):
        if request.url.host == "geo.api.gouv.fr":
            return httpx.Response(200, json=[{"nom": "Sans centre"}, "texte", {"centre": None}])
        return httpx.Response(200, text="pas du JSON")

    use_network(monkeypatch, handler)
    # The IGN answer is unreadable: the services answered, the code is unknown
    assert run(settings_service.geocode("34320")) == []
    assert settings_service.parse_geo_communes("34320", {"pas": "une liste"}) == []
    assert settings_service.parse_ign_features("34320", ["pas un objet"]) == []


# ---------------------------------------------------------------- location


def fake_geocode(monkeypatch, towns):
    async def geocode(postal_code):
        if isinstance(towns, Exception):
            raise towns
        return [Location(postal_code=postal_code, city=c, lat=a, lon=o) for c, a, o in towns]

    monkeypatch.setattr(settings_service, "geocode", geocode)


def test_set_location_with_the_town_chosen(monkeypatch):
    fake_geocode(monkeypatch, [("Roujan", 43.5, 3.31), ("Gabian", 43.51, 3.27)])
    response = run(settings_service.set_location(LocationRequest(postal_code="34320")))
    assert response.settings.location.city == "Roujan"  # the first town by default
    assert [c.city for c in response.communes] == ["Roujan", "Gabian"]
    response = run(settings_service.set_location(LocationRequest(postal_code="34320", city="Gabian")))
    assert response.settings.location.city == "Gabian"
    assert not response.geocoding_failed


def test_unknown_postal_code_is_an_error_and_saves_nothing(monkeypatch):
    fake_geocode(monkeypatch, [])
    with pytest.raises(AppError) as error:
        run(settings_service.set_location(LocationRequest(postal_code="00000")))
    assert (error.value.status_code, error.value.code) == (422, "unknown_postal_code")
    assert error.value.message == "Code postal inconnu : vérifiez les 5 chiffres."
    assert run(settings_service.load_settings()).location is None


def test_postal_code_saved_without_geo_service(monkeypatch):
    fake_geocode(monkeypatch, settings_service.GeocodingUnavailable("hors ligne"))
    response = run(settings_service.set_location(LocationRequest(postal_code="34320")))
    assert response.geocoding_failed
    assert response.settings.location == Location(postal_code="34320")


# ---------------------------------------------------------------- atomic writes


def test_concurrent_changes_are_all_kept(monkeypatch):
    fake_geocode(monkeypatch, [("Roujan", 43.5, 3.31)])
    real_get = settings_service.settings_store.get_setting

    async def slow_get(key):
        value = await real_get(key)
        await asyncio.sleep(0.01)  # leaves time to the other changes to interleave
        return value

    monkeypatch.setattr(settings_service.settings_store, "get_setting", slow_get)

    async def scenario():
        await asyncio.gather(
            settings_service.set_location(LocationRequest(postal_code="34320")),
            settings_service.set_store("intermarche", StoreSelection(id="06814", name="Lattes")),
            settings_service.set_store("coursesu", StoreSelection(url="https://www.coursesu.com/drive-superu-roujan")),
            settings_service.set_show_browser(True),
        )
        return await settings_service.load_settings()

    saved = run(scenario())
    assert saved.location.city == "Roujan"
    assert set(saved.stores) == {"intermarche", "coursesu"}
    assert saved.show_browser is True


def test_modify_accepts_a_coroutine_and_a_new_model():
    async def scenario():
        async def change(settings):
            settings.show_browser = True

        first = await settings_service.modify(change)
        second = await settings_service.modify(lambda s: Settings(stores={"intermarche": StoreSelection(id="12")}))
        return first, second, await settings_service.load_settings()

    first, second, saved = run(scenario())
    assert first.show_browser and not second.show_browser
    assert saved == second


def test_unreadable_settings_give_the_defaults():
    async def scenario():
        await settings_service.settings_store.set_setting(settings_service.SETTINGS_KEY, "{pas du json")
        return await settings_service.load_settings()

    assert run(scenario()) == Settings()


def test_remove_store_and_backup():
    async def scenario():
        await settings_service.set_store("intermarche", StoreSelection(id="06814"))
        backup = await settings_service.export_backup()
        await settings_service.remove_store("intermarche")
        await settings_service.remove_store("intermarche")  # nothing to remove: no error
        removed = await settings_service.load_settings()
        await settings_service.settings_store.set_setting("pref:autre", "{}")
        await settings_service.restore_backup(backup)
        return removed, await settings_service.load_settings(), await settings_service.export_backup()

    removed, restored, after = run(scenario())
    assert removed.stores == {}
    assert restored.stores["intermarche"].id == "06814"
    assert "pref:autre" not in after  # the restore replaces everything


# ---------------------------------------------------------------- first-launch assistant


def test_onboarding_needed_only_on_an_empty_setup():
    empty = Settings()
    state = settings_service.OnboardingState()
    assert settings_service.onboarding_needed(state, empty)
    assert not settings_service.onboarding_needed(state, empty, auto=False)
    assert not settings_service.onboarding_needed(state.model_copy(update={"seen": True}), empty)
    assert not settings_service.onboarding_needed(state.model_copy(update={"done": True}), empty)
    assert not settings_service.onboarding_needed(state, Settings(location=Location(postal_code="34320")))
    assert not settings_service.onboarding_needed(state, Settings(stores={"intermarche": StoreSelection(id="12")}))


def test_onboarding_status_and_update(monkeypatch):
    monkeypatch.setattr(settings_service, "AUTO_ONBOARDING", True)

    async def scenario():
        before = await settings_service.onboarding_status()
        seen = await settings_service.update_onboarding(OnboardingUpdate(seen=True))
        done = await settings_service.update_onboarding(OnboardingUpdate(done=True))
        again = await settings_service.update_onboarding(OnboardingUpdate(done=False))
        return before, seen, done, again

    before, seen, done, again = run(scenario())
    assert before.needed and not before.seen
    assert seen.seen and not seen.needed
    assert done.done and done.done_at is not None
    assert not again.done and again.done_at is None


# ---------------------------------------------------------------- API


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.mark.parametrize(
    "body, message",
    [
        ({"postal_code": "3432"}, "Saisissez 5 chiffres, par ex. 34000."),
        ({"postal_code": "34 32a"}, "Saisissez 5 chiffres, par ex. 34000."),
        ({"postal_code": "３４３２０"}, "Saisissez 5 chiffres, par ex. 34000."),  # full-width digits
        ({"postal_code": "34320", "city": "x" * 101}, "Nom de commune trop long (100 caractères au plus)."),
    ],
)
def test_location_validation(client, body, message):
    response = client.post("/api/settings/location", json=body)
    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == message


def test_location_api(client, monkeypatch):
    fake_geocode(monkeypatch, [])
    response = client.post("/api/settings/location", json={"postal_code": "00000"})
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Code postal inconnu : vérifiez les 5 chiffres.",
        "code": "unknown_postal_code",
    }
    fake_geocode(monkeypatch, [("Roujan", 43.5, 3.31), ("Gabian", 43.51, 3.27)])
    body = client.post("/api/settings/location", json={"postal_code": " 34320 ", "city": "Gabian"}).json()
    assert body["settings"]["location"]["city"] == "Gabian"
    assert len(body["communes"]) == 2


@pytest.mark.parametrize(
    "key, body, status",
    [
        ("intermarche", {"id": "../x"}, 422),
        ("intermarche", {"id": "1"}, 422),
        ("intermarche", {"id": "123456789"}, 422),
        ("intermarche", {"id": "x" * 41}, 422),
        ("coursesu", {"id": "../x", "url": "https://www.coursesu.com/drive-superu-roujan"}, 422),
        ("intermarche", {"id": "06814", "name": "n" * 201}, 422),
        ("intermarche", {"id": "06814", "address": "a" * 201}, 422),
        ("coursesu", {"url": "https://www.coursesu.com/drive-" + "x" * 300}, 422),
        ("coursesu", {"url": "https://www.example.com/drive-superu-roujan"}, 400),
        ("coursesu", {"url": "https://www.coursesu.com/drive/superu/roujan"}, 400),
        ("coursesu", {"url": "javascript:alert(1)"}, 400),
        ("coursesu", {}, 400),
        ("intermarche", {}, 400),
        ("intermarche", {"id": "06814", "distance_km": -1}, 422),
        ("aldi", {"id": "12"}, 400),
        ("inconnue", {"id": "12"}, 404),
    ],
)
def test_store_validation(client, key, body, status):
    response = client.put(f"/api/retailers/{key}/store", json=body)
    assert response.status_code == status, response.json()
    assert client.get("/api/settings").json()["stores"] == {}


def test_valid_stores_are_saved(client):
    saved = client.put("/api/retailers/intermarche/store", json={"id": "06814", "name": " Lattes "}).json()
    assert saved["stores"]["intermarche"]["name"] == "Lattes"
    saved = client.put(
        "/api/retailers/coursesu/store", json={"url": "https://www.coursesu.com/drive-superu-roujan/", "id": "11111"}
    ).json()
    assert saved["stores"]["coursesu"] == {
        "id": "11111",
        "name": "Super U Roujan",
        "url": "https://www.coursesu.com/drive-superu-roujan",
        "address": None,
        "auto": False,
        "distance_km": None,
    }
    assert client.delete("/api/retailers/coursesu/store").json()["stores"].keys() == {"intermarche"}
    assert client.delete("/api/retailers/inconnue/store").status_code == 404


def test_onboarding_api(client, monkeypatch):
    monkeypatch.setattr(settings_service, "AUTO_ONBOARDING", True)
    assert client.get("/api/settings/onboarding").json() == {
        "seen": False,
        "done": False,
        "done_at": None,
        "needed": True,
    }
    body = client.patch("/api/settings/onboarding", json={"seen": True}).json()
    assert body["seen"] and not body["needed"]
    body = client.patch("/api/settings/onboarding", json={"done": True}).json()
    assert body["done"] and body["done_at"] > 0


def test_show_browser_setting(client, monkeypatch):
    shown = []

    async def set_show_browser(show):
        shown.append(show)

    monkeypatch.setattr(main.browser, "set_show_browser", set_show_browser)
    assert client.patch("/api/settings", json={"show_browser": True}).json()["show_browser"] is True
    assert client.patch("/api/settings", json={}).json()["show_browser"] is True
    assert shown == [True]
