from pydantic import BaseModel


class ScrapedProduct(BaseModel):
    name: str
    price: float | None = None
    price_per_unit: str | None = None
    image_url: str | None = None
    product_url: str
    store_name: str


class SearchResponse(BaseModel):
    query: str
    results: list[ScrapedProduct]
    errors: list[str] = []


class LocationConfig(BaseModel):
    postal_code: str


class StoreConfig(BaseModel):
    store_id: str
    store_name: str


class AppConfig(BaseModel):
    postal_code: str | None = None
    stores: dict[str, StoreConfig] = {}
