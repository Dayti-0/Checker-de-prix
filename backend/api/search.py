"""Price search: every retailer at once, or one retailer."""

from fastapi import APIRouter, Query

from backend.api.common import get_scraper
from backend.models import SearchResponse, StoreResult
from backend.services.search import search_all, search_store

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
async def api_search(
    q: str = Query(..., min_length=1, max_length=120),
    stores: str | None = Query(None, description="Enseignes séparées par des virgules"),
    refresh: bool = False,
):
    keys = [s.strip() for s in stores.split(",") if s.strip()] if stores else None
    return await search_all(q.strip(), keys, refresh)


@router.get("/search/{store}", response_model=StoreResult)
async def api_search_store(store: str, q: str = Query(..., min_length=1, max_length=120), refresh: bool = False):
    get_scraper(store)
    return await search_store(store, q.strip(), refresh)
