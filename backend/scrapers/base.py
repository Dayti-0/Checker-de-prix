from abc import ABC, abstractmethod

from backend.models import ScrapedProduct


class BaseScraper(ABC):
    store_name: str

    @abstractmethod
    async def search(self, query: str) -> list[ScrapedProduct]:
        """Search for a product and return a list of results."""

    @abstractmethod
    async def setup_location(self, postal_code: str) -> bool:
        """Configure the nearest store for this retailer."""
