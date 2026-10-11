"""User settings: location and the store chosen for each retailer (area of P4).

Every change goes through ``modify(fn)``: read, change and write under one lock,
so that two changes made at the same time (a store chosen on the phone while
the location is saved on the PC) are both kept.

``geocode(postal_code)`` gives the towns of a postal code with their
coordinates (geo.api.gouv.fr, then the IGN geocoder). It returns ``[]`` for an
unknown postal code and raises ``GeocodingUnavailable`` when no service
answered. Tests replace ``HTTP_TRANSPORT`` with an ``httpx.MockTransport``.
"""

import asyncio
import inspect
import logging
import os
import time
from collections.abc import Callable
from typing import Any

import httpx

from backend.errors import AppError
from backend.models import (
    Location,
    LocationRequest,
    LocationResponse,
    OnboardingState,
    OnboardingStatus,
    OnboardingUpdate,
    Settings,
    StoreSelection,
)
from backend.repos import settings_store
from backend.services import hooks, prefs

logger = logging.getLogger("prixmalin.settings")

SETTINGS_KEY = "settings"

GEO_COMMUNES_URL = "https://geo.api.gouv.fr/communes"
IGN_SEARCH_URL = "https://data.geopf.fr/geocodage/search"
GEO_TIMEOUT_SECONDS = 8

# Replaced by an httpx.MockTransport in the tests (None: the real network)
HTTP_TRANSPORT: httpx.AsyncBaseTransport | None = None

UNKNOWN_POSTAL_CODE = "Code postal inconnu : vérifiez les 5 chiffres."

# Preferences of the first-launch assistant (#/bienvenue)
ONBOARDING_SECTION = "p4.onboarding"
# PRIXMALIN_ONBOARDING=0: the assistant never opens by itself (tests)
AUTO_ONBOARDING = os.environ.get("PRIXMALIN_ONBOARDING", "1") != "0"


class GeocodingUnavailable(AppError):
    """No geo service answered (no Internet, service down)."""

    status_code = 503
    code = "geocoding_unavailable"


def http_client(timeout: float = GEO_TIMEOUT_SECONDS) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, transport=HTTP_TRANSPORT, follow_redirects=True)


# ---------------------------------------------------------------- storage


_lock: tuple[asyncio.AbstractEventLoop, asyncio.Lock] | None = None


def _get_lock() -> asyncio.Lock:
    """One lock per event loop (each test runs its own loop)."""
    global _lock
    loop = asyncio.get_running_loop()
    if _lock is None or _lock[0] is not loop:
        _lock = (loop, asyncio.Lock())
    return _lock[1]


async def load_settings() -> Settings:
    raw = await settings_store.get_setting(SETTINGS_KEY)
    if raw:
        try:
            return Settings.model_validate_json(raw)
        except ValueError:
            logger.warning("Invalid settings in database, using defaults")
    return Settings()


async def save_settings(settings: Settings) -> Settings:
    """Write ``settings`` as they are (prefer ``modify``, which cannot lose a change)."""
    async with _get_lock():
        await settings_store.set_setting(SETTINGS_KEY, settings.model_dump_json())
    return settings


async def modify(fn: Callable[[Settings], Any]) -> Settings:
    """Change the settings with ``fn`` and save them, under the settings lock.

    ``fn`` receives the current settings; it changes them in place or returns
    new ones, and may be a coroutine function. Returns the saved settings.
    """
    async with _get_lock():
        current = await load_settings()
        result = fn(current)
        if inspect.isawaitable(result):
            result = await result
        new = result if isinstance(result, Settings) else current
        await settings_store.set_setting(SETTINGS_KEY, new.model_dump_json())
        return new


# ---------------------------------------------------------------- geocoding


def parse_geo_communes(postal_code: str, data: Any) -> list[Location]:
    """Towns of a geo.api.gouv.fr ``/communes`` answer (those with coordinates)."""
    towns = []
    for town in data if isinstance(data, list) else []:
        try:
            lon, lat = town["centre"]["coordinates"][:2]
            department = town.get("departement") or {}
            towns.append(
                Location(
                    postal_code=postal_code,
                    city=town["nom"],
                    lat=float(lat),
                    lon=float(lon),
                    department_code=town.get("codeDepartement") or department.get("code"),
                    department_name=department.get("nom"),
                )
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return towns


def parse_ign_features(postal_code: str, data: Any) -> list[Location]:
    """Towns of an IGN geocoder answer (``features`` of type municipality)."""
    towns = []
    features = data.get("features", []) if isinstance(data, dict) else []
    for feature in features:
        try:
            props = feature["properties"]
            if props.get("postcode") != postal_code:
                continue
            lon, lat = feature["geometry"]["coordinates"][:2]
            # « 34, Hérault, Occitanie »
            context = [part.strip() for part in str(props.get("context") or "").split(",")]
            towns.append(
                Location(
                    postal_code=postal_code,
                    city=props.get("city") or props.get("name"),
                    lat=float(lat),
                    lon=float(lon),
                    department_code=context[0] or None,
                    department_name=context[1] if len(context) > 1 else None,
                )
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return towns


async def geocode(postal_code: str) -> list[Location]:
    """Towns (with coordinates) of a French postal code, from the public geo APIs.

    ``[]``: unknown postal code. ``GeocodingUnavailable``: no service answered.
    """
    answered = False
    async with http_client() as client:
        try:
            r = await client.get(
                GEO_COMMUNES_URL,
                params={
                    "codePostal": postal_code,
                    "fields": "nom,centre,codeDepartement,departement",
                    "format": "json",
                },
            )
            r.raise_for_status()
            answered = True
            towns = parse_geo_communes(postal_code, r.json())
            if towns:
                return towns
        except (httpx.HTTPError, ValueError) as e:
            logger.info("geo.api.gouv.fr unavailable: %s", e)
        try:
            r = await client.get(IGN_SEARCH_URL, params={"q": postal_code, "type": "municipality", "limit": 10})
            r.raise_for_status()
            answered = True
            return parse_ign_features(postal_code, r.json())
        except (httpx.HTTPError, ValueError) as e:
            logger.warning("Geocoding of %s failed: %s", postal_code, e)
    if not answered:
        raise GeocodingUnavailable("Le service de localisation ne répond pas. Réessayez dans un instant.")
    return []


# ---------------------------------------------------------------- changes


async def set_location(request: LocationRequest) -> LocationResponse:
    """Save the postal code (and the town chosen among ``communes``).

    Unknown postal code: ``AppError`` 422, nothing saved. No geo service: the
    postal code is saved without town (``geocoding_failed``).
    """
    try:
        communes = await geocode(request.postal_code)
    except GeocodingUnavailable:
        communes = None
    if communes == []:
        raise AppError(UNKNOWN_POSTAL_CODE, 422, "unknown_postal_code")
    chosen = next((c for c in communes or [] if request.city and c.city == request.city), None)
    location = chosen or (communes[0] if communes else Location(postal_code=request.postal_code))

    def change(settings: Settings) -> None:
        settings.location = location

    return LocationResponse(settings=await modify(change), communes=communes or [], geocoding_failed=communes is None)


async def set_store(key: str, selection: StoreSelection) -> Settings:
    def change(settings: Settings) -> None:
        settings.stores[key] = selection

    return await modify(change)


async def remove_store(key: str) -> Settings:
    def change(settings: Settings) -> None:
        settings.stores.pop(key, None)

    return await modify(change)


async def set_show_browser(show: bool) -> Settings:
    def change(settings: Settings) -> None:
        settings.show_browser = show

    return await modify(change)


# ---------------------------------------------------------------- first-launch assistant


def onboarding_needed(state: OnboardingState, settings: Settings, auto: bool = True) -> bool:
    """The assistant opens by itself: never shown, never finished, nothing set yet."""
    return auto and not state.seen and not state.done and settings.location is None and not settings.stores


async def onboarding_status() -> OnboardingStatus:
    state = await prefs.get(ONBOARDING_SECTION, OnboardingState)
    needed = onboarding_needed(state, await load_settings(), AUTO_ONBOARDING)
    return OnboardingStatus(**state.model_dump(), needed=needed)


async def update_onboarding(update: OnboardingUpdate) -> OnboardingStatus:
    def change(state: OnboardingState) -> None:
        if update.seen is not None:
            state.seen = update.seen
        if update.done is not None:
            state.done = update.done
            state.done_at = time.time() if update.done else None

    await prefs.update(ONBOARDING_SECTION, OnboardingState, change)
    return await onboarding_status()


# --- Backup provider: every row of the settings table (preferences included) ---


async def export_backup() -> dict[str, str]:
    return await settings_store.all_settings()


async def restore_backup(data: dict[str, str]) -> None:
    """Replace every setting with those of a backup."""
    async with _get_lock():
        for key in await settings_store.all_settings():
            if key not in data:
                await settings_store.delete_setting(key)
        for key, value in data.items():
            await settings_store.set_setting(str(key), str(value))


hooks.register_backup("settings", export_backup, restore_backup)
