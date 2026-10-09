"""A product found at a retailer (area of P2)."""

from urllib.parse import urlsplit

from pydantic import BaseModel, field_validator

__all__ = ["LABEL_MAX", "NAME_MAX", "PROMO_MAX", "Product", "web_url"]

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
    # Contract fields (filled by the scrapers that know them): barcode and
    # identifier of the product on the retailer site
    ean: str | None = None
    sku: str | None = None

    @field_validator("name", "brand", mode="before")
    @classmethod
    def _cut_name(cls, value: object) -> object:
        return _cut(value, NAME_MAX)

    @field_validator("unit", "unit_price_label", "quantity_label", "ean", "sku", mode="before")
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
