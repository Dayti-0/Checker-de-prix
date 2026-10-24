"""User settings: show the browser window, location, first-launch assistant (area of P4)."""

from fastapi import APIRouter

from backend.browser import browser
from backend.models import (
    LocationRequest,
    LocationResponse,
    OnboardingStatus,
    OnboardingUpdate,
    Settings,
    SettingsUpdate,
)
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
        # BrowserUnavailable: 502 (backend/api/errors.py)
        await browser.set_show_browser(update.show_browser)
    return current


@router.post("/settings/location", response_model=LocationResponse)
async def api_set_location(request: LocationRequest):
    """Unknown postal code: 422 « Code postal inconnu… » (nothing saved)."""
    return await settings_service.set_location(request)


@router.get("/settings/onboarding", response_model=OnboardingStatus)
async def api_onboarding():
    return await settings_service.onboarding_status()


@router.patch("/settings/onboarding", response_model=OnboardingStatus)
async def api_update_onboarding(update: OnboardingUpdate):
    return await settings_service.update_onboarding(update)
