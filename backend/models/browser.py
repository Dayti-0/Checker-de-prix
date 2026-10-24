"""State of the PrixMalin browser (area of P3)."""

from pydantic import BaseModel

__all__ = ["BrowserSetupRequest", "BrowserStatus", "RetailerWindow"]


class RetailerWindow(BaseModel):
    """Dedicated Chrome window of a retailer protected by DataDome (Intermarché)."""

    store: str
    label: str
    running: bool = False
    # "Google Chrome", "Microsoft Edge" (known once started)
    browser: str | None = None
    # French message when the window cannot be used (no Chrome installed...)
    error: str | None = None
    # The user closed the window: it opens again (minimized) at the next search
    closed_by_user: bool = False


class BrowserStatus(BaseModel):
    running: bool
    headless: bool
    setup_mode: bool
    channel: str | None = None
    error: str | None = None
    # Contract field: the request comes from the PC itself (the browser window
    # can only be seen there), computed by the API from request.client
    is_local: bool = False
    # The user closed the visible window: PrixMalin went back to the invisible browser
    closed_by_user: bool = False
    # Retailer opened with « Ouvrir le site » while setup_mode is true
    setup_store: str | None = None
    # Dedicated windows (Intermarché)
    windows: list[RetailerWindow] = []
    # Retailers paused after a hard block: {key: Unix time of the next allowed call}
    blocked_until: dict[str, float] = {}


class BrowserSetupRequest(BaseModel):
    store: str | None = None
