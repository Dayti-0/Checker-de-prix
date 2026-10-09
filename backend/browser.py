"""Single persistent browser shared by every scraper.

Playwright runs on a dedicated thread with its own event loop, so it works
whatever loop the web server uses (on Windows Playwright needs a Proactor loop
to start the browser process, which uvicorn does not always provide).

The browser keeps a persistent profile in ``data/browser-profile``: cookies,
anti-bot clearance and the store chosen on each retailer site survive restarts.
Each retailer gets its own tab, reused from one search to the next.
"""

import asyncio
import logging
import os
import random
import sys
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from backend import config
from backend.models import BrowserStatus

logger = logging.getLogger(__name__)

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-default-browser-check",
    "--no-first-run",
    "--lang=fr-FR",
]

USE_STEALTH = os.environ.get("PRIXMALIN_STEALTH", "1") != "0"


class BrowserUnavailable(Exception):
    """The browser could not be started (not installed, no display...)."""


class BrowserManager:
    def __init__(self, profile_dir: Path, channel: str = ""):
        self.profile_dir = profile_dir
        self.preferred_channel = channel
        self.show_browser = False
        self.setup_mode = False
        self.error: str | None = None

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._pw = None
        self._context = None
        self._channel: str | None = None
        self._headless = True
        self._ua_override: dict[str, str] = {}
        self._pages: dict[str, Any] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._launch_lock: asyncio.Lock | None = None
        self._last_request: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public API (call from any event loop)
    # ------------------------------------------------------------------

    async def run(
        self,
        key: str,
        fn: Callable[..., Awaitable[Any]],
        *args: Any,
        timeout: float | None = None,
    ) -> Any:
        """Run ``fn(page, *args)`` on the browser loop with the tab of ``key``.

        Calls for the same retailer are serialised and spaced out.
        """
        return await self._call(self._run_on_page, key, fn, args, timeout=timeout)

    async def open_setup(self, key: str | None, url: str) -> None:
        """Show the browser window on ``url`` so the user can act on the site."""
        await self._call(self._open_setup, key, url, timeout=60)

    async def end_setup(self) -> None:
        await self._call(self._end_setup, timeout=60)

    async def set_show_browser(self, show: bool) -> None:
        self.show_browser = show
        if self._context is not None and not self.setup_mode:
            await self._call(self._ensure_context, timeout=60)

    async def warmup(self, targets: dict[str, str]) -> None:
        """Start the browser and open the given ``{key: url}`` tabs in the background."""
        for key, url in targets.items():
            try:
                await self.run(key, _goto_if_blank, url, timeout=45)
            except Exception as e:  # warm-up is best effort
                logger.info("Warm-up %s failed: %s", key, e)

    def status(self) -> BrowserStatus:
        return BrowserStatus(
            running=self._context is not None,
            headless=self._headless,
            setup_mode=self.setup_mode,
            channel=self._channel,
            error=self.error,
        )

    async def shutdown(self) -> None:
        if self._loop is None:
            return
        try:
            await self._call(self._shutdown, timeout=15)
        except Exception as e:
            logger.debug("Browser shutdown: %s", e)
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        self._loop = None
        self._thread = None

    # ------------------------------------------------------------------
    # Thread / loop plumbing
    # ------------------------------------------------------------------

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if sys.platform == "win32":
            loop: asyncio.AbstractEventLoop = asyncio.ProactorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        ready = threading.Event()

        def run_loop() -> None:
            asyncio.set_event_loop(loop)
            loop.call_soon(ready.set)
            loop.run_forever()

        self._thread = threading.Thread(target=run_loop, name="prixmalin-browser", daemon=True)
        self._thread.start()
        ready.wait()
        self._loop = loop

    async def _call(self, fn: Callable[..., Awaitable[Any]], *args: Any, timeout: float | None = None) -> Any:
        self._ensure_thread()
        future = asyncio.wrap_future(asyncio.run_coroutine_threadsafe(fn(*args), self._loop))
        if timeout is None:
            return await future
        return await asyncio.wait_for(future, timeout)

    # ------------------------------------------------------------------
    # Everything below runs on the browser loop
    # ------------------------------------------------------------------

    async def _run_on_page(self, key: str, fn: Callable[..., Awaitable[Any]], args: tuple) -> Any:
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            page = await self._get_page(key)
            last = self._last_request.get(key)
            if last is not None:
                wait = config.MIN_REQUEST_INTERVAL_SECONDS + random.uniform(0, 0.5) - (time.monotonic() - last)
                if wait > 0:
                    await asyncio.sleep(wait)
            try:
                return await fn(page, *args)
            finally:
                self._last_request[key] = time.monotonic()

    async def _ensure_context(self):
        want_headless = not (self.show_browser or self.setup_mode)
        if self._context is not None and self._headless == want_headless:
            return self._context
        if self._launch_lock is None:
            self._launch_lock = asyncio.Lock()
        async with self._launch_lock:
            if self._context is not None and self._headless == want_headless:
                return self._context
            await self._close_context()
            try:
                self._context = await self._launch(want_headless)
            except BrowserUnavailable as e:
                self.error = str(e)
                raise
            self._headless = want_headless
            self.error = None
            return self._context

    async def _launch(self, headless: bool):
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise BrowserUnavailable(
                "Playwright n'est pas installé : pip install -r requirements.txt"
            ) from e

        if self._pw is None:
            self._pw = await async_playwright().start()
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        channels = [self.preferred_channel] if self.preferred_channel else ["chrome", "msedge", "chromium"]
        if self._channel in channels:  # keep the channel that already worked
            channels.remove(self._channel)
            channels.insert(0, self._channel)

        last_error: Exception | None = None
        for channel in channels:
            try:
                context = await self._launch_channel(channel, headless)
            except Exception as e:
                last_error = e
                message = str(e)
                if not headless and ("XServer" in message or "DISPLAY" in message or "display" in message):
                    raise BrowserUnavailable(
                        "Impossible d'afficher la fenêtre du navigateur sur cette machine (pas d'écran)."
                    ) from e
                logger.info("Browser channel %s unavailable: %s", channel, message.splitlines()[0])
                continue
            self._channel = channel
            logger.info("Browser started (%s, %s)", channel, "headless" if headless else "visible")
            return context

        raise BrowserUnavailable(
            "Aucun navigateur utilisable. Installez Chromium avec : python -m playwright install chromium"
            + (f" ({str(last_error).splitlines()[0]})" if last_error else "")
        )

    async def _launch_channel(self, channel: str, headless: bool):
        options: dict[str, Any] = {
            "headless": headless,
            "channel": channel,
            "args": LAUNCH_ARGS,
            "ignore_default_args": ["--enable-automation"],
            "locale": "fr-FR",
            "timezone_id": "Europe/Paris",
        }
        if headless:
            options["viewport"] = {"width": 1366, "height": 900}
        else:
            options["no_viewport"] = True
        if channel in self._ua_override:
            options["user_agent"] = self._ua_override[channel]

        context = await self._pw.chromium.launch_persistent_context(str(self.profile_dir), **options)

        if headless and channel not in self._ua_override:
            # Headless Chrome announces itself as "HeadlessChrome": sites like
            # Carrefour reject it outright. Relaunch with the regular user agent.
            page = context.pages[0] if context.pages else await context.new_page()
            user_agent = await page.evaluate("navigator.userAgent")
            if "HeadlessChrome" in user_agent:
                await context.close()
                self._ua_override[channel] = user_agent.replace("HeadlessChrome", "Chrome")
                return await self._launch_channel(channel, headless)

        if USE_STEALTH:
            try:
                from playwright_stealth import Stealth

                options = {"navigator_languages_override": ("fr-FR", "fr")}
                if sys.platform != "win32":
                    # The platform patch claims Windows: only true on Windows
                    options.update(navigator_platform=False, navigator_platform_override=None)
                await Stealth(**options).apply_stealth_async(context)
            except Exception as e:  # optional dependency
                logger.debug("Stealth not applied: %s", e)

        context.set_default_timeout(20000)
        context.on("close", lambda *_: self._on_context_closed(context))
        self._pages = {}
        return context

    def _on_context_closed(self, context) -> None:
        # Also triggered when the user closes the visible window. Ignore the
        # late event of a context that was already replaced by a relaunch.
        if self._context is context:
            self._context = None
            self._pages = {}

    async def _get_page(self, key: str):
        context = await self._ensure_context()
        page = self._pages.get(key)
        if page is not None and not page.is_closed():
            return page
        used = set(self._pages.values())
        blank = next((p for p in context.pages if p not in used and p.url == "about:blank"), None)
        page = blank or await context.new_page()
        self._pages[key] = page
        return page

    async def _open_setup(self, key: str | None, url: str) -> None:
        self.setup_mode = True
        try:
            await self._ensure_context()
        except BrowserUnavailable:
            # No window can be shown: keep searching in the background
            self.setup_mode = False
            raise
        lock = self._locks.setdefault(key or "_setup", asyncio.Lock())
        async with lock:
            page = await self._get_page(key or "_setup")
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.bring_to_front()

    async def _end_setup(self) -> None:
        self.setup_mode = False
        if self._context is not None:
            await self._ensure_context()

    async def _close_context(self) -> None:
        context, self._context = self._context, None
        self._pages = {}
        if context is not None:
            try:
                await context.close()
            except Exception as e:
                logger.debug("Context close: %s", e)

    async def _shutdown(self) -> None:
        await self._close_context()
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None


async def _goto_if_blank(page, url: str) -> None:
    if page.url in ("", "about:blank"):
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)


browser = BrowserManager(config.BROWSER_PROFILE_DIR, config.BROWSER_CHANNEL)
