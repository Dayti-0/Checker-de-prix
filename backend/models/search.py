"""Result of a search at one retailer, or at all of them (area of P3)."""

from typing import Literal

from pydantic import BaseModel

from backend.models.products import Product

__all__ = ["BlockRecord", "BlockRecords", "RetailerState", "SearchResponse", "SearchStatus", "StoreResult"]

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
    # Older prices shown because the site failed (stale is true, status "ok"):
    # what went wrong ("blocked", "timeout"...)
    problem: SearchStatus | None = None
    # The retailer refused the connection (hard block): PrixMalin makes no call
    # to its site before this Unix time, « Réessayer » is useless until then
    retry_after: float | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[StoreResult]


class BlockRecord(BaseModel):
    """What PrixMalin remembers of the anti-robot blocks of one retailer."""

    # Hard block ("Accès temporairement restreint"): no call at all before this time
    until: float = 0.0
    # Length of the last pause (doubled at each new hard block, at most 4 h)
    seconds: float = 0.0
    last_hard_block: float = 0.0
    # Last anti-robot check or block of any kind (the warm-up skips the retailer for 24 h)
    last_blocked: float = 0.0


class BlockRecords(BaseModel):
    """Preferences section ``p3.blocks`` (stored in the settings table)."""

    retailers: dict[str, BlockRecord] = {}


class RetailerState(BaseModel):
    """Circuit breaker of a retailer (``search.retailer_state(key)``)."""

    store: str
    # No call to the site before ``until`` (unless the user asks for a new
    # search, and never during a hard block)
    circuit_open: bool = False
    # "blocked", "store_required", "timeout" or "hard_block"
    reason: str | None = None
    until: float | None = None
    # Timeouts in a row
    timeouts: int = 0
    hard_block_until: float | None = None
    last_blocked: float | None = None
