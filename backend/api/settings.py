"""User settings: show the browser window, location."""

from fastapi import APIRouter, HTTPException

from backend.browser import BrowserUnavailable, browser
from backend.models import LocationRequest, LocationResponse, Settings, SettingsUpdate
from backend.services import settings as settings_service

router = APIRouter()


@router.get("/settings", response_model=Settings)
async def api_get_settings():
    return await settings_service.load_settings()


@router.patch("/settings", response_model=Settings)
async def api_update_settings(update: SettingsUpdate):
    current = await settings_service.load_settings()
    if update.show_browser is not None:
        current = await settings_service.set_show_browser(update.show_browser)
        try:
            await browser.set_show_browser(update.show_browser)
        except BrowserUnavailable as e:
            raise HTTPException(502, str(e))
    return current


@router.post("/settings/location", response_model=LocationResponse)
async def api_set_location(request: LocationRequest):
    return await settings_service.set_location(request)
