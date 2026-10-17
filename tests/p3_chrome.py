"""Real Chrome window of the P3 tests (dedicated Intermarché window, backend/real_chrome.py).

That window is never headless: on Linux without a display the tests start
their own Xvfb (``xvfb-run -a python -m pytest`` works too). The browser is
``PRIXMALIN_CHROME_PATH`` when set, else the Chromium downloaded by Playwright.
"""

import os
import select
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager


def chrome_path() -> str | None:
    """Chrome or Chromium binary for the dedicated window, or None."""
    configured = os.environ.get("PRIXMALIN_CHROME_PATH", "").strip()
    if configured:
        return configured if os.path.isfile(configured) else None
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            path = p.chromium.executable_path
    except Exception:  # noqa: BLE001 (no Playwright browser installed)
        return None
    return path if path and os.path.isfile(path) else None


def sandbox_args() -> tuple[str, ...]:
    """--no-sandbox for the test window on Linux (tests only, never in the app).

    Chrome refuses to start as root without it (containers), and Ubuntu 23.10+
    (GitHub runners) restricts the user namespaces its sandbox needs, so a plain
    Chrome started by a normal user exits at once there too.
    """
    if sys.platform.startswith("linux"):
        return ("--no-sandbox",)
    return ()


@contextmanager
def display() -> Iterator[bool]:
    """A display for a visible window: the current one, or an Xvfb started here.

    Yields False when there is none (no Xvfb installed).
    """
    if not sys.platform.startswith("linux") or os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        yield True
        return
    xvfb = shutil.which("Xvfb")
    if xvfb is None:
        yield False
        return
    read_fd, write_fd = os.pipe()
    proc = subprocess.Popen(  # noqa: S603 (fixed command)
        [xvfb, "-displayfd", str(write_fd), "-screen", "0", "1366x900x24", "-nolisten", "tcp"],
        pass_fds=(write_fd,),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.close(write_fd)
    number = b""
    try:
        while not number.endswith(b"\n"):
            ready, _, _ = select.select([read_fd], [], [], 10)
            chunk = os.read(read_fd, 16) if ready else b""
            if not chunk:
                break
            number += chunk
    finally:
        os.close(read_fd)
    if not number.strip().isdigit():
        proc.terminate()
        proc.wait(5)
        yield False
        return
    os.environ["DISPLAY"] = f":{number.strip().decode()}"
    try:
        yield True
    finally:
        os.environ.pop("DISPLAY", None)
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


@contextmanager
def dedicated_manager(root):
    """A BrowserManager whose Intermarché tab is a dedicated visible Chromium (pytest fixtures).

    Skips (or fails with PRIXMALIN_REQUIRE_BROWSER=1) when no Chromium or display.
    """
    import asyncio

    import pytest

    from backend import config
    from backend.browser import BrowserManager, BrowserUnavailable
    from tests.conftest import browser_missing

    path = chrome_path()
    if path is None:
        browser_missing("Chromium introuvable pour la fenêtre Intermarché")
    with display() as available:
        if not available:
            browser_missing("pas d'écran pour la fenêtre Intermarché (installez Xvfb)")
        mp = pytest.MonkeyPatch()
        mp.setattr(config, "CHROME_PATH", path)
        mp.setattr(config, "CHROME_EXTRA_ARGS", sandbox_args())
        mp.setattr(config, "REAL_CHROME_STORES", ("intermarche",))
        manager = BrowserManager(root / "profile", real_chrome_dir=root)

        async def blank(page):
            return page.url

        try:
            try:
                asyncio.run(manager.run("intermarche", blank, timeout=60))
            except BrowserUnavailable as e:
                browser_missing(f"fenêtre Intermarché impossible : {e}")
            yield manager
        finally:
            asyncio.run(manager.shutdown())
            mp.undo()
