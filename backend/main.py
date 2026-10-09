import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import config, database
from backend.api import api_router
from backend.browser import browser
from backend.scrapers import SCRAPERS
from backend.services import settings as settings_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("prixmalin")


@asynccontextmanager
async def lifespan(app: FastAPI):
    current = await settings_service.load_settings()
    browser.show_browser = current.show_browser
    warmup = None
    if os.environ.get("PRIXMALIN_WARMUP", "1") != "0":
        # Open the sites queried through their API so that the first search is fast
        warmup = asyncio.create_task(
            browser.warmup({k: SCRAPERS[k].home_url for k in ("carrefour", "intermarche", "lidl")})
        )
    yield
    if warmup:
        warmup.cancel()
    await browser.shutdown()
    await database.close_db()


app = FastAPI(title="PrixMalin", version="2.0.0", lifespan=lifespan)

# Every /api route lives in backend/api/ (one router per area)
app.include_router(api_router)


# --- Frontend ---


class FrontendFiles(StaticFiles):
    """Static files revalidated on each load.

    The JavaScript ES modules import each other without a version in their
    URL: without this header the browser could mix old and new modules after
    an update of the app.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


@app.get("/")
async def index():
    return FileResponse(config.FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


app.mount("/static", FrontendFiles(directory=str(config.FRONTEND_DIR)), name="static")


def run() -> None:
    # No auto-reload: it would start a second browser and breaks Playwright on Windows
    print(f"\n  PrixMalin : http://localhost:{config.PORT}\n")
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    run()
