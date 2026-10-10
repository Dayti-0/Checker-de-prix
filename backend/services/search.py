"""Search orchestration: cache, error handling, relevance and sorting (area of P3)."""

import asyncio
import logging
import re
import time
from contextvars import ContextVar

from backend import config
from backend.browser import BrowserUnavailable, browser
from backend.errors import short_error
from backend.models import Product, SearchResponse, Settings, StoreResult, StoreSelection
from backend.repos import cache
from backend.scrapers import SCRAPERS
from backend.scrapers.base import BaseScraper, ScraperError
from backend.services import hooks
from backend.services.matching import query_key
from backend.services.products import prepare_products
from backend.services.settings import load_settings

__all__ = ["cache_key", "prepare_products", "search_all", "search_store"]

logger = logging.getLogger(__name__)

# Priority given to browser.run by the search running in this task
_priority: ContextVar[str] = ContextVar("prixmalin_search_priority", default="interactive")


def cache_key(scraper: BaseScraper, store: StoreSelection | None, query: str) -> str:
    return f"{scraper.key}|{scraper.context_key(store)}|{query_key(query)}"


async def _scrape(scraper: BaseScraper, query: str, store: StoreSelection | None) -> list[Product]:
    for attempt in range(2):
        try:
            return await browser.run(
                scraper.key,
                scraper.search,
                query,
                store,
                timeout=config.SCRAPER_TIMEOUT_SECONDS,
                priority=_priority.get(),
            )
        except (ScraperError, TimeoutError, BrowserUnavailable):
            raise
        except Exception as e:  # navigation errors, page crashed... retry once
            if attempt:
                raise
            logger.warning("%s: %s, retrying", scraper.label, short_error(e))
            await asyncio.sleep(1.5)
    return []


async def search_store(
    key: str,
    query: str,
    refresh: bool = False,
    *,
    settings: Settings | None = None,
    priority: str = "interactive",
) -> StoreResult:
    """Search ``query`` at retailer ``key`` (from the cache unless ``refresh``).

    ``priority`` ("interactive", "basket" or "background") is passed to the
    browser for the calls to the site.
    """
    scraper = SCRAPERS[key]
    settings = settings or await load_settings()
    store = settings.stores.get(key)
    store_ctx = scraper.context_key(store)
    result = StoreResult(store=key, label=scraper.label, status="ok", store_label=scraper.store_label(store))
    start = time.monotonic()
    ckey = cache_key(scraper, store, query)

    entry = None if refresh else await cache.get_cached_entry(ckey)
    if entry is not None:
        cached, saved_at = entry
        result.products = prepare_products([Product(**p) for p in cached], query)
        result.cached = True
        result.fetched_at = saved_at
    else:
        token = _priority.set(priority)
        scraper.last_source = None
        try:
            products = await _scrape(scraper, query, store)
        except ScraperError as e:
            result.status, result.message = e.status, str(e)
            result.retry_after = getattr(e, "retry_after", None)
        except TimeoutError:
            result.status = "timeout"
            result.message = f"{scraper.label} n'a pas répondu à temps. Réessayez dans un instant."
        except BrowserUnavailable as e:
            result.status, result.message = "error", str(e)
        except Exception as e:  # noqa: BLE001 (turned into a message for the user)
            result.status = "error"
            network = re.search(r"net::(ERR_[A-Z_]+)", str(e))
            if network:
                logger.warning("%s unreachable: %s", scraper.label, network.group(1))
                result.message = (
                    f"{scraper.label} est injoignable ({network.group(1)}). Vérifiez votre connexion Internet."
                )
            else:
                logger.exception("%s search failed", scraper.label)
                result.message = f"Erreur pendant la recherche sur {scraper.label} : {short_error(e)}"
        else:
            result.fetched_at = time.time()
            result.source = scraper.last_source
            result.products = prepare_products(products, query)
            if result.products:
                await cache.set_cached(ckey, [p.model_dump() for p in result.products])
            await hooks.emit("products_scraped", store=key, store_ctx=store_ctx, query=query, products=result.products)
        finally:
            _priority.reset(token)

    if result.status == "ok":
        if not result.products:
            result.status = "empty"
            result.message = f"Aucun produit trouvé chez {scraper.label}."
        elif scraper.needs_store and store is None and all(p.price is None for p in result.products):
            result.status = "store_required"
            result.message = f"{scraper.label} n'affiche les prix qu'après le choix d'un magasin."
    result.elapsed_ms = int((time.monotonic() - start) * 1000)
    await hooks.emit("search_finished", result=result, query=query, store_ctx=store_ctx, from_cache=result.cached)
    return result


async def search_all(query: str, stores: list[str] | None = None, refresh: bool = False) -> SearchResponse:
    keys = [k for k in (stores or SCRAPERS) if k in SCRAPERS]
    settings = await load_settings()
    results = await asyncio.gather(*(search_store(k, query, refresh, settings=settings) for k in keys))
    return SearchResponse(query=query, results=list(results))
