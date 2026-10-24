"""Basket comparison (area of P5).

``GET /api/basket/compare/stream`` sends the progress of a comparison as
Server-Sent Events (``EventSource`` of the page): ``start``, ``line`` (one per
search), ``store`` (a retailer is over), ``done`` (the comparison, the same as
``POST /api/basket/compare``) or ``error``. The page closes the EventSource
after ``done``; a browser that reconnects after ``done`` gets a 204 (it stops
reconnecting) instead of a new comparison. When the page leaves (« Arrêter »
closes the EventSource), the searches are cancelled.
"""

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response, StreamingResponse

from backend.api.common import get_scraper
from backend.api.search import until_disconnected
from backend.models import BasketComparison, BasketPrefs, BasketPrefsUpdate, BasketRequest, Candidates
from backend.services import basket

logger = logging.getLogger("prixmalin.basket")

router = APIRouter()

# The stream checks that the page still listens this often (seconds)
DISCONNECT_POLL_SECONDS = 1.0
# A comment line keeps the connection open while a retailer is slow (seconds)
KEEPALIVE_SECONDS = 15.0
ERROR_MESSAGE = "La comparaison du panier a échoué. Réessayez dans un instant."


def _keys(stores: str | None) -> list[str] | None:
    return [s.strip() for s in stores.split(",") if s.strip()] if stores else None


@router.post("/basket/compare", response_model=BasketComparison)
async def api_basket_compare(request: Request, body: BasketRequest):
    comparison = await until_disconnected(
        request, basket.compare_basket(body.stores, body.refresh, cache_only=body.cache_only)
    )
    return Response(status_code=499) if comparison is None else comparison


def sse(event: str, data: object, event_id: str | None = None) -> str:
    """One Server-Sent Event (the JSON data on one line)."""
    head = f"id: {event_id}\n" if event_id else ""
    return f"{head}event: {event}\ndata: {json.dumps(jsonable_encoder(data), ensure_ascii=False)}\n\n"


async def basket_events(
    request: Request, stores: list[str] | None, refresh: bool, cache_only: bool
) -> AsyncIterator[str]:
    """The events of one comparison; the comparison is cancelled when the page leaves."""
    queue: asyncio.Queue = asyncio.Queue()
    run_id = uuid.uuid4().hex[:8]

    async def on_event(name: str, data: dict) -> None:
        await queue.put((name, data))

    async def runner() -> None:
        try:
            await basket.compare_basket(stores, refresh, cache_only=cache_only, on_event=on_event)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 (sent to the page as an « error » event)
            logger.exception("Basket comparison failed")
            await queue.put(("error", {"message": ERROR_MESSAGE}))
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(runner())
    count = 0
    waited = 0.0
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), DISCONNECT_POLL_SECONDS)
            except TimeoutError:
                if await request.is_disconnected():
                    logger.info("Basket comparison stopped: the page left")
                    break
                waited += DISCONNECT_POLL_SECONDS
                if waited >= KEEPALIVE_SECONDS:
                    waited = 0.0
                    yield ": attente\n\n"
                continue
            waited = 0.0
            if item is None:
                break
            name, data = item
            count += 1
            yield sse(name, data, f"done-{run_id}" if name == "done" else f"{run_id}-{count}")
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


@router.get("/basket/compare/stream")
async def api_basket_stream(
    request: Request,
    stores: str | None = Query(None, description="Enseignes séparées par des virgules"),
    refresh: bool = False,
    cache_only: bool = False,
):
    """Live basket (Server-Sent Events)."""
    if request.headers.get("last-event-id", "").startswith("done-"):
        return Response(status_code=204)  # finished: the browser must not start it again
    return StreamingResponse(
        basket_events(request, _keys(stores), refresh, cache_only),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/basket/last", response_model=BasketComparison)
async def api_basket_last():
    """The last comparison (204 when there is none); outdated when its ``list_version`` differs."""
    comparison = await basket.last_comparison()
    return Response(status_code=204) if comparison is None else comparison


@router.get("/basket/candidates/{item_id}/{store}", response_model=Candidates)
async def api_basket_candidates(item_id: int, store: str, refresh: bool = False):
    """Products of a retailer for an item (sheet « Changer »), from the cache when it is fresh."""
    get_scraper(store)
    result = await basket.candidates(item_id, store, refresh)
    if result is None:
        raise HTTPException(404, "Article introuvable")
    return result


@router.get("/basket/prefs", response_model=BasketPrefs)
async def api_basket_prefs():
    return await basket.get_prefs()


@router.patch("/basket/prefs", response_model=BasketPrefs)
async def api_basket_prefs_update(update: BasketPrefsUpdate):
    return await basket.update_prefs(update)
