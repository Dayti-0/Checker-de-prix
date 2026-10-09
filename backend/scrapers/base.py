from abc import ABC, abstractmethod

from backend.models import Product, StoreSelection


class ScraperError(Exception):
    status = "error"


class BlockedError(ScraperError):
    """The site shows an anti-bot challenge (Cloudflare, DataDome...)."""

    status = "blocked"


class StoreRequiredError(ScraperError):
    """Prices cannot be shown until a store is chosen."""

    status = "store_required"


class BaseScraper(ABC):
    key: str
    label: str
    home_url: str
    # Prices depend on the store chosen by the user
    needs_store: bool = False
    # Shown in the settings panel
    store_hint: str = ""

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
