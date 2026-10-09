"""Warm-up: open the sites queried through their API when the app starts (area of P3).

The first search is then fast. Disabled with PRIXMALIN_WARMUP=0 (tests, demo).
"""

import os

from backend.browser import browser
from backend.scrapers import SCRAPERS

WARMED_UP = ("carrefour", "intermarche", "lidl")


def enabled() -> bool:
    return os.environ.get("PRIXMALIN_WARMUP", "1") != "0"


async def warmup() -> None:
    """Startup hook (registered by backend/main.py)."""
    if enabled():
        await browser.warmup({key: SCRAPERS[key].home_url for key in WARMED_UP})
