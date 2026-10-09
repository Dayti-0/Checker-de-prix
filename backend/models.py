from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

SearchStatus = Literal["ok", "empty", "store_required", "blocked", "timeout", "error"]

# Longest texts kept in a product: longer ones are cut, never rejected, so that
# an odd product never makes a whole search fail
NAME_MAX = 300
LABEL_MAX = 100
PROMO_MAX = 200


def _cut(value: object, limit: int) -> object:
    return value[:limit] if isinstance(value, str) and len(value) > limit else value


def web_url(value: object) -> str | None:
    """``value`` when it is an http(s) address, else None (no javascript:, data:...)."""
    if not isinstance(value, str):
        return None
    url = value.strip()
    if url.startswith("//"):
        url = "https:" + url
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    return url if parts.scheme.lower() in ("http", "https") and parts.netloc else None


class Product(BaseModel):
    store: str
    name: str
    brand: str | None = None
    price: float | None = None
    # Normalised price per unit (€/kg, €/L or €/unité) when it can be determined
    unit_price: float | None = None
    unit: str | None = None
    unit_price_label: str | None = None
    quantity_label: str | None = None
    image_url: str | None = None
    product_url: str = ""
    promo: str | None = None
    available: bool = True
    # 1.0 = every keyword of the query is in the product name
    relevance: float = 1.0

    @field_validator("name", "brand", mode="before")
    @classmethod
    def _cut_name(cls, value: object) -> object:
        return _cut(value, NAME_MAX)

    @field_validator("unit", "unit_price_label", "quantity_label", mode="before")
    @classmethod
    def _cut_label(cls, value: object) -> object:
        return _cut(value, LABEL_MAX)

    @field_validator("promo", mode="before")
    @classmethod
    def _cut_promo(cls, value: object) -> object:
        return _cut(value, PROMO_MAX)

    @field_validator("product_url", mode="before")
    @classmethod
    def _product_url(cls, value: object) -> object:
        if value is None or isinstance(value, str):
            return web_url(value) or ""
        return value

    @field_validator("image_url", mode="before")
    @classmethod
    def _image_url(cls, value: object) -> object:
        if value is None or isinstance(value, str):
            return web_url(value)
        return value


class StoreResult(BaseModel):
    store: str
    label: str
    status: SearchStatus
    message: str | None = None
    products: list[Product] = []
    cached: bool = False
    store_label: str | None = None
    elapsed_ms: int = 0


class SearchResponse(BaseModel):
    query: str
    results: list[StoreResult]


# --- Settings ---


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


# --- Browser ---


class BrowserStatus(BaseModel):
    running: bool
    headless: bool
    setup_mode: bool
    channel: str | None = None
    error: str | None = None


class BrowserSetupRequest(BaseModel):
    store: str | None = None


# --- Shopping list / basket ---


class ListItem(BaseModel):
    id: int
    query: str
    quantity: int = 1
    picks: dict[str, Product] = {}


class ListItemCreate(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    quantity: int = Field(default=1, ge=1, le=99)
    product: Product | None = None

    @field_validator("product")
    @classmethod
    def _known_retailer(cls, product: Product | None) -> Product | None:
        from backend.scrapers import SCRAPERS  # the scrapers import the models

        if product is not None and product.store not in SCRAPERS:
            raise ValueError("enseigne inconnue")
        return product


class ListItemUpdate(BaseModel):
    quantity: int | None = Field(default=None, ge=1, le=99)
    remove_pick: str | None = None


class BasketRequest(BaseModel):
    stores: list[str] | None = None
    refresh: bool = False


class BasketLine(BaseModel):
    item_id: int
    query: str
    quantity: int
    product: Product | None = None
    line_total: float | None = None
    picked: bool = False


class StoreBasket(BaseModel):
    store: str
    label: str
    total: float = 0.0
    missing: int = 0
    lines: list[BasketLine] = []
    message: str | None = None


class BasketComparison(BaseModel):
    stores: list[StoreBasket]
    best_store: str | None = None
    # Cheapest total when each item is bought at the cheapest retailer
    split_total: float | None = None
    split_missing: int = 0
