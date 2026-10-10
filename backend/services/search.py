"""Search orchestration: cache, circuit breaker, errors, relevance and sorting (area of P3).

``search_store(key, query)`` answers, in this order:

1. **fresh cache** (unless ``refresh``): products younger than 6 h (« no
   product » younger than 30 min). Older than 1 h: served, then refreshed in
   the background (priority ``background``; never for a retailer that has its
   own Chrome window, Intermarché, whose site is only visited when the user
   asks);
2. **no call to the site** while the retailer is paused after a hard block, or
   while its circuit is open (services/circuit.py): after an anti-robot check
   or « store required » for 10 minutes or until « J'ai terminé » or another
   store, after 2 timeouts in a row for 2 minutes. A search asked again by the
   user (``refresh``) goes through, except during a hard block or an
   unvalidated check of Intermarché;
3. **the site**, through ``_scrape`` (``browser.run``, one more try in a fresh
   tab after a navigation error only, never for Intermarché). Identical
   searches running at the same time share one visit.

When the site cannot answer (blocked, timeout, error, browser unavailable), the
last prices younger than 7 days are shown, marked ``stale`` with the message
« Prix du 03/10 à 14 h (Carrefour : vérification requise) ».

Emits ``products_scraped`` after each real visit and ``search_finished`` for
every search (P0 contracts).
"""

import asyncio
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import ValidationError

from backend import config
from backend.browser import PRIORITIES, BrowserUnavailable, QueueTimeout, browser
from backend.errors import short_error
from backend.models import Product, RetailerState, SearchResponse, Settings, StoreResult, StoreSelection
from backend.repos import cache
from backend.scrapers import SCRAPERS
from backend.scrapers.base import BaseScraper, BlockedError, HardBlockError, ScraperError
from backend.scrapers.common import clock_text, hard_block_message, is_navigation_error, is_timeout_error
from backend.services import hooks
from backend.services.circuit import Circuit, may_call
from backend.services.matching import query_key
from backend.services.products import prepare_products
from backend.services.settings import load_settings

__all__ = [
    "cache_key",
    "prepare_products",
    "reset_circuit",
    "retailer_state",
    "search_all",
    "search_store",
    "stale_message",
]

logger = logging.getLogger("prixmalin.search")

# Priority given to browser.run by the search running in this task
_priority: ContextVar[str] = ContextVar("prixmalin_search_priority", default="interactive")

# How each scraper reads its products first; any other source is a fallback
PRIMARY_SOURCE = {"aldi": "html", "coursesu": "html"}

# Words of the stale message: « Prix du 03/10 à 14 h (Aldi : vérification requise) »
PROBLEM_TEXT = {
    "blocked": "vérification requise",
    "timeout": "site trop lent",
    "error": "site indisponible",
    "store_required": "magasin à choisir",
}

_circuit = Circuit()


def cache_key(scraper: BaseScraper, store: StoreSelection | None, query: str) -> str:
    return f"{scraper.key}|{scraper.context_key(store)}|{query_key(query)}"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def cache_ttl(products: list) -> float:
    """How long a cached search is fresh: 6 h, 30 min when it found no product."""
    return config.CACHE_TTL_SECONDS if products else config.CACHE_EMPTY_TTL_SECONDS


def needs_refresh(products: list, age: float) -> bool:
    """A fresh entry old enough to be read again in the background (1 h to 6 h)."""
    return bool(products) and config.CACHE_REFRESH_AFTER_SECONDS < age < config.CACHE_TTL_SECONDS


def final_status(scraper: BaseScraper, store: StoreSelection | None, products: list[Product]) -> tuple[str, str | None]:
    """Status and message of a visit that returned ``products``."""
    if not products:
        return "empty", f"Aucun produit trouvé chez {scraper.label}."
    if scraper.needs_store and store is None and all(p.price is None for p in products):
        return "store_required", f"{scraper.label} n'affiche les prix qu'après le choix d'un magasin."
    return "ok", None


def stale_message(label: str, fetched_at: float, problem: str, retry_after: float | None = None) -> str:
    """« Prix du 03/10 à 14 h (Carrefour : vérification requise) »."""
    moment = datetime.fromtimestamp(fetched_at)
    clock = f"{moment.hour} h" + (f" {moment.minute:02d}" if moment.minute else "")
    if retry_after:
        what = f"accès bloqué jusqu'à {clock_text(retry_after)}"
    else:
        what = PROBLEM_TEXT.get(problem, "site indisponible")
    return f"Prix du {moment:%d/%m} à {clock} ({label} : {what})"


def error_answer(label: str, error: BaseException) -> tuple[str, str]:
    """Status and French message of a failed visit (technical details go to the log only)."""
    if isinstance(error, ScraperError):
        return error.status, str(error)
    if isinstance(error, BrowserUnavailable):
        return "error", str(error)
    if isinstance(error, QueueTimeout):
        return "timeout", f"Trop de recherches en attente pour {label}. Réessayez dans un instant."
    if is_timeout_error(error):
        return "timeout", f"Le site {label} met trop de temps à répondre."
    if "net::ERR_" in str(error):
        return "error", f"{label} est injoignable. Vérifiez votre connexion Internet."
    return "error", f"La recherche sur {label} a échoué. Réessayez dans un instant."


# ---------------------------------------------------------------------------
# Visit of the site
# ---------------------------------------------------------------------------


async def _scrape(scraper: BaseScraper, query: str, store: StoreSelection | None) -> list[Product]:
    """Products of the site (one more try in a fresh tab after a navigation error)."""
    key = scraper.key
    attempts = 1 if browser.is_dedicated(key) else 2  # Intermarché: never twice
    for attempt in range(attempts):
        try:
            return await browser.run(
                key,
                scraper.search,
                query,
                store,
                timeout=config.scraper_timeout(key),
                priority=_priority.get(),
            )
        except (ScraperError, BrowserUnavailable):
            raise
        except Exception as e:
            if attempt + 1 >= attempts or not is_navigation_error(e):
                raise
            logger.warning("%s: %s, new try in a fresh tab", scraper.label, short_error(e))
            await browser.reset_tab(key)
            await asyncio.sleep(1.0)
    return []


@dataclass
class Visit:
    """What one visit of the site gave (shared by identical searches running together)."""

    status: str = "ok"
    message: str | None = None
    products: list[Product] = field(default_factory=list)
    source: str | None = None
    fetched_at: float | None = None
    retry_after: float | None = None


async def _visit(scraper: BaseScraper, query: str, store: StoreSelection | None, ckey: str, priority: str) -> Visit:
    key = scraper.key
    store_ctx = scraper.context_key(store)
    token = _priority.set(priority)
    scraper.last_source = None
    visit = Visit()
    try:
        products = await _scrape(scraper, query, store)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 (turned into a status and a message)
        visit.status, visit.message = error_answer(scraper.label, e)
        if isinstance(e, HardBlockError):
            visit.retry_after = await _record_hard_block(key, e)
            visit.message = hard_block_message(scraper.label, visit.retry_after)
        elif isinstance(e, BlockedError) and not getattr(e, "recorded", False):
            await browser.hard_blocks.blocked(key)
        if visit.status == "error" and not isinstance(e, (ScraperError, BrowserUnavailable)):
            if "net::ERR_" in str(e):
                logger.warning("%s unreachable: %s", scraper.label, short_error(e))
            else:
                logger.error("%s search failed: %s", scraper.label, short_error(e), exc_info=e)
        elif visit.status == "timeout":
            logger.warning("%s: %s", scraper.label, short_error(e) or "timeout")
    else:
        visit.fetched_at = time.time()
        visit.source = scraper.last_source
        if visit.source and visit.source != PRIMARY_SOURCE.get(key, "api"):
            logger.warning("%s: products read by the fallback method %r", scraper.label, visit.source)
        visit.products = prepare_products(products, query)
        visit.status, visit.message = final_status(scraper, store, visit.products)
        if visit.status == "ok":
            await cache.set_cached(ckey, [p.model_dump() for p in visit.products], source=visit.source)
        elif visit.status == "empty":
            await cache.set_cached(ckey, [], source=None)  # remembered 30 minutes
        await hooks.emit("products_scraped", store=key, store_ctx=store_ctx, query=query, products=visit.products)
    finally:
        _priority.reset(token)
    _circuit.update(key, store_ctx, visit.status, visit.message, products=tuple(visit.products))
    return visit


async def _record_hard_block(key: str, error: HardBlockError) -> float:
    """End of the pause after a hard block (recorded here when browser.run did not)."""
    if error.retry_after is None:
        record = await browser.hard_blocks.hard_block(key)
        error.retry_after = record.until
    return error.retry_after


class _Shared:
    """A visit of the site awaited by every identical search running at the same time."""

    def __init__(self, task: asyncio.Task, rank: int) -> None:
        self.task = task
        self.rank = rank
        self.waiters = 0


_inflight: dict[str, _Shared] = {}
_refreshing: set[asyncio.Task] = set()


async def _shared_visit(
    scraper: BaseScraper, query: str, store: StoreSelection | None, ckey: str, priority: str
) -> Visit:
    """``_visit`` shared by the identical searches (same cache key) running together.

    A search joins a visit of the same or a higher priority. The visit is
    cancelled when every search waiting for it was (the client went away).
    """
    rank = PRIORITIES.index(priority)
    shared = _inflight.get(ckey)
    if (
        shared is None
        or shared.task.done()
        or shared.rank > rank
        or shared.task.get_loop() is not asyncio.get_running_loop()
    ):
        task = asyncio.get_running_loop().create_task(_visit(scraper, query, store, ckey, priority))
        shared = _Shared(task, rank)
        _inflight[ckey] = shared

        def forget(_task: asyncio.Task, entry: _Shared = shared) -> None:
            if _inflight.get(ckey) is entry:
                del _inflight[ckey]

        task.add_done_callback(forget)
    shared.waiters += 1
    try:
        return await asyncio.shield(shared.task)
    except asyncio.CancelledError:
        if shared.waiters == 1 and not shared.task.done():
            shared.task.cancel()  # nobody waits for it any more: free the tab
        raise
    finally:
        shared.waiters -= 1


def _refresh_later(key: str, query: str, settings: Settings) -> None:
    """Read again in the background a cached search older than 1 hour."""

    async def refresh() -> None:
        try:
            await search_store(key, query, True, settings=settings, priority="background")
        except Exception as e:  # noqa: BLE001 (background work)
            logger.info("Background refresh of %s failed: %s", key, short_error(e))

    task = asyncio.get_running_loop().create_task(refresh())
    _refreshing.add(task)
    task.add_done_callback(_refreshing.discard)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def _cached(ckey: str, query: str) -> tuple[list[Product], float, str | None] | None:
    """Products of a cache entry younger than 7 days (an unreadable entry counts as none)."""
    entry = await cache.get_entry(ckey, config.CACHE_STALE_MAX_SECONDS)
    if entry is None:
        return None
    try:
        products = [Product(**p) for p in entry.products]
    except (ValidationError, TypeError) as e:
        logger.info("Cache entry %s unreadable: %s", ckey, short_error(e))
        return None
    return prepare_products(products, query), entry.created_at, entry.source


async def search_store(
    key: str,
    query: str,
    refresh: bool = False,
    *,
    settings: Settings | None = None,
    priority: str = "interactive",
) -> StoreResult:
    """Search ``query`` at retailer ``key`` (see the module docstring).

    ``priority`` ("interactive", "basket" or "background") is passed to the
    browser for the visits of the site.
    """
    if priority not in PRIORITIES:
        raise ValueError(f"unknown priority {priority!r}")
    scraper = SCRAPERS[key]
    settings = settings or await load_settings()
    store = settings.stores.get(key)
    store_ctx = scraper.context_key(store)
    result = StoreResult(store=key, label=scraper.label, status="ok", store_label=scraper.store_label(store))
    start = time.monotonic()
    now = time.time()
    ckey = cache_key(scraper, store, query)
    entry = await _cached(ckey, query)

    if entry is not None and not refresh and now - entry[1] < cache_ttl(entry[0]):
        products, saved_at, source = entry
        result.products, result.fetched_at, result.source, result.cached = products, saved_at, source, True
        if needs_refresh(products, now - saved_at) and not browser.is_dedicated(key):
            _refresh_later(key, query, settings)
    else:
        hard_until = await browser.hard_blocks.until(key)
        state = _circuit.get(key, store_ctx)
        if hard_until:
            visit = Visit(status="blocked", message=hard_block_message(scraper.label, hard_until))
            visit.retry_after = hard_until
        elif not may_call(state, now, refresh=refresh, priority=priority, dedicated=browser.is_dedicated(key)):
            # Circuit open: the answer of the last visit, without calling the site
            visit = Visit(status=state.status or "blocked", message=state.message)
            if state.products:
                visit.products = prepare_products(list(state.products), query)
                visit.fetched_at = state.fetched_at
                result.cached = True
        else:
            visit = await _shared_visit(scraper, query, store, ckey, priority)

        result.status, result.message, result.retry_after = visit.status, visit.message, visit.retry_after
        if visit.fetched_at is not None:
            result.products, result.fetched_at, result.source = visit.products, visit.fetched_at, visit.source
        elif entry is not None and entry[0] and visit.status in ("blocked", "timeout", "error"):
            # The site failed: the last prices known, marked as old
            result.products, result.fetched_at, result.source = entry
            result.cached, result.stale, result.problem = True, True, visit.status
            result.status = "ok"
            result.message = stale_message(scraper.label, entry[1], visit.status, visit.retry_after)

    if result.status == "ok" and result.cached and not result.stale:
        result.status, result.message = final_status(scraper, store, result.products)
    result.elapsed_ms = int((time.monotonic() - start) * 1000)
    await hooks.emit("search_finished", result=result, query=query, store_ctx=store_ctx, from_cache=result.cached)
    return result


async def search_all(query: str, stores: list[str] | None = None, refresh: bool = False) -> SearchResponse:
    keys = [k for k in (stores or SCRAPERS) if k in SCRAPERS]
    settings = await load_settings()
    results = await asyncio.gather(*(search_store(k, query, refresh, settings=settings) for k in keys))
    return SearchResponse(query=query, results=list(results))


async def retailer_state(key: str) -> RetailerState:
    """Circuit breaker and hard block of retailer ``key`` (what the next search will do)."""
    return _circuit.state(key, await browser.hard_blocks.get(key))


def reset_circuit(key: str | None = None) -> None:
    """Allow the visits of ``key`` again (« J'ai terminé »), or of every retailer."""
    _circuit.reset(key)
