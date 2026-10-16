"""Dedicated real Chrome window for a retailer protected by DataDome (Intermarché, E.Leclerc).

DataDome tells an automated browser from a person's browser. PrixMalin's shared
browser (Playwright + playwright-stealth, headless) is easy to spot, so the
retailers of ``config.REAL_CHROME_STORES`` get their own window instead:

- the Google Chrome installed on the PC (else Microsoft Edge) is started as a
  plain process, exactly like the user would, with only::

      --remote-debugging-address=127.0.0.1 --remote-debugging-port=<free port>
      --user-data-dir=data/chrome-<key> --no-first-run --no-default-browser-check

  (plus ``--start-minimized`` when PrixMalin starts it for a search, a switch
  Chrome ignores: the window is minimized through CDP right after start):
  never headless, no stealth script, no user agent, language or window size
  change;
- the port is a free port chosen by PrixMalin, remembered in
  ``<profile>/PrixMalinDebugPort``. Not ``--remote-debugging-port=0``: Chrome
  then sets ``navigator.webdriver`` to true (measured on Chromium 141), the
  first thing an anti-robot script reads;
- PrixMalin attaches with patchright's ``connect_over_cdp`` (a Playwright that
  does not send ``Runtime.enable``) and uses the first browser context and the
  tab already open;
- the window and its tab are kept from one search to the next, and a Chrome
  still open when PrixMalin restarts is reused. A search never brings the
  window to the front; « Ouvrir le site » shows it normally.

Everything here runs on the browser thread (backend/browser.py).
"""

import asyncio
import contextlib
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from backend import config

logger = logging.getLogger("prixmalin.real_chrome")


def _of(label: str) -> str:
    """« d'Intermarché », « d'E.Leclerc », « de Courses U »."""
    return f"d'{label}" if label[:1].upper() in "AEIOUYÉÈ" else f"de {label}"


def chrome_missing(label: str) -> str:
    return (
        f"{label} nécessite Google Chrome ou Microsoft Edge installé sur l'ordinateur. "
        "Installez Google Chrome puis relancez PrixMalin."
    )


def patchright_missing(label: str) -> str:
    return f"Il manque un composant de PrixMalin pour {label} (patchright) : relancez lancer.bat pour l'installer."


def start_failed(label: str) -> str:
    return f"La fenêtre Chrome {_of(label)} n'a pas pu démarrer. Fermez-la si elle est ouverte, puis réessayez."


def already_open(label: str) -> str:
    return f"Une fenêtre Chrome {_of(label)} est déjà ouverte sans PrixMalin. Fermez-la, puis relancez la recherche."


# Messages of the Intermarché window (kept for the callers of P3)
CHROME_MISSING = chrome_missing("Intermarché")
PATCHRIGHT_MISSING = patchright_missing("Intermarché")
START_FAILED = start_failed("Intermarché")
ALREADY_OPEN = already_open("Intermarché")

# Seconds given to Chrome to open its debugging port
START_TIMEOUT_SECONDS = 30.0


class ChromeUnavailable(Exception):
    """The dedicated window cannot be used (no Chrome, start failed...): French message."""


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def chrome_candidates(platform: str, env: Mapping[str, str]) -> list[tuple[str, str]]:
    """Usual places of Chrome, then Edge: ``[(path, name), ...]`` in the order tried."""
    if platform == "win32":
        program_files = env.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = env.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = env.get("LOCALAPPDATA", "")
        chrome = r"Google\Chrome\Application\chrome.exe"
        edge = r"Microsoft\Edge\Application\msedge.exe"
        bases = [program_files, program_files_x86] + ([local] if local else [])
        return [(f"{base}\\{chrome}", "Google Chrome") for base in bases] + [
            (f"{base}\\{edge}", "Microsoft Edge") for base in (program_files_x86, program_files)
        ]
    if platform == "darwin":
        return [
            ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "Google Chrome"),
            ("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "Microsoft Edge"),
        ]
    return [
        ("google-chrome", "Google Chrome"),
        ("google-chrome-stable", "Google Chrome"),
        ("chromium", "Chromium"),
        ("chromium-browser", "Chromium"),
        ("microsoft-edge", "Microsoft Edge"),
    ]


def browser_name(path: str) -> str:
    lowered = path.lower()
    if "edge" in lowered:
        return "Microsoft Edge"
    if "chromium" in lowered or "chrome-linux" in lowered:
        return "Chromium"
    return "Google Chrome"


def name_from_user_agent(user_agent: str) -> str | None:
    """Browser named by the user agent of ``/json/version`` (Edge adds « Edg/ »)."""
    if "Edg/" in user_agent:
        return "Microsoft Edge"
    if "Chrome/" in user_agent:
        return "Google Chrome"
    return None


def find_chrome(
    configured: str = "",
    platform: str = sys.platform,
    env: Mapping[str, str] | None = None,
    exists: Callable[[str], bool] = os.path.isfile,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[str, str] | None:
    """``(path, name)`` of the browser to start, or None when none is installed.

    ``configured`` (PRIXMALIN_CHROME_PATH) wins when the file exists.
    """
    env = os.environ if env is None else env
    if configured:
        return (configured, browser_name(configured)) if exists(configured) else None
    for path, name in chrome_candidates(platform, env):
        if platform in ("win32", "darwin"):
            if exists(path):
                return path, name
        else:
            found = which(path)
            if found:
                return found, name
    if platform == "win32":
        return _registry_chrome()
    return None


def _registry_chrome() -> tuple[str, str] | None:  # pragma: no cover (Windows only)
    try:
        import winreg
    except ImportError:
        return None
    for exe, name in (("chrome.exe", "Google Chrome"), ("msedge.exe", "Microsoft Edge")):
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as key:
                    path = winreg.QueryValue(key, None)
            except OSError:
                continue
            if path and os.path.isfile(path):
                return path, name
    return None


PORT_FILE = "PrixMalinDebugPort"


def parse_port_file(text: str) -> int | None:
    """Port saved in ``<profile>/PrixMalinDebugPort`` (also reads Chrome's DevToolsActivePort)."""
    first = (text or "").strip().splitlines()[:1]
    if not first or not first[0].strip().isdigit():
        return None
    port = int(first[0].strip())
    return port if 0 < port < 65536 else None


def free_port() -> int:
    """A TCP port of 127.0.0.1 nobody listens on (Chrome opens its debugging port there)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def launch_args(path: str, profile: Path, port: int, *, minimized: bool, extra: tuple[str, ...] = ()) -> list[str]:
    """Command line of the dedicated Chrome: nothing that a person's Chrome would not have."""
    args = [
        path,
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if minimized:
        args.append("--start-minimized")
    return [*args, *extra, "about:blank"]


def on_site(url: str, domain: str) -> bool:
    host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
    return host == domain or host.endswith("." + domain)


def _mark_seen(task: asyncio.Task) -> None:
    """Retrieve the error of a start nobody waits for any more (no « never retrieved » warning)."""
    if not task.cancelled():
        error = task.exception()
        if error is not None:
            logger.debug("Dedicated Chrome start failed: %s", error)


def _wait_process(proc: subprocess.Popen, timeout: float = 5) -> None:
    try:
        proc.wait(timeout)
    except subprocess.TimeoutExpired:
        proc.kill()


def _get_json(url: str, timeout: float = 2.0) -> Any:
    # No proxy: 127.0.0.1 only
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as response:  # noqa: S310 (fixed http://127.0.0.1 URL)
        return json.loads(response.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------


class RealChrome:
    """The dedicated Chrome window of one retailer (``key``, site ``domain``, name ``label``)."""

    def __init__(
        self,
        key: str,
        domain: str,
        profile_dir: Path | None = None,
        on_closed: Callable[[str], None] | None = None,
        label: str | None = None,
    ) -> None:
        self.key = key
        self.domain = domain
        self.label = label or key
        self.profile_dir = profile_dir or config.real_chrome_profile_dir(key)
        self.name: str | None = None  # "Google Chrome", "Microsoft Edge"
        self.error: str | None = None
        self.closed_by_user = False
        # The site asked for a check through its API: « Ouvrir le site » reloads it
        self.challenge_pending = False
        self._on_closed = on_closed
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._proc: subprocess.Popen | None = None
        self._reused_name: str | None = None
        # Start (or reuse) of Chrome under way, shared by the calls that need it
        self._start_task: asyncio.Task | None = None
        self._closing = False

    @property
    def running(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    # --- public, on the browser loop ---------------------------------------

    async def page(self, *, minimized: bool = True):
        """The tab used for the searches (Chrome is started minimized when needed)."""
        await self._ensure(minimized=minimized)
        return await self._pick_page(minimized=minimized)

    async def show(self, url: str, *, reload: bool = False):
        """Show the window on the site (« Ouvrir le site »); returns the tab.

        The page is loaded only when it is not on the site yet, or when
        ``reload`` (the site asked for a check that only a fresh page shows).
        """
        await self._ensure(minimized=False)
        page = await self._pick_page()
        # Also a window started (minimized) for a search that was still starting
        await self._restore_window(page)
        if reload or not on_site(page.url, self.domain):
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.bring_to_front()
        self.challenge_pending = False
        return page

    async def close(self) -> None:
        """Close the window (when PrixMalin stops)."""
        self._closing = True
        try:
            task = self._start_task
            if task is not None and not task.done():
                # Let a start under way end (the window and its connection are then closed)
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(asyncio.shield(task), 20)
            if self._browser is not None and self._browser.is_connected():
                try:
                    session = await self._browser.new_browser_cdp_session()
                    await asyncio.wait_for(session.send("Browser.close"), 5)
                except Exception as e:  # noqa: BLE001 (already closed)
                    logger.debug("Browser.close: %s", e)
                try:
                    await asyncio.wait_for(self._browser.close(), 5)
                except Exception as e:  # noqa: BLE001
                    logger.debug("disconnect: %s", e)
            if self._proc is not None:
                try:
                    await asyncio.to_thread(self._proc.wait, 5)
                except subprocess.TimeoutExpired:
                    self._proc.terminate()
            if self._pw is not None:
                await self._pw.stop()
        finally:
            self._pw = None
            self._reset()
            self._proc = None
            self._closing = False

    def current_page(self):
        """The tab used last, when the window is still open (no request to the site)."""
        if not self.running or self._page is None or self._page.is_closed():
            return None
        return self._page

    # --- start or reuse Chrome ----------------------------------------------

    async def _ensure(self, *, minimized: bool) -> None:
        """Start or reuse Chrome, in a task of its own shared by the calls that need it.

        A search that gives up meanwhile (client gone, time limit) never stops
        the start halfway: the window started for it is still minimized, and
        its connection kept for the next search (B43).
        """
        if self.running:
            return
        task = self._start_task
        if task is None or task.done():
            task = self._start_task = asyncio.get_running_loop().create_task(self._start_once(minimized))
            task.add_done_callback(_mark_seen)
        await asyncio.shield(task)

    async def _start_once(self, minimized: bool) -> None:
        if self.running:
            return
        try:
            await self._connect(minimized)
        except ChromeUnavailable as e:
            self.error = str(e)
            raise
        self.error = None
        self.closed_by_user = False

    async def _connect(self, minimized: bool) -> None:
        profile = self.profile_dir
        endpoint = await self._running_endpoint(profile)
        spawned = endpoint is None
        if endpoint is None:
            found = find_chrome(config.CHROME_PATH)
            if found is None:
                raise ChromeUnavailable(chrome_missing(self.label))
            path, self.name = found
            profile.mkdir(parents=True, exist_ok=True)
            endpoint = await self._start(path, profile, minimized)
            logger.info("%s started for %s (%s)", self.name, self.key, "minimized" if minimized else "visible")
        else:
            self.name = self._reused_name or self.name or "Google Chrome"
            logger.info("Dedicated Chrome of %s reused", self.key)

        pw = await self._playwright()
        try:
            # no_defaults: no focus or media emulation on the profile's own context
            browser = await pw.chromium.connect_over_cdp(endpoint, timeout=20000, is_local=True, no_defaults=True)
        except Exception as e:
            logger.warning("connect_over_cdp failed: %s", e)
            raise ChromeUnavailable(start_failed(self.label)) from e
        if not browser.contexts:
            await browser.close()
            raise ChromeUnavailable(start_failed(self.label))
        self._browser = browser
        self._context = browser.contexts[0]  # the profile's own context: never new_context()
        self._context.set_default_timeout(20000)
        browser.on("disconnected", lambda *_: self._disconnected(browser))
        if spawned and minimized and self._context.pages:
            # Chrome has no real --start-minimized switch: the window is put in
            # the taskbar as soon as it exists, it never stays in front
            await self._set_window_state(self._context.pages[0], "minimized")

    async def _playwright(self):
        if self._pw is None:
            try:
                from patchright.async_api import async_playwright
            except ImportError as e:
                raise ChromeUnavailable(patchright_missing(self.label)) from e
            self._pw = await async_playwright().start()
        return self._pw

    def _spawn(self, args: list[str]) -> subprocess.Popen:
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if sys.platform == "win32":
            # Not a child of the PrixMalin console: closing it keeps Chrome open
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        try:
            return subprocess.Popen(args, **kwargs)  # noqa: S603 (path of the installed browser)
        except OSError as e:
            logger.warning("Chrome start failed: %s", e)
            raise ChromeUnavailable(start_failed(self.label)) from e

    async def _start(self, path: str, profile: Path, minimized: bool) -> str:
        """Start Chrome on a free port; returns its websocket URL."""
        for attempt in range(2):
            port = free_port()
            (profile / PORT_FILE).write_text(f"{port}\n", encoding="utf-8")
            proc = self._spawn(launch_args(path, profile, port, minimized=minimized, extra=config.CHROME_EXTRA_ARGS))
            try:
                endpoint = await self._wait_endpoint(port, proc)
            except ChromeUnavailable:
                if proc.poll() is None:
                    # Started but the port was taken meanwhile: try another one
                    proc.terminate()
                    await asyncio.to_thread(_wait_process, proc)
                    if attempt == 0:
                        continue
                raise
            self._proc = proc
            return endpoint
        raise ChromeUnavailable(start_failed(self.label))  # pragma: no cover (loop always returns or raises)

    async def _running_endpoint(self, profile: Path) -> str | None:
        """Websocket URL of a dedicated Chrome still open (PrixMalin restarted), else None."""
        for name in (PORT_FILE, "DevToolsActivePort"):
            try:
                port = parse_port_file((profile / name).read_text(encoding="utf-8"))
            except OSError:
                continue
            if port is not None:
                endpoint = await self._endpoint(port)
                if endpoint:
                    return endpoint
        return None

    async def _endpoint(self, port: int) -> str | None:
        try:
            version = await asyncio.to_thread(_get_json, f"http://127.0.0.1:{port}/json/version")
        except (OSError, ValueError):
            return None
        if not isinstance(version, dict):
            return None
        url = version.get("webSocketDebuggerUrl")
        if not isinstance(url, str) or not url.startswith(f"ws://127.0.0.1:{port}/"):
            return None
        self._reused_name = name_from_user_agent(str(version.get("User-Agent") or ""))
        return url

    async def _wait_endpoint(self, port: int, proc: subprocess.Popen) -> str:
        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        exited_at: float | None = None
        while time.monotonic() < deadline:
            endpoint = await self._endpoint(port)
            if endpoint:
                return endpoint
            if proc.poll() is not None:
                # Chrome handed the command line to a window already open with
                # this profile (opened without PrixMalin) and quit
                exited_at = exited_at or time.monotonic()
                if time.monotonic() - exited_at > 3:
                    message = already_open(self.label) if proc.returncode == 0 else start_failed(self.label)
                    raise ChromeUnavailable(message)
            await asyncio.sleep(0.1)
        raise ChromeUnavailable(start_failed(self.label))

    # --- tab and window -----------------------------------------------------

    async def _pick_page(self, *, minimized: bool = False):
        pages = [p for p in self._context.pages if not p.is_closed()]
        if self._page is not None and self._page in pages:
            return self._page
        site = next((p for p in pages if on_site(p.url, self.domain)), None)
        if site or pages:
            self._page = site or pages[0]
        else:
            # Every window was closed but Chrome kept running: the new tab opens
            # a window, put back in the taskbar for a search
            self._page = await self._context.new_page()
            if minimized:
                await self._set_window_state(self._page, "minimized")
        return self._page

    async def _restore_window(self, page) -> None:
        """Un-minimize the window (« Ouvrir le site » only, never for a search)."""
        await self._set_window_state(page, "normal", only_from=("minimized", "fullscreen"))

    async def window_state(self, page) -> str | None:
        """ "normal", "minimized", "maximized" or "fullscreen" (None when unknown)."""
        try:
            session = await self._context.new_cdp_session(page)
            try:
                window = await session.send("Browser.getWindowForTarget")
            finally:
                await session.detach()
        except Exception as e:  # noqa: BLE001
            logger.debug("window state: %s", e)
            return None
        return window.get("bounds", {}).get("windowState")

    async def _set_window_state(self, page, state: str, only_from: tuple[str, ...] | None = None) -> None:
        try:
            session = await self._context.new_cdp_session(page)
            try:
                window = await session.send("Browser.getWindowForTarget")
                current = window.get("bounds", {}).get("windowState")
                if current != state and (only_from is None or current in only_from):
                    await session.send(
                        "Browser.setWindowBounds",
                        {"windowId": window["windowId"], "bounds": {"windowState": state}},
                    )
            finally:
                await session.detach()
        except Exception as e:  # noqa: BLE001 (the window stays as it is)
            logger.debug("window %s: %s", state, e)

    def _disconnected(self, browser) -> None:
        if self._browser is not browser:
            return
        by_user = not self._closing
        self._reset()
        if by_user:
            # The user closed the window (or Chrome quit): started again at the next search
            self.closed_by_user = True
            logger.info("Dedicated Chrome of %s closed", self.key)
            if self._on_closed is not None:
                self._on_closed(self.key)

    def _reset(self) -> None:
        self._browser = None
        self._context = None
        self._page = None
