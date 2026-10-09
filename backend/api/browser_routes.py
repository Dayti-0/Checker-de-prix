"""Manual actions on the retailer sites in the PrixMalin browser window.

Named ``browser_routes`` so that it is not mistaken for ``backend/browser.py``.
"""

from fastapi import APIRouter, HTTPException

from backend import database
from backend.api.common import get_scraper
from backend.browser import BrowserUnavailable, browser
from backend.models import BrowserSetupRequest, BrowserStatus
from backend.services import settings as settings_service

router = APIRouter()


@router.get("/browser", response_model=BrowserStatus)
async def api_browser_status():
    return browser.status()


@router.post("/browser/setup", response_model=BrowserStatus)
async def api_browser_setup(request: BrowserSetupRequest):
    current = await settings_service.load_settings()
    if request.store:
        scraper = get_scraper(request.store)
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


@router.post("/browser/setup/done", response_model=BrowserStatus)
async def api_browser_setup_done():
    try:
        await browser.end_setup()
    except BrowserUnavailable as e:
        raise HTTPException(502, str(e))
    # The store or the session may have changed on the sites: forget old results
    await database.clear_cache()
    return browser.status()
