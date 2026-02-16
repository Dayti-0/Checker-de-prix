import asyncio
import logging
import re
import unicodedata

from backend.database import get_cached_results, set_cached_results
from backend.models import ScrapedProduct, SearchResponse
from backend.scrapers.aldi import AldiScraper
from backend.scrapers.carrefour import CarrefourScraper
from backend.scrapers.coursesu import CoursesUScraper
from backend.scrapers.intermarche import IntermarcheScraper
from backend.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Short words to ignore when matching relevance (French stop words)
_STOP_WORDS = frozenset({
    "de", "du", "des", "le", "la", "les", "un", "une", "au", "aux",
    "et", "ou", "en", "a", "à",
})


def _normalize(text: str) -> str:
    """Lowercase and strip accents from *text*."""
    text = text.lower()
    # Decompose unicode, drop combining marks (accents), recompose
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _extract_words(text: str) -> list[str]:
    """Extract significant alphabetic words from *text* (no stop words, len > 1)."""
    return [
        w for w in re.findall(r"[a-z]+", _normalize(text))
        if w not in _STOP_WORDS and len(w) > 1
    ]


# Minimum ratio of product-name words that must relate to the query keywords.
# Filters out products where the query terms are secondary descriptors
# (e.g. "thon à l'huile de tournesol" when searching "huile de tournesol").
_MIN_RELEVANCE = 0.5


def _is_relevant(product: ScrapedProduct, query: str) -> bool:
    """Return True if the product name is relevant to the search query.

    Two checks are performed:
    1. **All** query keywords must appear in the product name (substring match).
    2. For multi-keyword queries, the query must *cover* a significant share of
       the product name so that products where the query is just a secondary
       descriptor are filtered out.
    """
    norm_name = _normalize(product.name)
    keywords = _extract_words(query)
    if not keywords:
        # If the query is only stop words, don't filter anything
        return True

    # All keywords must appear in the product name (whole-word match to avoid
    # false positives like "eau" matching inside "gateau").
    if not all(re.search(r"\b" + re.escape(kw) + r"\b", norm_name) for kw in keywords):
        return False

    # For multi-keyword queries, check relevance coverage
    if len(keywords) >= 2:
        product_words = _extract_words(product.name)
        if product_words:
            matched = sum(
                1 for pw in product_words
                if any(kw in pw or pw in kw for kw in keywords)
            )
            if matched / len(product_words) < _MIN_RELEVANCE:
                return False

    return True

# Registry of available scrapers
SCRAPERS: dict[str, BaseScraper] = {
    "aldi": AldiScraper(),
    "carrefour": CarrefourScraper(),
    "coursesu": CoursesUScraper(),
    "intermarche": IntermarcheScraper(),
}


async def _run_scraper(
    scraper: BaseScraper, query: str
) -> tuple[list[ScrapedProduct], str | None]:
    """Run a single scraper with caching and error handling."""
    store_key = scraper.store_name.lower()

    # Check cache first
    cached = await get_cached_results(query, store_key)
    if cached is not None:
        logger.info("Cache hit for %s / %s", store_key, query)
        return [ScrapedProduct(**p) for p in cached], None

    try:
        results = await asyncio.wait_for(
            scraper.search(query), timeout=45
        )
        # Store in cache
        await set_cached_results(
            query, store_key, [p.model_dump() for p in results]
        )
        return results, None
    except asyncio.TimeoutError:
        msg = f"{scraper.store_name}: timeout"
        logger.warning(msg)
        return [], msg
    except Exception as e:
        msg = f"{scraper.store_name}: {e}"
        logger.error(msg)
        return [], msg


async def search_all(
    query: str, stores: list[str] | None = None
) -> SearchResponse:
    """Search across all (or selected) stores in parallel."""
    scrapers_to_run: dict[str, BaseScraper] = {}
    if stores:
        for s in stores:
            key = s.lower()
            if key in SCRAPERS:
                scrapers_to_run[key] = SCRAPERS[key]
    else:
        scrapers_to_run = SCRAPERS

    if not scrapers_to_run:
        return SearchResponse(query=query, results=[], errors=["No valid stores selected"])

    tasks = [_run_scraper(scraper, query) for scraper in scrapers_to_run.values()]
    outcomes = await asyncio.gather(*tasks)

    all_results: list[ScrapedProduct] = []
    errors: list[str] = []
    for results, error in outcomes:
        all_results.extend(results)
        if error:
            errors.append(error)

    # Filter out products that don't match the search query
    before = len(all_results)
    all_results = [p for p in all_results if _is_relevant(p, query)]
    filtered = before - len(all_results)
    if filtered:
        logger.info("Filtered out %d irrelevant products for '%s'", filtered, query)

    # Sort by price ascending (products without price go last)
    all_results.sort(key=lambda p: (p.price is None, p.price or 0))

    return SearchResponse(query=query, results=all_results, errors=errors)
