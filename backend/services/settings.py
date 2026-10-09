"""User settings: location and the store chosen for each retailer."""

import logging

import httpx

from backend import database
from backend.models import Location, LocationRequest, LocationResponse, Settings, StoreSelection

logger = logging.getLogger(__name__)

SETTINGS_KEY = "settings"


async def load_settings() -> Settings:
    raw = await database.get_setting(SETTINGS_KEY)
    if raw:
        try:
            return Settings.model_validate_json(raw)
        except ValueError:
            logger.warning("Invalid settings in database, using defaults")
    return Settings()


async def save_settings(settings: Settings) -> Settings:
    await database.set_setting(SETTINGS_KEY, settings.model_dump_json())
    return settings


async def geocode(postal_code: str) -> list[Location]:
    """Towns (with coordinates) for a French postal code, from the public geo APIs."""
    async with httpx.AsyncClient(timeout=8) as client:
        try:
            r = await client.get(
                "https://geo.api.gouv.fr/communes",
                params={"codePostal": postal_code, "fields": "nom,centre", "format": "json"},
            )
            r.raise_for_status()
            towns = [
                Location(
                    postal_code=postal_code,
                    city=t["nom"],
                    lon=t["centre"]["coordinates"][0],
                    lat=t["centre"]["coordinates"][1],
                )
                for t in r.json()
                if t.get("centre")
            ]
            if towns:
                return towns
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            logger.info("geo.api.gouv.fr unavailable: %s", e)
        try:
            r = await client.get(
                "https://data.geopf.fr/geocodage/search",
                params={"q": postal_code, "type": "municipality", "limit": 10},
            )
            r.raise_for_status()
            return [
                Location(
                    postal_code=postal_code,
                    city=f["properties"].get("city") or f["properties"].get("name"),
                    lon=f["geometry"]["coordinates"][0],
                    lat=f["geometry"]["coordinates"][1],
                )
                for f in r.json().get("features", [])
                if f["properties"].get("postcode") == postal_code
            ]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            logger.warning("Geocoding of %s failed: %s", postal_code, e)
    return []


async def set_location(request: LocationRequest) -> LocationResponse:
    communes = await geocode(request.postal_code)
    chosen = next((c for c in communes if request.city and c.city == request.city), None)
    location = chosen or (communes[0] if communes else Location(postal_code=request.postal_code))
    settings = await load_settings()
    settings.location = location
    return LocationResponse(settings=await save_settings(settings), communes=communes)


async def set_store(key: str, selection: StoreSelection) -> Settings:
    settings = await load_settings()
    settings.stores[key] = selection
    return await save_settings(settings)


async def remove_store(key: str) -> Settings:
    settings = await load_settings()
    settings.stores.pop(key, None)
    return await save_settings(settings)


async def set_show_browser(show: bool) -> Settings:
    settings = await load_settings()
    settings.show_browser = show
    return await save_settings(settings)
