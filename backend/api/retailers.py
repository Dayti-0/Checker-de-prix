"""Retailers and the store chosen for each of them."""

from fastapi import APIRouter, HTTPException

from backend.api.common import get_scraper, logger
from backend.browser import BrowserUnavailable, browser
from backend.models import RetailerInfo, Settings, StoreOption, StoreSelection
from backend.scrapers import SCRAPERS
from backend.scrapers.base import ScraperError
from backend.scrapers.coursesu import is_store_url, store_name_from_url
from backend.services import settings as settings_service

router = APIRouter()


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
    try:
        return await browser.run(scraper.key, scraper.find_stores, location.lat, location.lon, timeout=45)
    except (ScraperError, BrowserUnavailable) as e:
        raise HTTPException(502, str(e))
    except TimeoutError:
        raise HTTPException(504, "Intermarché n'a pas répondu à temps.")
    except Exception as e:
        logger.exception("Intermarché store search failed")
        raise HTTPException(502, f"Recherche des magasins impossible : {str(e).splitlines()[0][:200]}")


@router.put("/retailers/{key}/store", response_model=Settings)
async def api_set_store(key: str, selection: StoreSelection):
    scraper = get_scraper(key)
    if key == "coursesu":
        if not selection.url or not is_store_url(selection.url):
            raise HTTPException(400, "Adresse invalide. Exemple : https://www.coursesu.com/drive-superu-roujan")
        selection.url = selection.url.strip().rstrip("/")
        selection.name = selection.name or store_name_from_url(selection.url)
    elif key == "intermarche":
        if not selection.id:
            raise HTTPException(400, "Magasin manquant.")
    else:
        raise HTTPException(400, f"{scraper.label} ne nécessite pas de choisir un magasin ici.")
    return await settings_service.set_store(key, selection)


@router.delete("/retailers/{key}/store", response_model=Settings)
async def api_remove_store(key: str):
    get_scraper(key)
    return await settings_service.remove_store(key)
