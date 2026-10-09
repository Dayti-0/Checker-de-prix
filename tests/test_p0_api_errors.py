"""B05: the errors of the API are handled in one place (backend/api/errors.py)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import main
from backend.api import errors
from backend.browser import BrowserUnavailable
from backend.errors import AppError, short_error
from backend.models import Location
from backend.scrapers.base import BlockedError, ScraperError
from backend.services import settings


@pytest.mark.parametrize(
    "error, status, body",
    [
        (
            BrowserUnavailable("Aucun navigateur utilisable."),
            502,
            {"detail": "Aucun navigateur utilisable.", "code": "browser_unavailable"},
        ),
        (
            ScraperError("Intermarché a répondu HTTP 500"),
            502,
            {"detail": "Intermarché a répondu HTTP 500", "code": "error"},
        ),
        (BlockedError("Vérification requise"), 502, {"detail": "Vérification requise", "code": "blocked"}),
        # asyncio.TimeoutError is TimeoutError since Python 3.11
        (TimeoutError(), 504, {"detail": errors.TIMEOUT_MESSAGE, "code": "timeout"}),
        (AppError("Liste pleine", 409, "list_full"), 409, {"detail": "Liste pleine", "code": "list_full"}),
    ],
)
def test_known_errors_become_json(error, status, body):
    app = FastAPI()
    errors.install(app)

    @app.get("/boom")
    async def boom():
        raise error

    response = TestClient(app).get("/boom")
    assert response.status_code == status
    assert response.json() == body


def test_guard():
    with pytest.raises(AppError) as caught, errors.guard("Recherche impossible"):
        raise RuntimeError("Page crashed\nCall log: ...")
    assert (caught.value.status_code, caught.value.message) == (502, "Recherche impossible : Page crashed")

    with pytest.raises(AppError) as caught, errors.guard("Recherche impossible", timeout_message="Trop long."):
        raise TimeoutError
    assert (caught.value.status_code, caught.value.message) == (504, "Trop long.")

    # Known errors keep their own answer
    with pytest.raises(BlockedError), errors.guard("Recherche impossible"):
        raise BlockedError("Vérification requise")
    with pytest.raises(TimeoutError), errors.guard("Recherche impossible"):
        raise TimeoutError


def test_short_error():
    assert short_error(RuntimeError("first\nsecond")) == "first"
    assert short_error(RuntimeError("x" * 500)) == "x" * 200
    assert short_error(TimeoutError()) == "TimeoutError"


@pytest.fixture
def client(monkeypatch):
    async def geocode(postal_code):
        return [Location(postal_code=postal_code, city="Lattes", lat=43.57, lon=3.9)]

    monkeypatch.setattr(settings, "geocode", geocode)
    with TestClient(main.app) as c:
        c.post("/api/settings/location", json={"postal_code": "34970"})
        yield c


def failing(error):
    async def fn(*args, **kwargs):
        raise error

    return fn


@pytest.mark.parametrize(
    "error, status, detail",
    [
        (TimeoutError(), 504, "Intermarché n'a pas répondu à temps."),
        (
            BlockedError("Intermarché bloque les requêtes automatiques"),
            502,
            "Intermarché bloque les requêtes automatiques",
        ),
        (BrowserUnavailable("Aucun navigateur utilisable."), 502, "Aucun navigateur utilisable."),
        (RuntimeError("Target closed\nmore"), 502, "Recherche des magasins impossible : Target closed"),
    ],
)
def test_store_finder_errors(client, monkeypatch, error, status, detail):
    monkeypatch.setattr(main.browser, "run", failing(error))
    response = client.get("/api/retailers/intermarche/stores")
    assert (response.status_code, response.json()["detail"]) == (status, detail)


@pytest.mark.parametrize(
    "error, status, detail",
    [
        (
            BrowserUnavailable("Impossible d'afficher la fenêtre du navigateur"),
            502,
            "Impossible d'afficher la fenêtre du navigateur",
        ),
        (RuntimeError("net::ERR_NAME_NOT_RESOLVED"), 502, "Impossible d'ouvrir le site : net::ERR_NAME_NOT_RESOLVED"),
        (TimeoutError(), 504, errors.TIMEOUT_MESSAGE),
    ],
)
def test_open_site_errors(client, monkeypatch, error, status, detail):
    monkeypatch.setattr(main.browser, "open_setup", failing(error))
    response = client.post("/api/browser/setup", json={"store": "aldi"})
    assert (response.status_code, response.json()["detail"]) == (status, detail)


def test_browser_unavailable_elsewhere(client, monkeypatch):
    monkeypatch.setattr(main.browser, "end_setup", failing(BrowserUnavailable("Pas de navigateur")))
    monkeypatch.setattr(main.browser, "set_show_browser", failing(BrowserUnavailable("Pas d'écran")))
    done = client.post("/api/browser/setup/done")
    assert (done.status_code, done.json()["detail"]) == (502, "Pas de navigateur")
    patch = client.patch("/api/settings", json={"show_browser": True})
    assert (patch.status_code, patch.json()["detail"]) == (502, "Pas d'écran")
