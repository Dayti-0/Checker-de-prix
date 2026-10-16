"""Stores near the user: Courses U (area of P4) and E.Leclerc (P8) ranked by distance.

- ``nearest_coursesu_stores(location)``: the directory (read in the Courses U
  tab, cached ``DIRECTORY_TTL``), placed on the map with the table of French
  towns (geo.api.gouv.fr, cached ``COMMUNES_TTL``), sorted by distance;
- ``nearest_leclerc_stores(location)``: the store finder of E.Leclerc
  (``MapPoint/nearby``, asked in its dedicated window, cached ``DIRECTORY_TTL``
  per postal code and coordinates), sorted by distance;
- ``auto_pick(key)`` (``auto_pick_coursesu``, ``auto_pick_leclerc``): saves the
  nearest store when none is chosen (or when the current one was chosen
  automatically); ``initial=True`` (page loaded) does nothing when it was
  already done for this postal code, or when the user removed the store
  (preferences ``p4.coursesu``, ``p8.leclerc``). E.Leclerc: the nearest drive,
  never a pedestrian pick-up point;
- ``read_back(key)``: saves the store the user chose on the site.

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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from backend.browser import BrowserUnavailable, browser
from backend.errors import AppError
from backend.models import AutoPickPrefs, AutoPickResult, Location, Settings, StoreOption, StoreSelection
from backend.repos import stores_cache
from backend.scrapers import SCRAPERS, leclerc
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

# Preferences of the automatic choice (AutoPickPrefs)
PREFS_SECTION = "p4.coursesu"
LECLERC_PREFS_SECTION = "p8.leclerc"

COMMUNES_KEY = "geo:communes"
DIRECTORY_KEY = "coursesu:directory"
# Last directory read, whatever its size (names and addresses of the store read back from the site)
DIRECTORY_LAST_KEY = "coursesu:directory:last"
POSTAL_KEY = "geo:cp:{}"
# E.Leclerc drives near a postal code and its coordinates; the last list read
# (names and addresses of the drive read back from the site)
LECLERC_NEARBY_KEY = "leclerc:nearby:{cp}:{where}"
LECLERC_LAST_KEY = "leclerc:nearby:last"
# Seconds left to the E.Leclerc window to ask its store finder (it may have to start)
LECLERC_TIMEOUT = 60

NO_LOCATION = "Indiquez d'abord votre code postal."
NO_LOCATION_AUTO = "Indiquez votre code postal : PrixMalin choisira le magasin le plus proche."
AUTO_FAILED = (
    "La recherche du magasin Courses U le plus proche a échoué. "
    "Choisissez-le dans la liste, sur le site ou en collant l'adresse de sa page."
)
LECLERC_AUTO_FAILED = (
    "La recherche du drive E.Leclerc le plus proche a échoué. "
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


# Departments (code -> name), for the locations saved without them (before P4):
# the name gives the page of the department (/drive-herault)
DEPARTMENTS = {
    **dict(
        zip(
            [f"{n:02d}" for n in range(1, 20)],
            "Ain|Aisne|Allier|Alpes-de-Haute-Provence|Hautes-Alpes|Alpes-Maritimes|Ardèche|Ardennes|Ariège|"
            "Aube|Aude|Aveyron|Bouches-du-Rhône|Calvados|Cantal|Charente|Charente-Maritime|Cher|Corrèze".split("|"),
            strict=True,
        )
    ),
    "2A": "Corse-du-Sud",
    "2B": "Haute-Corse",
    **dict(
        zip(
            [str(n) for n in range(21, 96)],
            "Côte-d'Or|Côtes-d'Armor|Creuse|Dordogne|Doubs|Drôme|Eure|Eure-et-Loir|Finistère|Gard|"
            "Haute-Garonne|Gers|Gironde|Hérault|Ille-et-Vilaine|Indre|Indre-et-Loire|Isère|Jura|Landes|"
            "Loir-et-Cher|Loire|Haute-Loire|Loire-Atlantique|Loiret|Lot|Lot-et-Garonne|Lozère|Maine-et-Loire|"
            "Manche|Marne|Haute-Marne|Mayenne|Meurthe-et-Moselle|Meuse|Morbihan|Moselle|Nièvre|Nord|Oise|Orne|"
            "Pas-de-Calais|Puy-de-Dôme|Pyrénées-Atlantiques|Hautes-Pyrénées|Pyrénées-Orientales|Bas-Rhin|"
            "Haut-Rhin|Rhône|Haute-Saône|Saône-et-Loire|Sarthe|Savoie|Haute-Savoie|Paris|Seine-Maritime|"
            "Seine-et-Marne|Yvelines|Deux-Sèvres|Somme|Tarn|Tarn-et-Garonne|Var|Vaucluse|Vendée|Vienne|"
            "Haute-Vienne|Vosges|Yonne|Territoire de Belfort|Essonne|Hauts-de-Seine|Seine-Saint-Denis|"
            "Val-de-Marne|Val-d'Oise".split("|"),
            strict=True,
        )
    ),
    "971": "Guadeloupe",
    "972": "Martinique",
    "973": "Guyane",
    "974": "La Réunion",
    "976": "Mayotte",
}


def department_name_of(location: Location | None) -> str | None:
    """Name of the department of ``location``: saved with it, else from its postal code."""
    if location is None:
        return None
    if location.department_name:
        return location.department_name
    code = location.department_code or department_of(location.postal_code)
    if code == "20":  # Corse: 200xx-201xx Corse-du-Sud, 202xx-206xx Haute-Corse
        code = "2A" if (location.postal_code or "")[:3] in ("200", "201") else "2B"
    return DEPARTMENTS.get(code)


def town_index(index: dict[str, list[list]] | None) -> dict[tuple[str, str], tuple]:
    """(department, normalised town) -> coordinates, for the postal codes missing
    from ``index`` (CEDEX codes: « 34092 Montpellier Cedex 5 »)."""
    towns: dict[tuple[str, str], tuple] = {}
    for postal_code, entries in (index or {}).items():
        for name, lat, lon in entries:
            towns.setdefault((department_of(postal_code), name), (lat, lon))
    return towns


def rank_stores(
    stores: list[StoreOption], origin: Location | None, index: dict[str, list[list]] | None
) -> list[StoreOption]:
    """Stores with their distance from ``origin``, the nearest first.

    A store whose postal code is not in ``index`` (CEDEX) is placed by its town.
    Stores that cannot be placed come after, those of the same postal code
    first, then those of the same department.
    """
    ranked = []
    towns: dict | None = None
    for store in stores:
        coords = (store.lat, store.lon) if store.lat is not None and store.lon is not None else None
        coords = coords or locate(store.postal_code, store.city, index)
        if coords is None and store.postal_code and store.city and index:
            if towns is None:
                towns = town_index(index)
            coords = towns.get((department_of(store.postal_code), normalize_town(store.city)))
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
    stores = await coursesu_directory(department_name_of(location), refresh)
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


# ---------------------------------------------------------------- E.Leclerc drives (P8)


async def fetch_leclerc_nearby(location: Location) -> list[StoreOption]:
    """Drives near ``location`` from the store finder of E.Leclerc, called in its
    dedicated window (replaced by the E2E fakes)."""
    scraper = SCRAPERS["leclerc"]
    return await browser.run(
        scraper.key,
        scraper.find_stores,
        location.lat,
        location.lon,
        location.postal_code,
        timeout=LECLERC_TIMEOUT,
        priority="interactive",
    )


def leclerc_cache_key(location: Location) -> str:
    """``leclerc:nearby:34000:43.611:3.877`` (``…:-:-`` without coordinates)."""
    if location.lat is None or location.lon is None:
        return LECLERC_NEARBY_KEY.format(cp=location.postal_code, where="-:-")
    return LECLERC_NEARBY_KEY.format(cp=location.postal_code, where=f"{location.lat:.3f}:{location.lon:.3f}")


def rank_leclerc_stores(stores: list[StoreOption], origin: Location | None) -> list[StoreOption]:
    """Drives sorted by distance (pure): computed from their coordinates, else the one given by the site."""
    given = {(s.id, s.url): s.distance_km for s in stores}
    ranked = [
        s if s.distance_km is not None else s.model_copy(update={"distance_km": given.get((s.id, s.url))})
        for s in rank_stores(stores, origin, None)
    ]
    return sorted(ranked, key=lambda s: (s.distance_km is None, s.distance_km or 0.0))


async def leclerc_stores(location: Location, refresh: bool = False) -> list[StoreOption]:
    """Drives near ``location`` (cached ``DIRECTORY_TTL`` per postal code and coordinates)."""
    key = leclerc_cache_key(location)
    async with _lock("leclerc-nearby"):
        if not refresh:
            cached = await stores_cache.get(key, DIRECTORY_TTL)
            if cached:
                return [StoreOption(**s) for s in json.loads(cached[0])]
        found = await fetch_leclerc_nearby(location)
        stores = [s if isinstance(s, StoreOption) else StoreOption(**s) for s in found or []]
        if stores:
            dump = json.dumps([s.model_dump() for s in stores])
            await stores_cache.put(key, dump)
            await stores_cache.put(LECLERC_LAST_KEY, dump)
        return stores


async def nearest_leclerc_stores(
    location: Location | None, refresh: bool = False, limit: int = NEAREST_COUNT
) -> list[StoreOption]:
    """The ``limit`` E.Leclerc drives (and pedestrian pick-up points) nearest to ``location``."""
    if location is None:
        raise AppError(NO_LOCATION, 400, "no_location")
    return rank_leclerc_stores(await leclerc_stores(location, refresh), location)[:limit]


async def cached_leclerc_stores() -> list[StoreOption]:
    """The drives of the last list read, without asking the site."""
    cached = await stores_cache.get(LECLERC_LAST_KEY)
    return [StoreOption(**s) for s in json.loads(cached[0])] if cached else []


async def fetch_leclerc_site_store() -> dict | None:
    """What the tab of the E.Leclerc window shows (address, page, cookie), read
    without any request to the site (replaced by the E2E fakes)."""
    scraper = SCRAPERS["leclerc"]
    return await browser.run(scraper.key, scraper.read_site_store, timeout=45, priority="interactive")


def first_drive(stores: list[StoreOption]) -> StoreOption | None:
    """The nearest drive of a list sorted by distance (never a pedestrian pick-up point)."""
    return next((s for s in stores if "Drive" in s.services and s.url), None)


# ---------------------------------------------------------------- automatic choice


@dataclass(frozen=True)
class AutoPickSpec:
    """A retailer whose store PrixMalin chooses by itself (Courses U, E.Leclerc)."""

    key: str
    label: str
    # Preferences of the automatic choice (AutoPickPrefs)
    prefs_section: str
    # (location, refresh, limit) -> stores sorted by distance
    nearest: Callable[[Location, bool, int], Awaitable[list[StoreOption]]]
    # The store chosen in a sorted list
    pick: Callable[[list[StoreOption]], StoreOption | None]
    # () -> (store chosen on the site or None, the stores already known)
    site_store: Callable[[], Awaitable[tuple[StoreSelection | None, list[StoreOption]]]]
    none_message: str
    far_message: str
    timeout_message: str
    failed_message: str
    read_timeout_message: str


async def _coursesu_site_store() -> tuple[StoreSelection | None, list[StoreOption]]:
    info = await fetch_site_store()
    directory = await cached_coursesu_directory()
    return site_store_selection(info, directory), directory


async def _leclerc_site_store() -> tuple[StoreSelection | None, list[StoreOption]]:
    info = await fetch_leclerc_site_store() or {}
    known = await cached_leclerc_stores()
    selection = leclerc.site_store_selection(info.get("url"), info.get("html"), info.get("cookie"), known)
    return selection, known


SPECS = {
    "coursesu": AutoPickSpec(
        key="coursesu",
        label="Courses U",
        prefs_section=PREFS_SECTION,
        nearest=lambda location, refresh, limit: nearest_coursesu_stores(location, refresh=refresh, limit=limit),
        pick=lambda stores: stores[0] if stores and stores[0].url else None,
        site_store=lambda: _coursesu_site_store(),
        none_message="Aucun magasin Courses U trouvé.",
        far_message=f"Aucun drive Courses U à moins de {FAR_KM} km.",
        timeout_message="Courses U n'a pas répondu à temps. Réessayez dans un instant.",
        failed_message=AUTO_FAILED,
        read_timeout_message="Courses U n'a pas répondu à temps.",
    ),
    "leclerc": AutoPickSpec(
        key="leclerc",
        label="E.Leclerc",
        prefs_section=LECLERC_PREFS_SECTION,
        nearest=lambda location, refresh, limit: nearest_leclerc_stores(location, refresh=refresh, limit=limit),
        pick=lambda stores: first_drive(stores),
        site_store=lambda: _leclerc_site_store(),
        none_message="Aucun drive E.Leclerc trouvé.",
        far_message=f"Aucun drive E.Leclerc à moins de {FAR_KM} km.",
        timeout_message="E.Leclerc n'a pas répondu à temps. Réessayez dans un instant.",
        failed_message=LECLERC_AUTO_FAILED,
        read_timeout_message="E.Leclerc n'a pas répondu à temps.",
    ),
}
# Retailers whose nearest store is chosen automatically (RetailerInfo.auto_store)
AUTO_STORES = tuple(SPECS)


def _spec(key: str) -> AutoPickSpec:
    return SPECS[key]


def _result(status: str, settings: Settings, message: str | None = None, store=None) -> AutoPickResult:
    return AutoPickResult(status=status, message=message, store=store, settings=settings)


async def _auto_done_for(spec: AutoPickSpec, postal_code: str | None) -> None:
    def change(p: AutoPickPrefs) -> None:
        p.auto_done_for = postal_code

    await prefs.update(spec.prefs_section, AutoPickPrefs, change)


async def forget_store(key: str) -> None:
    """The user removed his store: no automatic choice at startup for this postal code."""
    current = await settings_service.load_settings()
    if current.location is not None:
        await _auto_done_for(_spec(key), current.location.postal_code)


async def auto_pick(key: str, refresh: bool = False, initial: bool = False) -> AutoPickResult:
    """Save the nearest store of ``key`` unless the user chose one himself.

    ``initial``: asked when a page loads; ``kept`` without reading the site when
    a store is chosen or when it was already done for this postal code.
    The location changed while the stores were read (town chosen meanwhile):
    the store is chosen again for the new one.
    Never raises: the outcome (``status``, French ``message``) is returned.
    """
    spec = _spec(key)
    for _ in range(3):
        result = await _auto_pick_once(spec, refresh, initial)
        if result is not None:
            return result
        refresh = False  # the stores have just been read
    return _result("kept", await settings_service.load_settings())


async def _auto_pick_once(spec: AutoPickSpec, refresh: bool, initial: bool) -> AutoPickResult | None:
    """One automatic choice; None when the location changed meanwhile (nothing saved)."""
    current = await settings_service.load_settings()
    chosen = current.stores.get(spec.key)
    if chosen and (not chosen.auto or initial):
        return _result("kept", current)
    if current.location is None:
        return _result("no_location", current, NO_LOCATION_AUTO)
    if initial:
        done = await prefs.get(spec.prefs_section, AutoPickPrefs)
        if done.auto_done_for == current.location.postal_code:
            return _result("kept", current)
    try:
        stores = await spec.nearest(current.location, refresh, NEAREST_COUNT)
    except BlockedError as e:
        return _result("blocked", current, str(e))
    except TimeoutError:
        return _result("timeout", current, spec.timeout_message)
    except (AppError, ScraperError) as e:
        return _result("error", current, getattr(e, "message", None) or str(e))
    except BrowserUnavailable as e:
        # The dedicated Chrome window of E.Leclerc cannot start: say why
        return _result("error", current, str(e) if browser.is_dedicated(spec.key) else spec.failed_message)
    except Exception:  # noqa: BLE001 (turned into a message for the user)
        logger.exception("Automatic choice of the %s store failed", spec.label)
        return _result("error", current, spec.failed_message)
    nearest = spec.pick(stores or [])
    if nearest is None:
        return _result("none", current, spec.none_message)
    selection = selection_from_option(nearest, auto=True)

    moved = False

    def change(settings: Settings) -> None:
        nonlocal moved
        if settings.location != current.location:
            moved = True
            return
        now = settings.stores.get(spec.key)
        if now is None or now.auto:  # the user may have chosen one meanwhile
            settings.stores[spec.key] = selection

    saved = await settings_service.modify(change)
    if moved:
        return None
    if saved.stores.get(spec.key) != selection:
        return _result("kept", saved)
    await _auto_done_for(spec, current.location.postal_code)
    message = None
    if nearest.distance_km is not None and nearest.distance_km > FAR_KM:
        message = spec.far_message
    return _result("chosen", saved, message, nearest)


async def read_back(key: str, opened_only: bool = False) -> AutoPickResult:
    """Save the store the user chose on the site of ``key`` (after « Ouvrir le site »).

    ``opened_only``: ``none`` at once, without reading the site, unless it was
    opened with « Ouvrir le site » since the last read-back.
    Never raises: ``none`` when the site shows no store, ``kept`` when it is
    the one already saved.
    """
    spec = _spec(key)
    current = await settings_service.load_settings()
    scraper = SCRAPERS[spec.key]
    if opened_only and getattr(scraper, "site_opened_at", None) is None:
        return _result("none", current)
    scraper.site_opened_at = None
    try:
        selection, known_stores = await spec.site_store()
    except BlockedError as e:
        return _result("blocked", current, str(e))
    except TimeoutError:
        return _result("timeout", current, spec.read_timeout_message)
    except Exception as e:  # noqa: BLE001 (best effort: the user can still choose in the list)
        logger.info("%s store read-back failed: %s", spec.label, e)
        return _result("error", current, "Impossible de lire le magasin choisi sur le site.")
    if selection is None or not selection.url:
        return _result("none", current)
    chosen = current.stores.get(spec.key)
    if chosen and chosen.url == selection.url:
        return _result("kept", current)
    known = next((s for s in known_stores if s.url == selection.url), None)
    if known is not None:
        selection = selection_from_option(known)
    saved = await settings_service.set_store(spec.key, selection)
    option = known or StoreOption(
        id=selection.id or "", name=selection.name or "", url=selection.url, address=selection.address
    )
    return _result("chosen", saved, store=option)


# --- Courses U and E.Leclerc entry points (used by the tests and the E2E fakes)


async def forget_coursesu_store() -> None:
    await forget_store("coursesu")


async def auto_pick_coursesu(refresh: bool = False, initial: bool = False) -> AutoPickResult:
    return await auto_pick("coursesu", refresh=refresh, initial=initial)


async def fetch_site_store() -> dict | None:
    """What the Courses U pages say about the store chosen there (replaced by the E2E fakes)."""
    scraper = SCRAPERS["coursesu"]
    return await browser.run(scraper.key, scraper.read_site_store, timeout=45, priority="interactive")


async def read_back_coursesu(opened_only: bool = False) -> AutoPickResult:
    return await read_back("coursesu", opened_only=opened_only)


async def forget_leclerc_store() -> None:
    await forget_store("leclerc")


async def auto_pick_leclerc(refresh: bool = False, initial: bool = False) -> AutoPickResult:
    return await auto_pick("leclerc", refresh=refresh, initial=initial)


async def read_back_leclerc(opened_only: bool = False) -> AutoPickResult:
    return await read_back("leclerc", opened_only=opened_only)
