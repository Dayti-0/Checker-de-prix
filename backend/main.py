import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import config, database
from backend.browser import BrowserUnavailable, browser
from backend.models import (
    BasketComparison,
    BasketRequest,
    BrowserSetupRequest,
    BrowserStatus,
    ListItem,
    ListItemCreate,
    ListItemUpdate,
    LocationRequest,
    LocationResponse,
    RetailerInfo,
    SearchResponse,
    Settings,
    SettingsUpdate,
    StoreOption,
    StoreResult,
    StoreSelection,
)
from backend.scrapers import SCRAPERS
from backend.scrapers.base import ScraperError
from backend.scrapers.coursesu import is_store_url, store_name_from_url
from backend.services import basket, settings as settings_service
from backend.services.search import search_all, search_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("prixmalin")


@asynccontextmanager
async def lifespan(app: FastAPI):
    current = await settings_service.load_settings()
    browser.show_browser = current.show_browser
    warmup = None
    if os.environ.get("PRIXMALIN_WARMUP", "1") != "0":
        # Open the sites queried through their API so that the first search is fast
        warmup = asyncio.create_task(
            browser.warmup({k: SCRAPERS[k].home_url for k in ("carrefour", "intermarche", "lidl")})
        )
    yield
    if warmup:
        warmup.cancel()
    await browser.shutdown()
    await database.close_db()


app = FastAPI(title="PrixMalin", version="2.0.0", lifespan=lifespan)


def _scraper(key: str):
    if key not in SCRAPERS:
        raise HTTPException(404, f"Enseigne inconnue : {key}")
    return SCRAPERS[key]


# --- Search ---


@app.get("/api/search", response_model=SearchResponse)
async def api_search(
    q: str = Query(..., min_length=1, max_length=120),
    stores: str | None = Query(None, description="Enseignes séparées par des virgules"),
    refresh: bool = False,
):
    keys = [s.strip() for s in stores.split(",") if s.strip()] if stores else None
    return await search_all(q.strip(), keys, refresh)


@app.get("/api/search/{store}", response_model=StoreResult)
async def api_search_store(store: str, q: str = Query(..., min_length=1, max_length=120), refresh: bool = False):
    _scraper(store)
    return await search_store(store, q.strip(), refresh)


# --- Retailers and stores ---


@app.get("/api/retailers", response_model=list[RetailerInfo])
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


@app.get("/api/retailers/intermarche/stores", response_model=list[StoreOption])
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
    except asyncio.TimeoutError:
        raise HTTPException(504, "Intermarché n'a pas répondu à temps.")
    except Exception as e:
        logger.exception("Intermarché store search failed")
        raise HTTPException(502, f"Recherche des magasins impossible : {str(e).splitlines()[0][:200]}")


@app.put("/api/retailers/{key}/store", response_model=Settings)
async def api_set_store(key: str, selection: StoreSelection):
    scraper = _scraper(key)
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


@app.delete("/api/retailers/{key}/store", response_model=Settings)
async def api_remove_store(key: str):
    _scraper(key)
    return await settings_service.remove_store(key)


# --- Settings ---


@app.get("/api/settings", response_model=Settings)
async def api_get_settings():
    return await settings_service.load_settings()


@app.patch("/api/settings", response_model=Settings)
async def api_update_settings(update: SettingsUpdate):
    current = await settings_service.load_settings()
    if update.show_browser is not None:
        current = await settings_service.set_show_browser(update.show_browser)
        try:
            await browser.set_show_browser(update.show_browser)
        except BrowserUnavailable as e:
            raise HTTPException(502, str(e))
    return current


@app.post("/api/settings/location", response_model=LocationResponse)
async def api_set_location(request: LocationRequest):
    return await settings_service.set_location(request)


# --- Browser (manual actions on the retailer sites) ---


@app.get("/api/browser", response_model=BrowserStatus)
async def api_browser_status():
    return browser.status()


@app.post("/api/browser/setup", response_model=BrowserStatus)
async def api_browser_setup(request: BrowserSetupRequest):
    current = await settings_service.load_settings()
    if request.store:
        scraper = _scraper(request.store)
        url = scraper.setup_url(current.stores.get(scraper.key))
    else:
        url = "about:blank"
    try:
        await browser.open_setup(request.store, url)
    except BrowserUnavailable as e:
        raise HTTPException(502, str(e))
    except Exception as e:
        raise HTTPException(502, f"Impossible d'ouvrir le site : {str(e).splitlines()[0][:200]}")
    return browser.status()


@app.post("/api/browser/setup/done", response_model=BrowserStatus)
async def api_browser_setup_done():
    try:
        await browser.end_setup()
    except BrowserUnavailable as e:
        raise HTTPException(502, str(e))
    # The store or the session may have changed on the sites: forget old results
    await database.clear_cache()
    return browser.status()


# --- Shopping list ---


@app.get("/api/list", response_model=list[ListItem])
async def api_list():
    return await basket.get_list()


@app.post("/api/list", response_model=ListItem)
async def api_list_add(item: ListItemCreate):
    return await basket.add_item(item)


@app.patch("/api/list/{item_id}", response_model=ListItem)
async def api_list_update(item_id: int, update: ListItemUpdate):
    item = await basket.update_item(item_id, update)
    if item is None:
        raise HTTPException(404, "Article introuvable")
    return item


@app.delete("/api/list/{item_id}", status_code=204)
async def api_list_delete(item_id: int):
    await database.delete_item(item_id)


@app.delete("/api/list", status_code=204)
async def api_list_clear():
    await database.clear_items()


@app.post("/api/basket/compare", response_model=BasketComparison)
async def api_basket_compare(request: BasketRequest):
    return await basket.compare_basket(request.stores, request.refresh)


# --- Frontend ---


@app.get("/")
async def index():
    return FileResponse(config.FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


app.mount("/static", StaticFiles(directory=str(config.FRONTEND_DIR)), name="static")


def run() -> None:
    # No auto-reload: it would start a second browser and breaks Playwright on Windows
    print(f"\n  PrixMalin : http://localhost:{config.PORT}\n")
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    run()
