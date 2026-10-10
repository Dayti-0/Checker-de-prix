from abc import ABC, abstractmethod

from backend.models import Product, StoreSelection


class ScraperError(Exception):
    status = "error"


class BlockedError(ScraperError):
    """The site shows an anti-bot challenge (Cloudflare, DataDome...)."""

    status = "blocked"


class HardBlockError(BlockedError):
    """The site refuses this connection for a while ("Accès temporairement restreint").

    Nothing the user can solve: PrixMalin stops calling the retailer until
    ``retry_after`` (Unix time, set by services/circuit.py) and never retries.
    """

    def __init__(self, message: str = "", retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class StoreRequiredError(ScraperError):
    """Prices cannot be shown until a store is chosen."""

    status = "store_required"


# How a scraper read the products of its last search (BaseScraper.last_source)
SOURCES = ("api", "html", "generic", "json-ld")


class BaseScraper(ABC):
    key: str
    label: str
    home_url: str
    # Prices depend on the store chosen by the user
    needs_store: bool = False
    # Shown in the settings panel
    store_hint: str = ""
    # Set by each search: "api" (JSON of the site read by the scraper), "html"
    # (selectors of the scraper), "generic" (backend/scrapers/extract.py) or
    # "json-ld"; None when nothing was found
    last_source: str | None = None

    def found(self, products: list[Product], source: str) -> list[Product]:
        """Record how ``products`` were read (``last_source``) and return them."""
        self.last_source = source if products else None
        return products

    def store_label(self, store: StoreSelection | None) -> str | None:
        return store.name if store and store.name else None

    def context_key(self, store: StoreSelection | None) -> str:
        """Part of the cache key: results change when the store changes."""
        if store is None:
            return ""
        return store.id or store.url or ""

    def setup_url(self, store: StoreSelection | None) -> str:
        """Page opened when the user wants to act on the site himself."""
        return store.url if store and store.url else self.home_url

    @abstractmethod
    async def search(self, page, query: str, store: StoreSelection | None) -> list[Product]:
        """Search ``query`` using the Playwright ``page`` dedicated to this retailer."""
