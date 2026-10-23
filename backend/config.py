import os
import shlex
import sys
from collections.abc import Mapping
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

# Everything the app writes (database, browser profiles, logs, debug snapshots):
# PRIXMALIN_DATA_DIR, else %LOCALAPPDATA%\PrixMalin (Windows) or ~/.local/share/prixmalin,
# outside the folder of the app (an update or a new copy of the app keeps them).
# Before 3.0 they were in the folder of the app: run() moves that ./data (backend/backup.py).
LEGACY_DATA_DIR = BASE_DIR / "data"


def default_data_dir(env: Mapping[str, str] = os.environ, platform: str = sys.platform) -> Path:
    if platform == "win32":
        root = env.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / "PrixMalin"
    xdg = env.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / "prixmalin"


def initial_data_dir(env: Mapping[str, str] = os.environ, legacy: Path = LEGACY_DATA_DIR) -> Path:
    """The folder at import: ./data while it waits to be moved (nothing reads elsewhere before run())."""
    if env.get("PRIXMALIN_DATA_DIR"):
        return Path(env["PRIXMALIN_DATA_DIR"])
    target = default_data_dir(env)
    return legacy if legacy.is_dir() and not target.exists() else target


DATA_DIR = initial_data_dir()
DB_PATH = DATA_DIR / "prixmalin.db"
BROWSER_PROFILE_DIR = DATA_DIR / "browser-profile"
DEBUG_DIR = DATA_DIR / "debug"


def use_data_dir(path: Path) -> None:
    """Point every path of the data to ``path`` (after the move of ./data)."""
    global DATA_DIR, DB_PATH, BROWSER_PROFILE_DIR, DEBUG_DIR
    DATA_DIR = Path(path)
    DB_PATH = DATA_DIR / "prixmalin.db"
    BROWSER_PROFILE_DIR = DATA_DIR / "browser-profile"
    DEBUG_DIR = DATA_DIR / "debug"


# 0.0.0.0: the phone on the same Wi-Fi reaches PrixMalin with the address of the PC. Without
# PRIXMALIN_HOST, run() listens on 127.0.0.1 when « Autoriser l'accès depuis le téléphone » is off
HOST = os.environ.get("PRIXMALIN_HOST", "0.0.0.0")  # noqa: S104
HOST_FROM_ENV = bool(os.environ.get("PRIXMALIN_HOST", "").strip())
PORT = int(os.environ.get("PRIXMALIN_PORT", "8000"))

# Browser channel: "chrome", "msedge", "chromium" (bundled with Playwright),
# or empty for auto-detection (installed Chrome, then Edge, then bundled).
BROWSER_CHANNEL = os.environ.get("PRIXMALIN_BROWSER", "").strip().lower()

# --- Délais, cache et navigateur (area of P3) ---------------------------------

CACHE_TTL_SECONDS = 6 * 60 * 60  # a cached search is fresh for 6 hours
CACHE_REFRESH_AFTER_SECONDS = 60 * 60  # older than 1 hour: served, then refreshed in the background
CACHE_STALE_MAX_SECONDS = 7 * 24 * 60 * 60  # served (marked stale) when the site fails, purged after
CACHE_EMPTY_TTL_SECONDS = 30 * 60  # "no product" is remembered 30 minutes

# Max time for one retailer search (the first search also warms up the site);
# PRIXMALIN_TIMEOUT_<KEY> (e.g. PRIXMALIN_TIMEOUT_COURSESU=90) for one retailer
SCRAPER_TIMEOUT_SECONDS = float(os.environ.get("PRIXMALIN_TIMEOUT", "40"))
# Longer default: Courses U visits the store page first; Intermarché and
# E.Leclerc may have to start their Chrome window and wait for the site to
# settle (E.Leclerc also visits the page of the drive)
SCRAPER_TIMEOUT_DEFAULTS = {"coursesu": 60.0, "intermarche": 60.0, "leclerc": 60.0}
# Max time waiting for the tab of a retailer (other searches before this one)
QUEUE_TIMEOUT_SECONDS = float(os.environ.get("PRIXMALIN_QUEUE_TIMEOUT", "90"))

# Politeness delay between two requests to the same retailer (plus 0 to 0.5 s)
MIN_REQUEST_INTERVAL_SECONDS = 1.0
REQUEST_JITTER_SECONDS = 0.5
# E.Leclerc: a burst of about 5 requests is refused by DataDome
REQUEST_INTERVAL_SECONDS = {"intermarche": 1.1, "leclerc": 1.5}

# Circuit breaker: after a "blocked" or "store_required" answer the retailer is
# not called again for 10 minutes (unless the user forces it), after 2 timeouts
# in a row for 2 minutes
CIRCUIT_BLOCKED_SECONDS = 10 * 60
CIRCUIT_TIMEOUT_SECONDS = 2 * 60
CIRCUIT_TIMEOUTS = 2
# Hard block (anti-bot "access restricted" page): no call at all to the
# retailer for 30 minutes, doubled at each new block, at most 4 hours
HARD_BLOCK_COOLDOWN_SECONDS = 30 * 60
HARD_BLOCK_COOLDOWN_MAX_SECONDS = 4 * 60 * 60


def parse_store_list(value: str) -> tuple[str, ...]:
    """``"intermarche, carrefour"`` → ``("intermarche", "carrefour")`` (empty: none)."""
    return tuple(k.strip().lower() for k in value.split(",") if k.strip())


# Retailers driven through a dedicated real Chrome window (backend/real_chrome.py)
# instead of the shared Playwright browser. PRIXMALIN_REAL_CHROME= (empty) goes
# back to the shared browser for every retailer (not advised for Intermarché
# nor E.Leclerc, both behind DataDome).
REAL_CHROME_STORES = parse_store_list(os.environ.get("PRIXMALIN_REAL_CHROME", "intermarche,leclerc"))
# chrome.exe or msedge.exe to use (found automatically when empty)
CHROME_PATH = os.environ.get("PRIXMALIN_CHROME_PATH", "").strip()
# Extra command line switches of that Chrome: for the tests only (--no-sandbox)
CHROME_EXTRA_ARGS = tuple(shlex.split(os.environ.get("PRIXMALIN_CHROME_ARGS", "")))
# Pause after the dedicated window loaded the site, before the first API call
REAL_CHROME_SETTLE_SECONDS = 2.0

# Images, fonts and ads are not loaded in the invisible tabs of Aldi and
# Courses U (PRIXMALIN_LIGHT=0 loads everything)
LIGHT_MODE = os.environ.get("PRIXMALIN_LIGHT", "1") != "0"


def scraper_timeout(key: str) -> float:
    """Max time of one search at retailer ``key`` (PRIXMALIN_TIMEOUT_<KEY> wins)."""
    value = os.environ.get(f"PRIXMALIN_TIMEOUT_{key.upper()}", "").strip()
    if value:
        try:
            return float(value)
        except ValueError:
            pass
    if "PRIXMALIN_TIMEOUT" in os.environ:
        return SCRAPER_TIMEOUT_SECONDS
    return max(SCRAPER_TIMEOUT_DEFAULTS.get(key, SCRAPER_TIMEOUT_SECONDS), SCRAPER_TIMEOUT_SECONDS)


def real_chrome_profile_dir(key: str) -> Path:
    """Profile of the dedicated Chrome window of retailer ``key`` (data/chrome-intermarche, data/chrome-leclerc)."""
    return DATA_DIR / f"chrome-{key}"


# --- Sécurité, lancement et mises à jour (area of P7) -----------------------

# Names of the PC accepted in the address bar besides localhost, the IP
# addresses, the name of the PC (and « name.local ») and Tailscale's *.ts.net:
# PRIXMALIN_ALLOWED_HOSTS=prixmalin.maison,.mondomaine.fr (".x": every name ending with it)
ALLOWED_HOSTS = tuple(h.strip().lower() for h in os.environ.get("PRIXMALIN_ALLOWED_HOSTS", "").split(",") if h.strip())
# lancer.bat sets it: the browser opens PrixMalin as soon as the server listens
OPEN_BROWSER = os.environ.get("PRIXMALIN_OPEN_BROWSER", "") == "1"
# GitHub repository of the releases (Réglages › À propos, mettre-a-jour.bat)
UPDATES_REPO = "Dayti-0/Checker-de-prix"
