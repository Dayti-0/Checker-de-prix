"""Helpers shared by the API routers."""

import logging

from fastapi import HTTPException

from backend.scrapers import SCRAPERS
from backend.scrapers.base import BaseScraper

# Same logger name as before the split into routers
logger = logging.getLogger("prixmalin")


def get_scraper(key: str) -> BaseScraper:
    """The scraper of retailer ``key``, or a 404 for an unknown retailer."""
    if key not in SCRAPERS:
        raise HTTPException(404, f"Enseigne inconnue : {key}")
    return SCRAPERS[key]
