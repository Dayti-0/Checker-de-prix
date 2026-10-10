"""Helpers shared by the API routers."""

from fastapi import HTTPException

from backend.scrapers import SCRAPERS
from backend.scrapers.base import BaseScraper


def get_scraper(key: str) -> BaseScraper:
    """The scraper of retailer ``key``, or a 404 for an unknown retailer."""
    if key not in SCRAPERS:
        raise HTTPException(404, f"Enseigne inconnue : {key}")
    return SCRAPERS[key]
