"""PrixMalin web server: ``python -m backend.main`` (or ``run()``).

``create_app()`` assembles the app: routers of backend/api/, error handlers,
security (backend/security.py), static files. Code of an area goes in its own
router, service or startup hook (backend/services/hooks.py), not here.

``run()`` (lancer.bat) in this order: PrixMalin already open on the port →
its page and exit (backend/instance.py); ``./data`` moved out of the folder
of the app (backend/backup.py); lock of the data folder; log file
(backend/logging_setup.py); address to listen on (Réglages › Sécurité);
daily copy of the database and check of the updates in the background;
uvicorn, then the start banner (addresses, access code, QR code) and the
browser once the server listens.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware

from backend import __version__, backup, config, database, instance, logging_setup, security
from backend.api import api_router, errors, pages_router, system, updates
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
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    # Every /api route lives in backend/api/ (one router per area)
    app.include_router(api_router)
    app.include_router(pages_router)
    system.mount_frontend(app)
    return app


app = create_app()


class Server(uvicorn.Server):
    """uvicorn's server: ``on_ready()`` once it listens (banner, browser)."""

    def __init__(self, config_: uvicorn.Config, on_ready) -> None:
        super().__init__(config_)
        self._on_ready = on_ready

    async def startup(self, sockets=None) -> None:
        await super().startup(sockets=sockets)
        if self.started and not self.should_exit:
            try:
                await asyncio.get_running_loop().run_in_executor(None, self._on_ready)
            except Exception:  # noqa: BLE001 (the server runs anyway)
                logger.exception("Start banner failed")


def run() -> None:
    # Already open (exit 0, its page shown) or port taken by another program (exit 1)
    instance.ensure_single_instance()
    moved = backup.migrate_legacy_data(in_use=instance.is_locked)
    browser.profile_dir = config.BROWSER_PROFILE_DIR  # created at import, before the move
    instance.lock_data_dir()
    log_file = logging_setup.configure()
    if moved:
        logger.log(*moved)
    logging_setup.log_versions()
    logger.info("Data folder: %s, log: %s", config.DATA_DIR, log_file)
    host = security.listen_host()
    security.LISTEN_HOST = host
    instance.check_port(host, config.PORT)
    hooks.on_startup(backup.daily_copies)
    hooks.on_startup(updates.auto_check)
    lan = security.lan_active()
    # No auto-reload: it would start a second browser and breaks Playwright on Windows.
    # No proxy headers: the address of a request is the one of its connection (security.py).
    tls = {"ssl_certfile": config.SSL_CERTFILE, "ssl_keyfile": config.SSL_KEYFILE} if config.scheme() == "https" else {}
    server = Server(
        uvicorn.Config(app, host=host, port=config.PORT, log_config=None, log_level="info", proxy_headers=False, **tls),
        on_ready=lambda: instance.ready(config.PORT, lan),
    )
    server.run()
    if not server.started:
        raise SystemExit(1)


if __name__ == "__main__":
    run()
