"""Result of a search at one retailer, or at all of them (area of P3)."""

from typing import Literal

from pydantic import BaseModel

from backend.models.products import Product

__all__ = ["SearchResponse", "SearchStatus", "StoreResult"]

SearchStatus = Literal["ok", "empty", "store_required", "blocked", "timeout", "error"]


class StoreResult(BaseModel):
    store: str
    label: str
    status: SearchStatus
    message: str | None = None
    products: list[Product] = []
    cached: bool = False
    store_label: str | None = None
    elapsed_ms: int = 0
    # Contract fields: when the prices were read on the site (Unix time, also
    # for a result from the cache), whether they are older than wanted, and how
    # the scraper read them ("api", "html", "generic" or "json-ld")
    fetched_at: float | None = None
    stale: bool = False
    source: str | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[StoreResult]
