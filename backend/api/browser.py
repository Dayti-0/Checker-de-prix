"""Manual actions on the retailer sites in the PrixMalin browser window (area of P3)."""

from fastapi import APIRouter, Request

from backend.api.common import get_scraper
from backend.api.errors import guard
from backend.browser import browser
from backend.models import BrowserSetupRequest, BrowserStatus
from backend.repos import cache
from backend.scrapers import SCRAPERS
from backend.security import is_local_request
from backend.services import search
from backend.services import settings as settings_service

router = APIRouter()


def status_for(http_request: Request) -> BrowserStatus:
    status = browser.status()
    status.is_local = is_local_request(http_request)
    return status


@router.get("/browser", response_model=BrowserStatus)
async def api_browser_status(http_request: Request):
    await browser.flush()  # window closed by the user: saved now
    await browser.hard_blocks.load()
    return status_for(http_request)


@router.delete("/browser/blocks/{store}", response_model=BrowserStatus)
async def api_browser_unblock(store: str, http_request: Request):
    """« Réessayer maintenant »: end the pause after a hard block (the user changed connection)."""
    scraper = get_scraper(store)
    await browser.hard_blocks.lift(scraper.key)
    search.reset_circuit(scraper.key)
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


def done_targets(store: str | None) -> list[str]:
    """Retailers whose results and circuit « J'ai terminé » resets.

    The retailer shown (also when the user closed its window first); for the
    browser opened without a retailer (``_setup``), the retailers of the shared
    browser, never a dedicated window that it cannot have changed; nothing
    when nothing was shown (« J'ai terminé » pressed twice).
    """
    if store == "_setup":
        return [key for key in SCRAPERS if not browser.is_dedicated(key)]
    return [store] if store in SCRAPERS else []


@router.post("/browser/setup/done", response_model=BrowserStatus)
async def api_browser_setup_done(http_request: Request):
    shown = browser.setup_store
    for key in done_targets(await browser.end_setup() or shown):
        # The store or the session may have changed on that site: forget its
        # old results, and allow its visits again (circuit breaker)
        await cache.clear_cache(f"{key}|")
        search.reset_circuit(key)
    return status_for(http_request)
