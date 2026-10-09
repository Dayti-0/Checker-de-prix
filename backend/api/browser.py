"""Manual actions on the retailer sites in the PrixMalin browser window (area of P3)."""

from fastapi import APIRouter, Request

from backend.api.common import get_scraper
from backend.api.errors import guard
from backend.browser import browser
from backend.models import BrowserSetupRequest, BrowserStatus
from backend.repos import cache
from backend.security import is_local_request
from backend.services import settings as settings_service

router = APIRouter()


def status_for(http_request: Request) -> BrowserStatus:
    status = browser.status()
    status.is_local = is_local_request(http_request)
    return status


@router.get("/browser", response_model=BrowserStatus)
async def api_browser_status(http_request: Request):
    return status_for(http_request)


@router.post("/browser/setup", response_model=BrowserStatus)
async def api_browser_setup(request: BrowserSetupRequest, http_request: Request):
    current = await settings_service.load_settings()
    if request.store:
        scraper = get_scraper(request.store)
        url = scraper.setup_url(current.stores.get(scraper.key))
    else:
        url = "about:blank"
    with guard("Impossible d'ouvrir le site"):
        await browser.open_setup(request.store, url)
    return status_for(http_request)


@router.post("/browser/setup/done", response_model=BrowserStatus)
async def api_browser_setup_done(http_request: Request):
    await browser.end_setup()
    # The store or the session may have changed on the sites: forget old results
    await cache.clear_cache()
    return status_for(http_request)
