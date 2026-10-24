"""Price search: every retailer at once, or one retailer (area of P3).

The search runs in its own task, cancelled when the client went away (page
closed, new search typed): the tab of the retailer is then freed at once.
"""

import asyncio
import contextlib

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from backend.api.common import get_scraper
from backend.models import SearchResponse, StoreResult
from backend.services.search import search_all, search_store

router = APIRouter()

# How often the API checks that the client still waits for the answer
DISCONNECT_POLL_SECONDS = 0.5


async def until_disconnected(request: Request, coro):
    """Result of ``coro``, or None when the client left first (``coro`` is then cancelled)."""
    task = asyncio.ensure_future(coro)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=DISCONNECT_POLL_SECONDS)
            if done:
                return task.result()
            if await request.is_disconnected():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                return None
    finally:
        if not task.done():
            task.cancel()


def _gone() -> Response:
    # Nobody reads it: 499 « client closed request »
    return Response(status_code=499)


@router.get("/search", response_model=SearchResponse)
async def api_search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=120),
    stores: str | None = Query(None, description="Enseignes séparées par des virgules"),
    refresh: bool = False,
):
    keys = [s.strip() for s in stores.split(",") if s.strip()] if stores else None
    result = await until_disconnected(request, search_all(q.strip(), keys, refresh))
    return _gone() if result is None else result


@router.get("/search/{store}", response_model=StoreResult)
async def api_search_store(
    request: Request, store: str, q: str = Query(..., min_length=1, max_length=120), refresh: bool = False
):
    get_scraper(store)
    result = await until_disconnected(request, search_store(store, q.strip(), refresh))
    return _gone() if result is None else result
