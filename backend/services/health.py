"""State of the retailers and diagnostic report (area of P4).

Every search at a retailer is written to the journal ``scrape_log`` by the
``search_finished`` hook (``record_search``), cache hits included; rows older
than ``LOG_DAYS`` days are removed. ``retailer_health`` turns the journal of a
retailer into its state (pure function):

- ``store_required``: no store chosen for a retailer that needs one, or the
  site does not know the store chosen any more (``last_error`` says why);
  an answer « Magasin à choisir » given for another store than the current
  one (the store was changed since) is left out;
- ``blocked``: the last search met an anti-robot check;
- ``broken``: « Probablement cassé », the last ``BROKEN_AFTER`` searches were
  empty or failed, on as many different queries;
- ``failing``: the last search failed (error, timeout);
- ``degraded``: the last search that worked used a fallback reader instead of
  the main method of the retailer (``PRIMARY_SOURCE``);
- ``ok``, or ``unknown`` before any search.

Only the searches read on the site count; results from the cache are kept in
the journal but say nothing about the site. ``all_health`` reads, for each
retailer, its last ``RECENT_ROWS`` searches and the figures of its whole
journal computed by SQL (``Totals``): a long journal never cuts the 7 days.

``diagnostic_zip()`` builds the report « Télécharger le diagnostic »: logs,
last debug snapshots, state, versions, settings without personal data. Never
the browser profile, its cookies or the database.
"""

import io
import json
import logging
import platform
import re
import sys
import time
import zipfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from backend import __version__, config
from backend.browser import browser
from backend.models import RetailerHealth, Settings, Snapshot, StoreResult
from backend.repos import scrape_log
from backend.scrapers import SCRAPERS
from backend.services import hooks
from backend.services.matching import query_key
from backend.services.settings import load_settings

logger = logging.getLogger("prixmalin.health")

LOG_DAYS = 30
WEEK = 7 * 24 * 3600
# Empty or failed searches in a row, on different queries: « Probablement cassé »
BROKEN_AFTER = 3
# Reader used when everything goes well (BaseScraper.last_source); a scraper may
# declare its own ``primary_source``
PRIMARY_SOURCE = {"aldi": "html", "lidl": "api", "carrefour": "api", "intermarche": "api", "coursesu": "html"}
NATIONAL = {"aldi", "lidl"}

STATE_LABELS = {
    "ok": "Prêt",
    "degraded": "Dégradé",
    "failing": "Échec récent",
    "broken": "Probablement cassé",
    "blocked": "Vérification requise",
    "store_required": "Magasin à choisir",
    "unknown": "Pas encore testé",
}

FAILED = ("empty", "error", "timeout", "blocked")
BROKEN = ("empty", "error")
# Searches of a retailer read to know its last ones (failures in a row...)
RECENT_ROWS = 500

# Files of data/debug/ that may be sent: aldi.html, coursesu-blocked.png,
# intermarche-20261009-101500-error.json, coursesu-stores.html...
SNAPSHOT_NAME = re.compile(r"^(?:" + "|".join(SCRAPERS) + r")(?:-[a-z0-9_-]{1,60})?\.(html|png|json)$")
SNAPSHOT_TYPES = {"html": "text/plain; charset=utf-8", "json": "text/plain; charset=utf-8", "png": "image/png"}

# Diagnostic report: newest snapshots and log files, size limits
DIAGNOSTIC_SNAPSHOTS = 20
DIAGNOSTIC_FILE_LIMIT = 5 * 1024 * 1024
DIAGNOSTIC_LOG_ROWS = 200


# ---------------------------------------------------------------- journal


def log_entry(result: StoreResult, query: str, store_ctx: str, from_cache: bool, now: float | None = None) -> dict:
    """Row of ``scrape_log`` for the result of a search."""
    return {
        "ts": now or time.time(),
        "store": result.store,
        "store_ctx": store_ctx or "",
        "query": (query or "")[:200],
        "status": result.status,
        "source": result.source,
        "products": len(result.products),
        "priced": sum(1 for p in result.products if p.price is not None),
        "elapsed_ms": int(result.elapsed_ms or 0),
        "error": (result.message or "")[:500] if result.status != "ok" else None,
        "from_cache": int(bool(from_cache)),
    }


_last_purge = 0.0


async def record_search(result: StoreResult, query: str, store_ctx: str, from_cache: bool, **_) -> None:
    """Listener of ``search_finished``: one row per search, old rows removed once a day."""
    global _last_purge
    await scrape_log.insert(log_entry(result, query, store_ctx, from_cache))
    if time.time() - _last_purge > 24 * 3600:
        _last_purge = time.time()
        removed = await scrape_log.purge(LOG_DAYS * 24 * 3600)
        if removed:
            logger.info("%d old searches removed from the journal", removed)


hooks.on("search_finished", record_search)


# ---------------------------------------------------------------- state (pure)


@dataclass
class Totals:
    """Figures of a retailer over its whole journal (searches read on the site)."""

    searches_7d: int = 0
    ok_7d: int = 0
    avg_elapsed_ms: int | None = None
    last_success: float | None = None
    last_source: str | None = None


def totals_of(real: list[dict], now: float) -> Totals:
    """``Totals`` from the rows themselves (all of them, the newest first)."""
    week = [r for r in real if now - r["ts"] <= WEEK and r["status"] != "store_required"]
    last_ok = next((r for r in real if r["status"] == "ok"), None)
    elapsed = [r["elapsed_ms"] for r in week if r.get("elapsed_ms")]
    return Totals(
        searches_7d=len(week),
        ok_7d=sum(r["status"] == "ok" for r in week),
        avg_elapsed_ms=round(sum(elapsed) / len(elapsed)) if elapsed else None,
        last_success=last_ok["ts"] if last_ok else None,
        last_source=last_ok.get("source") if last_ok else None,
    )


def primary_source(key: str) -> str | None:
    scraper = SCRAPERS.get(key)
    return getattr(scraper, "primary_source", None) or PRIMARY_SOURCE.get(key)


def retailer_health(
    key: str,
    rows: list[dict],
    now: float,
    *,
    label: str | None = None,
    needs_store: bool = False,
    store_name: str | None = None,
    has_store: bool = False,
    primary: str | None = None,
    snapshots: list[Snapshot] | None = None,
    store_ctx: str | None = None,
    totals: Totals | None = None,
) -> RetailerHealth:
    """State of retailer ``key`` from its journal ``rows`` (the newest first).

    ``store_ctx``: context of the current store (``scraper.context_key``), to
    leave out the answers « Magasin à choisir » about another store.
    ``totals``: figures of the whole journal when ``rows`` holds the last
    searches only (computed from ``rows`` otherwise).
    """
    real = [r for r in rows if not r.get("from_cache")]
    if store_ctx is not None:
        real = [r for r in real if r["status"] != "store_required" or (r.get("store_ctx") or "") == store_ctx]
    totals = totals or totals_of(real, now)
    last = real[0] if real else None

    failures = 0
    for row in real:
        if row["status"] == "store_required":
            continue
        if row["status"] not in FAILED:
            break
        failures += 1

    run, queries = 0, set()
    for row in real:
        # The site's API answered « nothing » (Lidl publishes few foods): not broken
        if row["status"] not in BROKEN or (row["status"] == "empty" and row.get("source") == "api"):
            break
        run += 1
        queries.add(query_key(row["query"]))
    broken = run >= BROKEN_AFTER and len(queries) >= BROKEN_AFTER

    degraded = bool(totals.last_success and primary and totals.last_source and totals.last_source != primary)

    if needs_store and not has_store:
        state = "store_required"
    elif last is None:
        state = "unknown"
    elif last["status"] == "blocked":
        state = "blocked"
    elif last["status"] == "store_required":
        state = "store_required"
    elif broken:
        state = "broken"
    elif last["status"] in ("error", "timeout"):
        state = "failing"
    elif degraded:
        state = "degraded"
    else:
        state = "ok"

    last_failed = next((r for r in real if r["status"] in FAILED and r.get("error")), None)
    last_error = last_failed["error"] if last_failed and failures else None
    if state == "store_required":
        # The store chosen is unknown to the site (« Ce magasin n'existe plus »)
        last_error = last.get("error") if has_store and last and last["status"] == "store_required" else None
    return RetailerHealth(
        key=key,
        label=label or key,
        state=state,
        state_label=STATE_LABELS[state],
        national=key in NATIONAL,
        needs_store=needs_store,
        store_name=store_name,
        last_at=last["ts"] if last else None,
        last_status=last["status"] if last else None,
        last_query=last["query"] if last else None,
        last_success=totals.last_success,
        searches_7d=totals.searches_7d,
        success_rate_7d=round(totals.ok_7d / totals.searches_7d, 3) if totals.searches_7d else None,
        consecutive_failures=failures,
        last_error=last_error,
        last_source=totals.last_source,
        primary_source=primary,
        avg_elapsed_ms=totals.avg_elapsed_ms,
        snapshots=snapshots or [],
    )


# ---------------------------------------------------------------- snapshots


def snapshot_files(key: str) -> list[Path]:
    """Debug snapshots of retailer ``key`` (data/debug/{key}*), the newest first."""
    try:
        files = [f for f in config.DEBUG_DIR.glob(key + "*") if f.is_file() and SNAPSHOT_NAME.match(f.name)]
    except OSError:
        return []
    # « coursesu*» must not catch another retailer whose key starts the same way
    files = [f for f in files if f.name[len(key)] in ".-"]
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)


def snapshots_of(key: str) -> list[Snapshot]:
    out = []
    for f in snapshot_files(key):
        stat = f.stat()
        out.append(Snapshot(name=f.name, kind=f.suffix[1:], size=stat.st_size, modified=stat.st_mtime))
    return out


def snapshot_file(name: str) -> Path | None:
    """The snapshot called ``name`` (strictly checked), or None."""
    if not SNAPSHOT_NAME.match(name or ""):
        return None
    path = config.DEBUG_DIR / name
    return path if path.is_file() else None


# ---------------------------------------------------------------- services


async def all_health(now: float | None = None) -> list[RetailerHealth]:
    """State of every retailer, in the display order."""
    now = now or time.time()
    settings = await load_settings()
    since = now - LOG_DAYS * 24 * 3600
    out = []
    for key, scraper in SCRAPERS.items():
        store = settings.stores.get(key)
        rows = await scrape_log.entries(since=since, store=key, limit=RECENT_ROWS, real_only=True)
        totals = Totals(**await scrape_log.totals(key, week_since=now - WEEK, since=since))
        out.append(
            retailer_health(
                key,
                rows,
                now,
                label=scraper.label,
                needs_store=scraper.needs_store,
                store_name=scraper.store_label(store),
                has_store=store is not None,
                primary=primary_source(key),
                snapshots=snapshots_of(key),
                store_ctx=scraper.context_key(store),
                totals=totals,
            )
        )
    return out


def public_settings(settings: Settings) -> dict:
    """Settings without personal data (no postal code, town, store or address)."""
    return {
        "location": settings.location is not None,
        "location_has_coordinates": bool(settings.location and settings.location.lat is not None),
        "show_browser": settings.show_browser,
        "stores": {key: {"chosen": True, "auto": s.auto} for key, s in settings.stores.items()},
    }


def versions() -> dict:
    def version_of(package: str) -> str | None:
        try:
            return metadata.version(package)
        except metadata.PackageNotFoundError:
            return None

    status = browser.status()
    return {
        "prixmalin": __version__,
        "python": sys.version.split()[0],
        "playwright": version_of("playwright"),
        "fastapi": version_of("fastapi"),
        "os": platform.platform(),
        "browser_channel": status.channel or config.BROWSER_CHANNEL or None,
        "browser_running": status.running,
        "browser_error": status.error,
    }


def _add_file(archive: zipfile.ZipFile, path: Path, name: str) -> bool:
    try:
        if path.stat().st_size > DIAGNOSTIC_FILE_LIMIT:
            return False
        archive.write(path, name)
        return True
    except OSError as e:
        logger.debug("Diagnostic: %s skipped (%s)", path, e)
        return False


async def diagnostic_zip(now: float | None = None) -> bytes:
    """The diagnostic report (zip): see the docstring of this module."""
    now = now or time.time()
    health = await all_health(now)
    settings = await load_settings()
    rows = await scrape_log.entries(since=now - LOG_DAYS * 24 * 3600, limit=DIAGNOSTIC_LOG_ROWS)
    journal = [{k: v for k, v in row.items() if k not in ("id", "store_ctx")} for row in rows]

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("LISEZMOI.txt", README.format(version=__version__, date=time.strftime("%Y-%m-%d %H:%M")))
        state = [h.model_dump(exclude={"store_name"}) for h in health]  # the store tells where the user lives
        archive.writestr("etat.json", json.dumps(state, ensure_ascii=False, indent=2))
        archive.writestr("versions.json", json.dumps(versions(), ensure_ascii=False, indent=2))
        archive.writestr("reglages.json", json.dumps(public_settings(settings), ensure_ascii=False, indent=2))
        archive.writestr("recherches.json", json.dumps(journal, ensure_ascii=False, indent=2))
        logs = config.DATA_DIR / "logs"
        if logs.is_dir():
            for f in sorted(logs.iterdir()):
                if f.is_file():
                    _add_file(archive, f, f"logs/{f.name}")
        snapshots = sorted(
            (f for key in SCRAPERS for f in snapshot_files(key)), key=lambda f: f.stat().st_mtime, reverse=True
        )
        for f in snapshots[:DIAGNOSTIC_SNAPSHOTS]:
            _add_file(archive, f, f"captures/{f.name}")
    return buffer.getvalue()


README = """Diagnostic de PrixMalin {version} ({date})

etat.json        état de chaque enseigne (dernières recherches, erreurs, méthode)
recherches.json  dernières recherches (enseigne, requête, statut, durée)
versions.json    versions de PrixMalin, Python, Playwright, système, navigateur
reglages.json    réglages, sans code postal, commune ni magasin
captures/        dernières pages enregistrées quand une recherche a échoué
logs/            journaux de PrixMalin (s'ils existent)

Ni le profil du navigateur, ni ses cookies, ni la base de données n'y figurent.
"""
