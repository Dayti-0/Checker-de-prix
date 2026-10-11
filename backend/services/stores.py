"""Stores near the user: the Courses U directory ranked by distance (area of P4).

- ``nearest_coursesu_stores(location)``: the directory (read in the Courses U
  tab, cached ``DIRECTORY_TTL``), placed on the map with the table of French
  towns (geo.api.gouv.fr, cached ``COMMUNES_TTL``), sorted by distance;
- ``auto_pick_coursesu()``: saves the nearest store when none is chosen (or
  when the current one was chosen automatically); ``initial=True`` (page
  loaded) does nothing when it was already done for this postal code, or when
  the user removed the store (preferences ``p4.coursesu``);
- ``read_back_coursesu()``: saves the store the user chose on the site.

Placing and sorting are pure functions (``build_commune_index``, ``locate``,
``rank_stores``). Without the town table, the postal codes of the stores of
the user's department are geocoded one by one (cached for good); without any
coordinates, the stores of the same postal code come first, then those of the
same department.
"""

import asyncio
import json
import logging
import math
import re
import unicodedata
from typing import Any

import httpx

from backend.browser import browser
from backend.errors import AppError
from backend.models import AutoPickResult, CoursesUPrefs, Location, Settings, StoreOption, StoreSelection
from backend.repos import stores_cache
from backend.scrapers import SCRAPERS
from backend.scrapers.base import BlockedError, ScraperError
from backend.scrapers.coursesu import MIN_DIRECTORY_STORES, site_store_selection
from backend.services import prefs
from backend.services import settings as settings_service

logger = logging.getLogger("prixmalin.stores")

COMMUNES_URL = "https://geo.api.gouv.fr/communes"
COMMUNES_TTL = 30 * 24 * 3600
DIRECTORY_TTL = 7 * 24 * 3600
# Seconds left to the Courses U tab to read the directory
DIRECTORY_TIMEOUT = 90
# Stores listed in the settings
NEAREST_COUNT = 8
# Beyond this distance the nearest store is reported as far
FAR_KM = 40
# Postal codes geocoded one by one when the town table cannot be downloaded
MAX_POSTAL_LOOKUPS = 40

# Preferences of the automatic choice (CoursesUPrefs)
PREFS_SECTION = "p4.coursesu"

COMMUNES_KEY = "geo:communes"
DIRECTORY_KEY = "coursesu:directory"
# Last directory read, whatever its size (names and addresses of the store read back from the site)
DIRECTORY_LAST_KEY = "coursesu:directory:last"
POSTAL_KEY = "geo:cp:{}"

NO_LOCATION = "Indiquez d'abord votre code postal."
NO_LOCATION_AUTO = "Indiquez votre code postal : PrixMalin choisira le magasin le plus proche."
AUTO_FAILED = (
    "La recherche du magasin Courses U le plus proche a échoué. "
    "Choisissez-le dans la liste, sur le site ou en collant l'adresse de sa page."
)

# ---------------------------------------------------------------- pure functions


def normalize_town(name: str | None) -> str:
    """'Saint-Jean-de-Védas' and 'St Jean de Vedas' -> 'saint jean de vedas'."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    text = re.sub(r"^ste\b", "sainte", text)
    text = re.sub(r"^st\b", "saint", text)
    return re.sub(r"\bcedex\b.*$", "", text).strip()


def build_commune_index(communes: Any) -> dict[str, list[list]]:
    """Postal code -> ``[[normalised town, lat, lon], ...]`` from geo.api.gouv.fr ``/communes``."""
    index: dict[str, list[list]] = {}
    for town in communes if isinstance(communes, list) else []:
        try:
            lon, lat = town["centre"]["coordinates"][:2]
            entry = [normalize_town(town["nom"]), round(float(lat), 5), round(float(lon), 5)]
            for postal_code in town.get("codesPostaux") or []:
                index.setdefault(str(postal_code), []).append(entry)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return index


def locate(postal_code: str | None, town: str | None, index: dict[str, list[list]] | None) -> tuple | None:
    """Coordinates of a store from its postal code, using its town when the code is shared."""
    entries = (index or {}).get(postal_code or "") or []
    if not entries:
        return None
    if len(entries) > 1 and town:
        wanted = normalize_town(town)
        for name, lat, lon in entries:
            if name == wanted:
                return lat, lon
        for name, lat, lon in entries:
            if name and (name in wanted or wanted in name):
                return lat, lon
    return entries[0][1], entries[0][2]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def department_of(postal_code: str | None) -> str:
    """'34320' -> '34'; overseas '97410' -> '974'."""
    code = postal_code or ""
    return code[:3] if code.startswith("97") else code[:2]


def rank_stores(
    stores: list[StoreOption], origin: Location | None, index: dict[str, list[list]] | None
) -> list[StoreOption]:
    """Stores with their distance from ``origin``, the nearest first.

    Stores that cannot be placed come after, those of the same postal code
    first, then those of the same department.
    """
    ranked = []
    for store in stores:
        coords = (store.lat, store.lon) if store.lat is not None and store.lon is not None else None
        coords = coords or locate(store.postal_code, store.city, index)
        distance = None
        if coords and origin is not None and origin.lat is not None and origin.lon is not None:
            distance = round(haversine_km(origin.lat, origin.lon, coords[0], coords[1]), 1)
        ranked.append(store.model_copy(update={"distance_km": distance}))
    origin_cp = origin.postal_code if origin else None

    def key(store: StoreOption):
        same_cp = bool(origin_cp) and store.postal_code == origin_cp
        same_dept = bool(origin_cp and store.postal_code) and department_of(store.postal_code) == department_of(
            origin_cp
        )
        return (store.distance_km is None, store.distance_km or 0.0, not same_cp, not same_dept, store.name)

    return sorted(ranked, key=key)


def selection_from_option(option: StoreOption, auto: bool = False) -> StoreSelection:
    return StoreSelection(
        id=option.id if option.id.isdigit() and 2 <= len(option.id) <= 8 else None,
        name=option.name,
        url=option.url,
        address=option.address,
        auto=auto,
        distance_km=option.distance_km,
    )


# ---------------------------------------------------------------- locks

_locks: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Lock]] = {}


def _lock(name: str) -> asyncio.Lock:
    """One lock per name and event loop (each test runs its own loop)."""
    loop = asyncio.get_running_loop()
    held = _locks.get(name)
    if held is None or held[0] is not loop:
        held = _locks[name] = (loop, asyncio.Lock())
    return held[1]


# ---------------------------------------------------------------- town coordinates


async def download_communes() -> Any:
    """Every French town with its postal codes and centre (a few MB, geo.api.gouv.fr)."""
    async with settings_service.http_client(timeout=60) as client:
        r = await client.get(COMMUNES_URL, params={"fields": "nom,codesPostaux,centre", "format": "json"})
        r.raise_for_status()
        return r.json()


async def commune_index(refresh: bool = False) -> dict[str, list[list]] | None:
    """The table postal code -> towns (cached 30 days); None when it cannot be had."""
    async with _lock("communes"):
        if not refresh:
            cached = await stores_cache.get(COMMUNES_KEY, COMMUNES_TTL)
            if cached:
                return json.loads(cached[0])
        try:
            index = build_commune_index(await download_communes())
            if index:
                await stores_cache.put(COMMUNES_KEY, json.dumps(index, separators=(",", ":")))
                return index
            logger.warning("geo.api.gouv.fr: empty town table")
        except (httpx.HTTPError, ValueError) as e:
            logger.info("Town table unavailable: %s", e)
        stale = await stores_cache.get(COMMUNES_KEY)
        return json.loads(stale[0]) if stale else None


async def postal_index(stores: list[StoreOption], origin: Location) -> dict[str, list[list]]:
    """Coordinates of the postal codes of the stores of the user's department, one by one."""
    department = department_of(origin.postal_code)
    codes = sorted({s.postal_code for s in stores if s.postal_code and department_of(s.postal_code) == department})
    index: dict[str, list[list]] = {}
    lookups = 0
    for code in codes:
        cached = await stores_cache.get(POSTAL_KEY.format(code))
        if cached:
            index[code] = json.loads(cached[0])
            continue
        if lookups >= MAX_POSTAL_LOOKUPS:
            continue
        lookups += 1
        try:
            towns = await settings_service.geocode(code)
        except AppError:
            break  # no geo service: the next ones would fail too
        entries = [[normalize_town(t.city), t.lat, t.lon] for t in towns if t.lat is not None]
        if entries:
            index[code] = entries
            await stores_cache.put(POSTAL_KEY.format(code), json.dumps(entries))
    return index


# ---------------------------------------------------------------- Courses U directory


async def fetch_coursesu_directory(department_name: str | None) -> dict:
    """``{"stores", "method"}`` read in the Courses U tab (replaced by the E2E fakes)."""
    scraper = SCRAPERS["coursesu"]
    return await browser.run(
        scraper.key, scraper.fetch_store_directory, department_name, timeout=DIRECTORY_TIMEOUT, priority="interactive"
    )


async def coursesu_directory(department_name: str | None = None, refresh: bool = False) -> list[StoreOption]:
    """Every Courses U store (cached 7 days when the national directory was read)."""
    async with _lock("directory"):
        if not refresh:
            cached = await stores_cache.get(DIRECTORY_KEY, DIRECTORY_TTL)
            if cached:
                return [StoreOption(**s) for s in json.loads(cached[0])]
        result = await fetch_coursesu_directory(department_name)
        stores = [s if isinstance(s, StoreOption) else StoreOption(**s) for s in result.get("stores", [])]
        dump = json.dumps([s.model_dump() for s in stores])
        if len(stores) >= MIN_DIRECTORY_STORES and result.get("method") != "département":
            await stores_cache.put(DIRECTORY_KEY, dump)
        if stores:
            await stores_cache.put(DIRECTORY_LAST_KEY, dump)
        return stores


async def nearest_coursesu_stores(
    location: Location | None, refresh: bool = False, limit: int = NEAREST_COUNT
) -> list[StoreOption]:
    """The ``limit`` Courses U stores nearest to ``location``."""
    if location is None:
        raise AppError(NO_LOCATION, 400, "no_location")
    stores = await coursesu_directory(location.department_name, refresh)
    if not stores:
        return []
    index = await commune_index()
    if index is None and location.lat is not None:
        index = await postal_index(stores, location)
    return rank_stores(stores, location, index)[:limit]


async def cached_coursesu_directory() -> list[StoreOption]:
    """The stores of the last directory read (however old or small), without reading the site."""
    cached = await stores_cache.get(DIRECTORY_KEY) or await stores_cache.get(DIRECTORY_LAST_KEY)
    return [StoreOption(**s) for s in json.loads(cached[0])] if cached else []


# ---------------------------------------------------------------- automatic choice


def _result(status: str, settings: Settings, message: str | None = None, store=None) -> AutoPickResult:
    return AutoPickResult(status=status, message=message, store=store, settings=settings)


async def _auto_done_for(postal_code: str | None) -> None:
    def change(p: CoursesUPrefs) -> None:
        p.auto_done_for = postal_code

    await prefs.update(PREFS_SECTION, CoursesUPrefs, change)


async def forget_coursesu_store() -> None:
    """The user removed his Courses U store: no automatic choice at startup for this postal code."""
    current = await settings_service.load_settings()
    if current.location is not None:
        await _auto_done_for(current.location.postal_code)


async def auto_pick_coursesu(refresh: bool = False, initial: bool = False) -> AutoPickResult:
    """Save the nearest Courses U store unless the user chose one himself.

    ``initial``: asked when a page loads; ``kept`` without reading the site when
    a store is chosen or when it was already done for this postal code.
    Never raises: the outcome (``status``, French ``message``) is returned.
    """
    current = await settings_service.load_settings()
    chosen = current.stores.get("coursesu")
    if chosen and (not chosen.auto or initial):
        return _result("kept", current)
    if current.location is None:
        return _result("no_location", current, NO_LOCATION_AUTO)
    if initial:
        done = await prefs.get(PREFS_SECTION, CoursesUPrefs)
        if done.auto_done_for == current.location.postal_code:
            return _result("kept", current)
    try:
        stores = await nearest_coursesu_stores(current.location, refresh=refresh, limit=1)
    except BlockedError as e:
        return _result("blocked", current, str(e))
    except TimeoutError:
        return _result("timeout", current, "Courses U n'a pas répondu à temps. Réessayez dans un instant.")
    except (AppError, ScraperError) as e:
        return _result("error", current, getattr(e, "message", None) or str(e))
    except Exception:  # noqa: BLE001 (turned into a message for the user)
        logger.exception("Automatic choice of the Courses U store failed")
        return _result("error", current, AUTO_FAILED)
    if not stores or not stores[0].url:
        return _result("none", current, "Aucun magasin Courses U trouvé.")
    nearest = stores[0]
    selection = selection_from_option(nearest, auto=True)

    def change(settings: Settings) -> None:
        now = settings.stores.get("coursesu")
        if now is None or now.auto:  # the user may have chosen one meanwhile
            settings.stores["coursesu"] = selection

    saved = await settings_service.modify(change)
    if saved.stores.get("coursesu") != selection:
        return _result("kept", saved)
    await _auto_done_for(current.location.postal_code)
    message = None
    if nearest.distance_km is not None and nearest.distance_km > FAR_KM:
        message = f"Aucun drive Courses U à moins de {FAR_KM} km."
    return _result("chosen", saved, message, nearest)


async def fetch_site_store() -> dict | None:
    """What the Courses U pages say about the store chosen there (replaced by the E2E fakes)."""
    scraper = SCRAPERS["coursesu"]
    return await browser.run(scraper.key, scraper.read_site_store, timeout=45, priority="interactive")


async def read_back_coursesu(opened_only: bool = False) -> AutoPickResult:
    """Save the store the user chose on the Courses U site (after « Ouvrir le site »).

    ``opened_only``: ``none`` at once, without reading the site, unless it was
    opened with « Ouvrir le site » since the last read-back.
    Never raises: ``none`` when the site shows no store, ``kept`` when it is
    the one already saved.
    """
    current = await settings_service.load_settings()
    scraper = SCRAPERS["coursesu"]
    if opened_only and getattr(scraper, "site_opened_at", None) is None:
        return _result("none", current)
    scraper.site_opened_at = None
    try:
        info = await fetch_site_store()
    except BlockedError as e:
        return _result("blocked", current, str(e))
    except TimeoutError:
        return _result("timeout", current, "Courses U n'a pas répondu à temps.")
    except Exception as e:  # noqa: BLE001 (best effort: the user can still choose in the list)
        logger.info("Courses U store read-back failed: %s", e)
        return _result("error", current, "Impossible de lire le magasin choisi sur le site.")
    directory = await cached_coursesu_directory()
    selection = site_store_selection(info, directory)
    if selection is None or not selection.url:
        return _result("none", current)
    chosen = current.stores.get("coursesu")
    if chosen and chosen.url == selection.url:
        return _result("kept", current)
    known = next((s for s in directory if s.url == selection.url), None)
    if known is not None:
        selection = selection_from_option(known)
    saved = await settings_service.set_store("coursesu", selection)
    option = known or StoreOption(
        id=selection.id or "", name=selection.name or "", url=selection.url, address=selection.address
    )
    return _result("chosen", saved, store=option)
