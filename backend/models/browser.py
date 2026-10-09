"""State of the PrixMalin browser (area of P3)."""

from pydantic import BaseModel

__all__ = ["BrowserSetupRequest", "BrowserStatus"]


class BrowserStatus(BaseModel):
    running: bool
    headless: bool
    setup_mode: bool
    channel: str | None = None
    error: str | None = None
    # Contract field: the request comes from the PC itself (the browser window
    # can only be seen there), computed by the API from request.client
    is_local: bool = False


class BrowserSetupRequest(BaseModel):
    store: str | None = None
