"""PrixMalin web server: ``python -m backend.main`` (or ``run()``).

``create_app()`` assembles the app: routers of backend/api/, error handlers,
security headers, static files. Code of an area goes in its own router,
service or startup hook (backend/services/hooks.py), not here.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from backend import __version__, config, database, instance, logging_setup, security
from backend.api import api_router, errors, pages_router, system
from backend.browser import browser
from backend.services import hooks, warmup
from backend.services import settings as settings_service

logger = logging.getLogger("prixmalin")


async def _run_startup_hook(fn) -> None:
    try:
        await fn()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 (a startup hook never stops the app)
        logger.exception("Startup hook %r failed", fn)


@asynccontextmanager
async def lifespan(app: FastAPI):
    current = await settings_service.load_settings()
    browser.show_browser = current.show_browser
    # Startup hooks (warm-up of the sites...) run in the background
    tasks = [asyncio.create_task(_run_startup_hook(fn)) for fn in hooks.startup_hooks()]
    yield
    for task in tasks:
        task.cancel()
    await browser.shutdown()
    await database.close_db()


def create_app() -> FastAPI:
    app = FastAPI(title="PrixMalin", version=__version__, lifespan=lifespan)
    hooks.on_startup(warmup.warmup)
    errors.install(app)
    security.install(app)
    # Every /api route lives in backend/api/ (one router per area)
    app.include_router(api_router)
    app.include_router(pages_router)
    system.mount_frontend(app)
    return app


app = create_app()


def run() -> None:
    instance.ensure_single_instance()
    logging_setup.configure()
    # No auto-reload: it would start a second browser and breaks Playwright on Windows
    print(f"\n  PrixMalin : http://localhost:{config.PORT}\n")
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    run()
