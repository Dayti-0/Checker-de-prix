import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

# Everything the app writes (database, browser profile, debug snapshots)
DATA_DIR = Path(os.environ.get("PRIXMALIN_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "prixmalin.db"
BROWSER_PROFILE_DIR = DATA_DIR / "browser-profile"
DEBUG_DIR = DATA_DIR / "debug"

HOST = os.environ.get("PRIXMALIN_HOST", "0.0.0.0")
PORT = int(os.environ.get("PRIXMALIN_PORT", "8000"))

# Browser channel: "chrome", "msedge", "chromium" (bundled with Playwright),
# or empty for auto-detection (installed Chrome, then Edge, then bundled).
BROWSER_CHANNEL = os.environ.get("PRIXMALIN_BROWSER", "").strip().lower()

CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours
# Max time for one retailer search (the first search also warms up the site)
SCRAPER_TIMEOUT_SECONDS = float(os.environ.get("PRIXMALIN_TIMEOUT", "40"))
# Politeness delay between two requests to the same retailer
MIN_REQUEST_INTERVAL_SECONDS = 1.0
