"""Search orchestration: cache, error handling, relevance and sorting."""

import asyncio
import logging
import re
import time

from backend import config, database
from backend.browser import BrowserUnavailable, browser
from backend.models import Product, SearchResponse, Settings, StoreResult, StoreSelection
from backend.scrapers import SCRAPERS
from backend.scrapers.base import BaseScraper, ScraperError
from backend.scrapers.parsing import finalize_product
from backend.services.matching import query_key, relevance
from backend.services.settings import load_settings

logger = logging.getLogger(__name__)


def cache_key(scraper: BaseScraper, store: StoreSelection | None, query: str) -> str:
    return f"{scraper.key}|{scraper.context_key(store)}|{query_key(query)}"


def prepare_products(products: list[Product], query: str) -> list[Product]:
    """Normalise unit prices, drop duplicates, score and sort by price."""
    unique: dict[tuple[str, str], Product] = {}
    for product in products:
        finalize_product(product)
        product.relevance = relevance(f"{product.name} {product.brand or ''}", query)
        unique.setdefault((product.product_url, product.name.lower()), product)
    return sorted(
        unique.values(),
        key=lambda p: (p.relevance < 1, -p.relevance, p.price is None, p.price or 0),
    )


async def _scrape(scraper: BaseScraper, query: str, store: StoreSelection | None) -> list[Product]:
    for attempt in range(2):
        try:
            return await browser.run(scraper.key, scraper.search, query, store, timeout=config.SCRAPER_TIMEOUT_SECONDS)
        except (ScraperError, asyncio.TimeoutError, BrowserUnavailable):
            raise
        except Exception as e:  # navigation errors, page crashed... retry once
            if attempt:
                raise
            logger.warning("%s: %s, retrying", scraper.label, str(e).splitlines()[0])
            await asyncio.sleep(1.5)
    return []


async def search_store(key: str, query: str, refresh: bool = False, settings: Settings | None = None) -> StoreResult:
    scraper = SCRAPERS[key]
    settings = settings or await load_settings()
    store = settings.stores.get(key)
    result = StoreResult(store=key, label=scraper.label, status="ok", store_label=scraper.store_label(store))
    start = time.monotonic()
    ckey = cache_key(scraper, store, query)

    cached = None if refresh else await database.get_cached(ckey)
    if cached is not None:
        result.products = prepare_products([Product(**p) for p in cached], query)
        result.cached = True
    else:
        try:
            products = await _scrape(scraper, query, store)
        except ScraperError as e:
            result.status, result.message = e.status, str(e)
        except asyncio.TimeoutError:
            result.status = "timeout"
            result.message = f"{scraper.label} n'a pas répondu à temps. Réessayez dans un instant."
        except BrowserUnavailable as e:
            result.status, result.message = "error", str(e)
        except Exception as e:
            result.status = "error"
            network = re.search(r"net::(ERR_[A-Z_]+)", str(e))
            if network:
                logger.warning("%s unreachable: %s", scraper.label, network.group(1))
                result.message = (
                    f"{scraper.label} est injoignable ({network.group(1)}). Vérifiez votre connexion Internet."
                )
            else:
                logger.exception("%s search failed", scraper.label)
                result.message = f"Erreur pendant la recherche sur {scraper.label} : {str(e).splitlines()[0][:200]}"
        else:
            result.products = prepare_products(products, query)
            if result.products:
                await database.set_cached(ckey, [p.model_dump() for p in result.products])

    if result.status == "ok":
        if not result.products:
            result.status = "empty"
            result.message = f"Aucun produit trouvé chez {scraper.label}."
        elif scraper.needs_store and store is None and all(p.price is None for p in result.products):
            result.status = "store_required"
            result.message = f"{scraper.label} n'affiche les prix qu'après le choix d'un magasin."
    result.elapsed_ms = int((time.monotonic() - start) * 1000)
    return result


async def search_all(query: str, stores: list[str] | None = None, refresh: bool = False) -> SearchResponse:
    keys = [k for k in (stores or SCRAPERS) if k in SCRAPERS]
    settings = await load_settings()
    results = await asyncio.gather(*(search_store(k, query, refresh, settings) for k in keys))
    return SearchResponse(query=query, results=list(results))
