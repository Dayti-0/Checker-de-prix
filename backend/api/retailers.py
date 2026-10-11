"""Retailers and the store chosen for each of them (area of P4)."""

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
from backend.scrapers import SCRAPERS
from backend.scrapers.coursesu import is_store_url, store_name_from_url
from backend.services import settings as settings_service
from backend.services import stores as stores_service

router = APIRouter()

# Same prices everywhere in France
NATIONAL = {"aldi", "lidl"}
# PrixMalin lists the stores near the user
FINDS_STORES = {"intermarche", "coursesu"}

COURSESU_URL_HINT = "Adresse invalide. Exemple : https://www.coursesu.com/drive-superu-roujan"


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
        )
        for s in SCRAPERS.values()
    ]


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


@router.get("/retailers/coursesu/stores", response_model=list[StoreOption])
async def api_coursesu_stores(refresh: bool = False):
    """The 8 Courses U stores nearest to the saved postal code (400 without one)."""
    current = await settings_service.load_settings()
    with guard("Recherche des magasins impossible", timeout_message="Courses U n'a pas répondu à temps."):
        return await stores_service.nearest_coursesu_stores(current.location, refresh=refresh)


@router.post("/retailers/coursesu/store/auto", response_model=AutoPickResult)
async def api_coursesu_auto(refresh: bool = False, initial: bool = False):
    """Choose the nearest Courses U store unless the user chose one (always 200).

    ``initial=true`` (page loaded): only once per postal code.
    """
    return await stores_service.auto_pick_coursesu(refresh=refresh, initial=initial)


@router.post("/retailers/coursesu/store/from-site", response_model=AutoPickResult)
async def api_coursesu_from_site(opened_only: bool = False):
    """Save the store chosen by the user on the Courses U site (always 200).

    ``opened_only=true``: only when the site was opened with « Ouvrir le site ».
    """
    return await stores_service.read_back_coursesu(opened_only=opened_only)


@router.put("/retailers/{key}/store", response_model=Settings)
async def api_set_store(key: str, choice: StoreChoice):
    scraper = get_scraper(key)
    if key in ("coursesu", "intermarche") and choice.id is not None and not valid_store_id(choice.id):
        raise HTTPException(422, "Identifiant de magasin invalide.")
    if key == "coursesu":
        url = (choice.url or "").rstrip("/")
        if not url or not is_store_url(url):
            raise HTTPException(400, COURSESU_URL_HINT)
        selection = StoreSelection(
            id=choice.id,
            name=choice.name or store_name_from_url(url),
            url=url,
            address=choice.address,
            distance_km=choice.distance_km,
        )
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
    if key == "coursesu":
        await stores_service.forget_coursesu_store()
    return await settings_service.remove_store(key)
