"""Settings of the user: location and stores (area of P4)."""

from pydantic import BaseModel, Field

__all__ = [
    "Location",
    "LocationRequest",
    "LocationResponse",
    "RetailerInfo",
    "Settings",
    "SettingsUpdate",
    "StoreOption",
    "StoreSelection",
]


class Location(BaseModel):
    postal_code: str
    city: str | None = None
    lat: float | None = None
    lon: float | None = None


class StoreSelection(BaseModel):
    id: str | None = None
    name: str | None = None
    url: str | None = None
    address: str | None = None


class Settings(BaseModel):
    location: Location | None = None
    stores: dict[str, StoreSelection] = {}
    show_browser: bool = False


class LocationRequest(BaseModel):
    postal_code: str = Field(pattern=r"^\d{5}$")
    city: str | None = None


class LocationResponse(BaseModel):
    settings: Settings
    communes: list[Location] = []


class SettingsUpdate(BaseModel):
    show_browser: bool | None = None


class StoreOption(BaseModel):
    id: str
    name: str
    address: str | None = None
    distance_km: float | None = None


class RetailerInfo(BaseModel):
    key: str
    label: str
    needs_store: bool
    store_hint: str
    home_url: str
    store: StoreSelection | None = None
