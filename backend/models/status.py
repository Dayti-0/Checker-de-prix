"""State of the retailers: journal of the searches, page « État des enseignes » (area of P4)."""

from typing import Literal

from pydantic import BaseModel

__all__ = ["HealthState", "RetailerHealth", "Snapshot"]

# ok: works; degraded: works with a fallback reader; failing: the last search
# failed; broken: 3 empty or failed searches in a row on different queries;
# blocked: anti-robot check to pass; store_required: no store chosen yet;
# unknown: no search yet
HealthState = Literal["ok", "degraded", "failing", "broken", "blocked", "store_required", "unknown"]


class Snapshot(BaseModel):
    """A page saved in data/debug/ when a search went wrong."""

    name: str
    kind: Literal["html", "png", "json"]
    size: int
    modified: float


class RetailerHealth(BaseModel):
    key: str
    label: str
    state: HealthState
    # French name of the state: « Prêt », « Dégradé », « Probablement cassé »...
    state_label: str
    # Same prices everywhere in France (Aldi, Lidl)
    national: bool = False
    needs_store: bool = False
    store_name: str | None = None
    # Last search read on the site (not from the cache)
    last_at: float | None = None
    last_status: str | None = None
    last_query: str | None = None
    last_success: float | None = None
    # Searches read on the site over the last 7 days, and the share that worked
    searches_7d: int = 0
    success_rate_7d: float | None = None
    consecutive_failures: int = 0
    # Message of the last failed search (French, as shown in the results)
    last_error: str | None = None
    last_source: str | None = None
    # How the retailer is read when everything goes well ("api", "html")
    primary_source: str | None = None
    avg_elapsed_ms: int | None = None
    snapshots: list[Snapshot] = []
