"""Retailers and the store chosen for each of them (area of P4, E.Leclerc added by P8)."""

from fastapi import APIRouter, HTTPException

from backend.api.common import get_scraper
from backend.api.errors import guard
from backend.browser import browser
from backend.models import (
    AutoPickResult,
    RetailerInfo,
    Settings,
    StoreChoice,
    StoreOption,
    StoreSelection,
    valid_store_id,
)
from backend.scrapers import SCRAPERS, leclerc
from backend.scrapers.coursesu import is_store_url, store_name_from_url, store_url_from_href
from backend.services import settings as settings_service
from backend.services import stores as stores_service

router = APIRouter()

# Same prices everywhere in France
NATIONAL = {"aldi", "lidl"}
# PrixMalin lists the stores near the user
FINDS_STORES = {"intermarche", "coursesu", "leclerc"}
# PrixMalin chooses the nearest store by itself, and reads back the one chosen on the site
AUTO_STORES = set(stores_service.AUTO_STORES)
# Example of the field « collez l'adresse de sa page »
STORE_URL_EXAMPLES = {
    "coursesu": "https://www.coursesu.com/drive-superu-roujan",
    "leclerc": leclerc.STORE_URL_EXAMPLE,
}

COURSESU_URL_HINT = "Adresse invalide. Exemple : https://www.coursesu.com/drive-superu-roujan"
NO_AUTO_STORE = "PrixMalin ne choisit pas lui-même le magasin de cette enseigne."
TIMEOUT_MESSAGES = {
    "coursesu": "Courses U n'a pas répondu à temps.",
    "leclerc": "E.Leclerc n'a pas répondu à temps.",
}


def _auto_store_key(key: str) -> str:
    """404 (French message) for an unknown retailer or one whose store is not chosen automatically."""
    get_scraper(key)
    if key not in AUTO_STORES:
        raise HTTPException(404, NO_AUTO_STORE)
    return key


@router.get("/retailers", response_model=list[RetailerInfo])
async def api_retailers():
    current = await settings_service.load_settings()
    return [
        RetailerInfo(
            key=s.key,
            label=s.label,
            needs_store=s.needs_store,
            store_hint=s.store_hint,
            home_url=s.home_url,
            store=current.stores.get(s.key),
            national=s.key in NATIONAL,
            finds_stores=s.key in FINDS_STORES,
            auto_store=s.key in AUTO_STORES,
            store_url_example=STORE_URL_EXAMPLES.get(s.key),
        )
        for s in SCRAPERS.values()
    ]


# Declared before the generic route below
@router.get("/retailers/intermarche/stores", response_model=list[StoreOption])
async def api_intermarche_stores():
    current = await settings_service.load_settings()
    location = current.location
    if location is None or location.lat is None:
        raise HTTPException(400, "Indiquez d'abord votre code postal.")
    scraper = SCRAPERS["intermarche"]
    with guard("Recherche des magasins impossible", timeout_message="Intermarché n'a pas répondu à temps."):
        return await browser.run(
            scraper.key, scraper.find_stores, location.lat, location.lon, timeout=45, priority="interactive"
        )


@router.get("/retailers/{key}/stores", response_model=list[StoreOption])
async def api_nearest_stores(key: str, refresh: bool = False):
    """The 8 stores (Courses U) or drives (E.Leclerc) nearest to the saved postal code (400 without one)."""
    _auto_store_key(key)
    current = await settings_service.load_settings()
    nearest = stores_service.nearest_leclerc_stores if key == "leclerc" else stores_service.nearest_coursesu_stores
    with guard("Recherche des magasins impossible", timeout_message=TIMEOUT_MESSAGES[key]):
        return await nearest(current.location, refresh=refresh)


@router.post("/retailers/{key}/store/auto", response_model=AutoPickResult)
async def api_auto_store(key: str, refresh: bool = False, initial: bool = False):
    """Choose the nearest store (Courses U) or drive (E.Leclerc) unless the user chose one (always 200).

    ``initial=true`` (page loaded): only once per postal code.
    """
    # The functions of each retailer, looked up at each call (replaced by some tests)
    pick = stores_service.auto_pick_leclerc if _auto_store_key(key) == "leclerc" else stores_service.auto_pick_coursesu
    return await pick(refresh=refresh, initial=initial)


@router.post("/retailers/{key}/store/from-site", response_model=AutoPickResult)
async def api_store_from_site(key: str, opened_only: bool = False):
    """Save the store chosen by the user on the site (always 200).

    ``opened_only=true``: only when the site was opened with « Ouvrir le site ».
    """
    read = stores_service.read_back_leclerc if _auto_store_key(key) == "leclerc" else stores_service.read_back_coursesu
    return await read(opened_only=opened_only)


def _coursesu_selection(choice: StoreChoice) -> StoreSelection:
    raw = (choice.url or "").strip()
    # Page of a drive: query string (?utm_…) and fragment dropped, slug in lower case
    url = store_url_from_href(raw) or raw.rstrip("/")
    if not url or not is_store_url(url):
        raise HTTPException(400, COURSESU_URL_HINT)
    return StoreSelection(
        id=choice.id,
        name=choice.name or store_name_from_url(url),
        url=url,
        address=choice.address,
        distance_km=choice.distance_km,
    )


def _leclerc_selection(choice: StoreChoice) -> StoreSelection:
    """Address of any page of the drive (``leclerc.parse_store_url``), kept without « .aspx »."""
    ref = leclerc.parse_store_url(choice.url)
    if ref is None:
        raise HTTPException(400, leclerc.URL_HINT)
    if choice.id is not None and choice.id != ref.no_pl:
        raise HTTPException(422, "Identifiant de magasin invalide.")
    return StoreSelection(
        id=ref.no_pl,
        name=leclerc.store_name_of(ref, choice.name),
        url=ref.base,
        address=choice.address,
        distance_km=choice.distance_km,
    )


@router.put("/retailers/{key}/store", response_model=Settings)
async def api_set_store(key: str, choice: StoreChoice):
    scraper = get_scraper(key)
    if key in ("coursesu", "intermarche", "leclerc") and choice.id is not None and not valid_store_id(choice.id):
        raise HTTPException(422, "Identifiant de magasin invalide.")
    if key == "coursesu":
        selection = _coursesu_selection(choice)
    elif key == "leclerc":
        selection = _leclerc_selection(choice)
    elif key == "intermarche":
        if not choice.id:
            raise HTTPException(400, "Magasin manquant.")
        selection = StoreSelection(
            id=choice.id, name=choice.name, address=choice.address, distance_km=choice.distance_km
        )
    else:
        raise HTTPException(400, f"{scraper.label} ne nécessite pas de choisir un magasin ici.")
    return await settings_service.set_store(key, selection)


@router.delete("/retailers/{key}/store", response_model=Settings)
async def api_remove_store(key: str):
    get_scraper(key)
    if key in AUTO_STORES:
        await stores_service.forget_store(key)
    return await settings_service.remove_store(key)
