"""PrixMalin served by uvicorn in a background thread, for the E2E tests and the demo."""

import asyncio
import socket
import sqlite3
import threading
import time
from pathlib import Path

import uvicorn

from backend import config, database, main


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def use_data_dir(mp, data_dir: Path) -> None:
    """Point the database, the debug snapshots and the browser profile to ``data_dir``."""
    data_dir.mkdir(parents=True, exist_ok=True)
    mp.setattr(config, "DATA_DIR", data_dir)
    mp.setattr(config, "DB_PATH", data_dir / "prixmalin.db")
    mp.setattr(config, "DEBUG_DIR", data_dir / "debug")
    mp.setattr(config, "BROWSER_PROFILE_DIR", data_dir / "browser-profile")
    database._db = None


def make_app():
    create_app = getattr(main, "create_app", None)
    return create_app() if create_app else main.app


class LiveServer:
    """``with LiveServer() as base_url: ...`` (port 0 = a free port)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self.port = port or free_port()
        self.url = f"http://{host}:{self.port}"
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        config_ = uvicorn.Config(
            make_app(), host=self.host, port=self.port, log_level="warning", timeout_graceful_shutdown=5
        )
        self._server = uvicorn.Server(config_)
        self._thread = threading.Thread(target=self._server.run, name="e2e-uvicorn", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 20
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Le serveur PrixMalin n'a pas démarré")
            time.sleep(0.05)
        return self.url

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.should_exit = True
        self._thread.join(timeout=15)
        if self._thread.is_alive():
            self._server.force_exit = True
            self._thread.join(timeout=5)
        self._server = None
        # The app closes the database when it stops. In case it could not: an
        # aiosqlite connection left open would keep the interpreter alive at exit.
        # (In its own thread: the sync Playwright API may be running a loop here.)
        closer = threading.Thread(target=asyncio.run, args=(database.close_db(),))
        closer.start()
        closer.join(timeout=10)

    def __enter__(self) -> str:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def reset_data() -> None:
    """Empty the list, the settings and the cache of the running server.

    Written with a separate SQLite connection: the server reads them again at
    each request.
    """
    if not Path(config.DB_PATH).exists():
        return
    with sqlite3.connect(config.DB_PATH, timeout=5) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table in ("shopping_list", "settings", "search_cache"):
            if table in tables:
                db.execute(f"DELETE FROM {table}")  # noqa: S608 (fixed table names)
    db.close()
