"""Startup work of the search engine (area of P3): warm-up and cache purge.

Warm-up: open the sites queried through their API, so that the first search
is fast. Only the retailers that can answer are opened:
a store chosen when the retailer needs one, and no anti-robot check or block
in the last 24 hours. Intermarché is never opened here: its dedicated Chrome
window only starts for a search asked by the user (DataDome watches every
visit). Disabled with PRIXMALIN_WARMUP=0 (tests, demo).

Purge: the cached searches older than 7 days are removed at startup, then
every day.
"""

import asyncio
import logging
import os
import time

from backend.browser import browser
from backend.errors import short_error
from backend.models import BlockRecord, Settings
from backend.repos import cache
from backend.scrapers import SCRAPERS
from backend.services.settings import load_settings

logger = logging.getLogger("prixmalin.warmup")

# Retailers read through their JSON API from a page of their site
WARMED_UP = ("carrefour", "lidl")

# A retailer that asked for a check (or blocked) within this time is left alone
RECENT_BLOCK_SECONDS = 24 * 60 * 60
# The old cached searches are removed this often
PURGE_INTERVAL_SECONDS = 24 * 60 * 60


def enabled() -> bool:
    return os.environ.get("PRIXMALIN_WARMUP", "1") != "0"


def warmup_targets(
    settings: Settings,
    blocks: dict[str, BlockRecord],
    now: float,
    *,
    keys: tuple[str, ...] = WARMED_UP,
    dedicated: tuple[str, ...] = (),
) -> list[str]:
    """Retailers to open at startup (pure function)."""
    targets = []
    for key in keys:
        scraper = SCRAPERS.get(key)
        if scraper is None or key == "intermarche" or key in dedicated:
            continue
        if scraper.needs_store and settings.stores.get(key) is None:
            continue
        record = blocks.get(key)
        if record is not None and (record.until > now or now - record.last_blocked < RECENT_BLOCK_SECONDS):
            continue
        targets.append(key)
    return targets


async def warmup_once() -> None:
    """Open the allowed sites in the background (nothing when PRIXMALIN_WARMUP=0)."""
    if not enabled():
        return
    settings = await load_settings()
    now = time.time()
    blocks = {key: await browser.hard_blocks.get(key) for key in WARMED_UP}
    keys = warmup_targets(settings, blocks, now, dedicated=tuple(k for k in WARMED_UP if browser.is_dedicated(k)))
    skipped = [k for k in WARMED_UP if k not in keys]
    if skipped:
        logger.info("Warm-up skips %s", ", ".join(skipped))
    if keys:
        await browser.warmup({key: SCRAPERS[key].home_url for key in keys})


async def purge_old_results() -> None:
    try:
        removed = await cache.purge_cache()
    except Exception as e:  # noqa: BLE001 (tried again the next day)
        logger.warning("Cache purge failed: %s", short_error(e))
        return
    if removed:
        logger.info("%s cached searches older than 7 days removed", removed)


async def warmup() -> None:
    """Startup hook (registered by backend/main.py): purge, warm-up, then a purge every day."""
    await purge_old_results()
    await warmup_once()
    while True:
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)
        await purge_old_results()
