from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "prixmalin.db"
CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours
SCRAPER_TIMEOUT_SECONDS = 15
