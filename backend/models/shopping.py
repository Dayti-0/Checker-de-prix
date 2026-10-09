"""Shopping list and basket comparison (area of P5)."""

from pydantic import BaseModel, Field, field_validator

from backend.models.products import Product

__all__ = [
    "BasketComparison",
    "BasketLine",
    "BasketRequest",
    "ListItem",
    "ListItemCreate",
    "ListItemUpdate",
    "StoreBasket",
]


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
