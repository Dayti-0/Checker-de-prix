"""Browsers of PrixMalin: one shared browser, plus a dedicated Chrome window for Intermarché.

Playwright runs on a dedicated thread with its own event loop, so it works
whatever loop the web server uses (on Windows Playwright needs a Proactor loop
to start the browser process, which uvicorn does not always provide). Do not
change that plumbing.

**Shared browser** (Aldi, Lidl, Carrefour, Courses U): persistent profile
``data/browser-profile`` (cookies, anti-bot clearance and stores chosen on the
sites survive restarts), invisible ("new" headless with the user agent of a
regular Chrome, playwright-stealth) unless the user shows it. One tab per
retailer, reused from one search to the next.

**Dedicated window** (``config.REAL_CHROME_STORES``, Intermarché by default):
the Google Chrome installed on the PC (else Edge), started as a plain process
with its own profile ``data/chrome-intermarche`` and driven by patchright over
CDP, without stealth script or any override (backend/real_chrome.py). Never
headless: started minimized by a search, shown by « Ouvrir le site ». The
shared browser never opens intermarche.com (``PRIXMALIN_REAL_CHROME=`` empty
goes back to the shared browser for every retailer).

**Calls** (``run``):

- one at a time per retailer; the waiting ones by priority (``interactive`` >
  ``basket`` > ``background``) then arrival, at most ``QUEUE_TIMEOUT_SECONDS``
  in the queue; ``timeout`` only covers the work (starting the browser included);
- spaced out: ``MIN_REQUEST_INTERVAL_SECONDS`` (``REQUEST_INTERVAL_SECONDS`` for
  Intermarché) plus 0 to 0.5 s;
- none at all to a retailer paused after a hard block (services/circuit.py);
- cancelled on the browser loop when the caller is (client of the API gone).

Starting, relaunching and stopping the browser run in their own task: a caller
that gives up (timeout) never stops them halfway.
"""

import asyncio
import contextlib
import json
import logging
import os
import random
import re
import sys
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend import config
from backend.errors import short_error
from backend.models import BrowserStatus, RetailerWindow
from backend.scrapers.base import BlockedError, HardBlockError
from backend.scrapers.common import detect_block, hard_block_message
from backend.services.circuit import HardBlocks

logger = logging.getLogger("prixmalin.browser")

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-default-browser-check",
    "--no-first-run",
    "--lang=fr-FR",
]

USE_STEALTH = os.environ.get("PRIXMALIN_STEALTH", "1") != "0"

# Browsers tried in turn when PRIXMALIN_BROWSER is not set: the installed Chrome,
# then Edge, then the Chromium downloaded by Playwright
CHANNEL_ORDER = ("chrome", "msedge", "chromium")

# python <args> downloads the Chromium of Playwright
PLAYWRIGHT_INSTALL_ARGS = ("-m", "playwright", "install", "chromium")

# Priorities of browser.run, highest first: a search typed by the user, a
# basket comparison, background work (refresh, alerts)
PRIORITIES = ("interactive", "basket", "background")

PROFILE_IN_USE = "Le profil du navigateur PrixMalin est déjà utilisé (une autre fenêtre PrixMalin est-elle ouverte ?)"
_PROFILE_LOCKED = re.compile(
    r"ProcessSingleton|profile (directory )?(is|appears to be) (already )?in use|already running for", re.I
)

# Invisible tabs where images, media, fonts and ads are not loaded (never
# Intermarché nor Carrefour: their anti-bot scripts would notice)
LIGHT_STORES = ("aldi", "coursesu")
LIGHT_RESOURCE_TYPES = ("image", "media", "font")
AD_DOMAINS = (
    "doubleclick.net",
    "googlesyndication.com",
    "googleadservices.com",
    "adnxs.com",
    "criteo.com",
    "criteo.net",
    "taboola.com",
    "outbrain.com",
    "hotjar.com",
    "facebook.net",
)

# Cookies of the Intermarché sessions of the shared profile (flagged by
# DataDome), removed once: Intermarché now has its own Chrome profile
_OLD_SESSION_COOKIES = re.compile(r"(^|\.)(intermarche\.com|captcha-delivery\.com)$")
OLD_SESSION_MARK = "prixmalin-intermarche-oublie.txt"


class BrowserUnavailable(Exception):
    """The browser could not be started (not installed, no display...)."""


class QueueTimeout(TimeoutError):
    """Waited too long for the tab of a retailer (other searches before this one)."""


def is_profile_locked(message: str) -> bool:
    """Chrome refused the profile: another browser uses it (another PrixMalin?)."""
    return bool(_PROFILE_LOCKED.search(message or ""))


def is_light_blocked(resource_type: str, url: str) -> bool:
    """Request not loaded by an invisible Aldi or Courses U tab (``PRIXMALIN_LIGHT=0`` loads all)."""
    if resource_type in LIGHT_RESOURCE_TYPES:
        return True
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in AD_DOMAINS)


async def _light_route(route) -> None:
    request = route.request
    if is_light_blocked(request.resource_type, request.url):
        await route.abort("blockedbyclient")
    else:
        await route.fallback()


_background: set[asyncio.Task] = set()


def _keep(task: asyncio.Task) -> asyncio.Task:
    """Keep a reference to ``task`` until it ends, and mark its error as seen."""
    _background.add(task)

    def done(t: asyncio.Task) -> None:
        _background.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.debug("Background task failed: %s", t.exception())

    task.add_done_callback(done)
    return task


class _Slot:
    """The tab of one retailer: one call at a time, the others wait by priority, then arrival."""

    def __init__(self) -> None:
        self.busy = False
        self._waiting: list[tuple[int, int, asyncio.Future]] = []
        self._count = 0

    @property
    def waiting(self) -> int:
        return len(self._waiting)

    async def acquire(self, rank: int, timeout: float | None) -> None:
        if not self.busy:
            self.busy = True
            return
        self._count += 1
        entry = (rank, self._count, asyncio.get_running_loop().create_future())
        self._waiting.append(entry)
        try:
            await asyncio.wait_for(asyncio.shield(entry[2]), timeout)
        except BaseException as e:
            if entry in self._waiting:
                self._waiting.remove(entry)
                entry[2].cancel()
            elif entry[2].done() and not entry[2].cancelled():
                self.release()  # handed over just as this call gave up: pass it on
            if isinstance(e, TimeoutError):
                raise QueueTimeout from None
            raise

    def release(self) -> None:
        if self._waiting:
            entry = min(self._waiting)  # priority, then arrival (counts are unique)
            self._waiting.remove(entry)
            entry[2].set_result(None)  # stays busy: handed over
        else:
            self.busy = False


class BrowserManager:
    def __init__(
        self,
        profile_dir: Path,
        channel: str = "",
        *,
        real_chrome_dir: Path | None = None,
        persist: bool = False,
    ) -> None:
        self.profile_dir = profile_dir
        self.preferred_channel = channel
        # Folder of the profiles of the dedicated windows (None: config.DATA_DIR)
        self.real_chrome_dir = real_chrome_dir
        # Save the hard blocks and the closing of the window by the user in the
        # database (the app's browser; not the browsers of the tests)
        self.persist = persist
        self.show_browser = False
        self.setup_mode = False
        self.setup_store: str | None = None
        self.closed_by_user = False
        self.error: str | None = None
        # Incremented each time a new browser context is started (tabs, cookies
        # in memory and page state are then new)
        self.context_generation = 0
        # Number of browser processes started (the user agent is remembered)
        self.launch_count = 0
        self.hard_blocks = HardBlocks(persist=persist)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._pw = None
        self._context = None
        self._channel: str | None = None
        self._headless = True
        # « Ouvrir le site » shows the shared browser (not for a dedicated window)
        self._shared_setup = False
        self._pages: dict[str, Any] = {}
        self._slots: dict[str, _Slot] = {}
        self._launch_task: asyncio.Task | None = None
        self._last_request: dict[str, float] = {}
        self._in_use = 0  # calls running in the shared browser
        self._idle: asyncio.Event | None = None
        self._real: dict[str, Any] = {}  # dedicated windows (RealChrome) by retailer
        # What happened on the browser loop and must be saved by the caller side
        self._pending: list[tuple] = []

    # ------------------------------------------------------------------
    # Public API (call from any event loop)
    # ------------------------------------------------------------------

    def is_dedicated(self, key: str | None) -> bool:
        """Retailer driven through its own Chrome window (Intermarché)."""
        return bool(key) and key in config.REAL_CHROME_STORES

    def dedicated_running(self, key: str) -> bool:
        real = self._real.get(key)
        return real is not None and real.running

    async def run(
        self,
        key: str,
        fn: Callable[..., Awaitable[Any]],
        *args: Any,
        timeout: float | None = None,
        priority: str = "interactive",
    ) -> Any:
        """Run ``fn(page, *args)`` on the browser loop with the tab of ``key``.

        ``timeout``: seconds for the work itself (``asyncio.TimeoutError``); the
        wait in the queue has its own limit (``QueueTimeout``). ``priority`` is
        one of PRIORITIES. Raises HardBlockError at once while the retailer is
        paused after a hard block.
        """
        if priority not in PRIORITIES:
            raise ValueError(f"unknown priority {priority!r}")
        await self.flush()
        await self._check_hard_block(key)
        try:
            return await self._submit(key, fn, args, timeout, priority)
        except HardBlockError as e:
            await self._record_hard_block(key, e)
            raise
        except BlockedError as e:
            await self.hard_blocks.blocked(key)
            e.recorded = True
            real = self._real.get(key)
            if real is not None:
                real.challenge_pending = True  # « Ouvrir le site » loads the page again
            raise

    async def open_setup(self, key: str | None, url: str) -> None:
        """Show the site of ``key`` so the user can act on it (« Ouvrir le site »)."""
        await self.flush()
        if key:
            await self._check_hard_block(key)
        kind = await self._call(self._protected, self._open_setup, key, url, timeout=90)
        if kind == "hard_block" and key:
            await self._record_hard_block(key, HardBlockError(label=self._label(key)), raise_it=True)

    async def end_setup(self) -> str | None:
        """« J'ai terminé »: back to the invisible browser; returns the retailer that was shown."""
        await self.flush()
        store, kind = await self._call(self._protected, self._end_setup, timeout=config.QUEUE_TIMEOUT_SECONDS + 60)
        if kind == "hard_block" and store:
            await self._record_hard_block(store, HardBlockError(label=self._label(store)), raise_it=True)
        return store

    async def set_show_browser(self, show: bool) -> None:
        self.show_browser = show
        if show:
            self.closed_by_user = False
        if self._context is not None:
            # Waits for the searches running in the window (they never fail for it)
            await self._call(self._protected, self._ensure_context, timeout=config.QUEUE_TIMEOUT_SECONDS + 60)

    async def warmup(self, targets: dict[str, str]) -> None:
        """Start the browser and open the given ``{key: url}`` tabs in the background."""
        for key, url in targets.items():
            try:
                await self.run(key, _goto_if_blank, url, timeout=45, priority="background")
            except Exception as e:  # noqa: BLE001 (warm-up is best effort)
                logger.info("Warm-up %s failed: %s", key, short_error(e))

    async def reset_tab(self, key: str) -> None:
        """Close the tab of ``key``: the next call gets a fresh one (shared browser only)."""
        if self._loop is not None and not self.is_dedicated(key):
            await self._call(self._reset_tab, key, timeout=15)

    async def flush(self) -> None:
        """Save what happened in the browser (window closed by the user)."""
        while self._pending:
            event = self._pending.pop(0)
            if not self.persist:
                continue
            try:
                await self._save_event(event)
            except Exception:  # noqa: BLE001 (the state in memory is right anyway)
                logger.exception("Browser event %s not saved", event)

    def status(self) -> BrowserStatus:
        return BrowserStatus(
            running=self._context is not None,
            headless=self._headless,
            setup_mode=self.setup_mode,
            channel=self._channel,
            error=self.error,
            closed_by_user=self.closed_by_user,
            setup_store=self.setup_store if self.setup_mode else None,
            windows=[self._window_status(key) for key in config.REAL_CHROME_STORES],
            blocked_until=self.hard_blocks.active(),
        )

    async def shutdown(self) -> None:
        if self._loop is None:
            return
        try:
            await self._call(self._protected, self._shutdown, timeout=30)
        except Exception as e:  # noqa: BLE001 (stopping anyway)
            logger.debug("Browser shutdown: %s", e)
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        self._loop = None
        self._thread = None

    # ------------------------------------------------------------------
    # Caller side helpers
    # ------------------------------------------------------------------

    def _label(self, key: str) -> str:
        from backend.scrapers import SCRAPERS

        scraper = SCRAPERS.get(key)
        return scraper.label if scraper else key

    async def _check_hard_block(self, key: str) -> None:
        until = await self.hard_blocks.until(key)
        if until:
            label = self._label(key)
            raise HardBlockError(hard_block_message(label, until), retry_after=until, label=label)

    async def _record_hard_block(self, key: str, error: HardBlockError, raise_it: bool = False) -> None:
        """Start the pause of ``key`` after a hard block seen on its site (message with its end)."""
        if error.retry_after is None:
            record = await self.hard_blocks.hard_block(key)
            error.retry_after = record.until
            error.args = (hard_block_message(error.label or self._label(key), record.until),)
        if raise_it:
            raise error

    async def _save_event(self, event: tuple) -> None:
        from backend.repos import cache
        from backend.services import settings

        kind, *data = event
        if kind == "closed":
            was_shown, store = data
            if was_shown:
                await settings.set_show_browser(False)
            if store and store != "_setup":
                await cache.clear_cache(f"{store}|")
        elif kind == "window_closed":
            await cache.clear_cache(f"{data[0]}|")

    async def _submit(self, key: str, fn, args: tuple, timeout: float | None, priority: str) -> Any:
        self._ensure_thread()
        coro = self._run_on_page(key, fn, args, timeout, priority)
        future = asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coro, self._loop))
        if timeout is None:
            return await future
        # Safety net: the browser loop enforces the limits of the queue and of the work
        return await asyncio.wait_for(future, config.QUEUE_TIMEOUT_SECONDS + timeout + 60)

    def _window_status(self, key: str) -> RetailerWindow:
        real = self._real.get(key)
        window = RetailerWindow(store=key, label=self._label(key))
        if real is not None:
            window.running = real.running
            window.browser = real.name
            window.error = real.error
            window.closed_by_user = real.closed_by_user
        return window

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

    async def _protected(self, fn: Callable[..., Awaitable[Any]], *args: Any) -> Any:
        """``fn(*args)`` in its own task: a caller that gives up does not stop it halfway."""
        return await asyncio.shield(_keep(asyncio.get_running_loop().create_task(fn(*args))))

    def _slot(self, key: str) -> _Slot:
        return self._slots.setdefault(key, _Slot())

    async def _run_on_page(
        self,
        key: str,
        fn: Callable[..., Awaitable[Any]],
        args: tuple,
        timeout: float | None = None,
        priority: str = "interactive",
    ) -> Any:
        slot = self._slot(key)
        await slot.acquire(PRIORITIES.index(priority), config.QUEUE_TIMEOUT_SECONDS)
        try:
            await self._pace(key)
            if timeout is None:
                return await self._work(key, fn, args)
            return await asyncio.wait_for(self._work(key, fn, args), timeout)
        finally:
            self._last_request[key] = time.monotonic()
            slot.release()

    async def _pace(self, key: str) -> None:
        last = self._last_request.get(key)
        if last is None:
            return
        interval = config.REQUEST_INTERVAL_SECONDS.get(key, config.MIN_REQUEST_INTERVAL_SECONDS)
        jitter = random.uniform(0, 0.5)  # noqa: S311 (not cryptographic)
        wait = interval + jitter - (time.monotonic() - last)
        if wait > 0:
            await asyncio.sleep(wait)

    async def _work(self, key: str, fn: Callable[..., Awaitable[Any]], args: tuple) -> Any:
        page = await self._get_page(key)
        if self.is_dedicated(key):
            return await fn(page, *args)
        self._in_use += 1
        if self._idle is not None:
            self._idle.clear()
        try:
            return await fn(page, *args)
        finally:
            self._in_use -= 1
            if self._in_use == 0 and self._idle is not None:
                self._idle.set()

    async def _wait_idle(self, timeout: float) -> None:
        """Wait for the calls running in the shared browser (before closing it)."""
        if self._in_use == 0:
            return
        if self._idle is None:
            self._idle = asyncio.Event()
        try:
            await asyncio.wait_for(self._idle.wait(), timeout)
        except TimeoutError:
            logger.warning("Browser relaunched while %s searches were still running", self._in_use)

    # --- shared browser -------------------------------------------------------

    def _want_headless(self) -> bool:
        return not (self.show_browser or self._shared_setup)

    async def _ensure_context(self):
        """The shared context, (re)launched when missing or not in the wanted mode."""
        for _ in range(3):
            want = self._want_headless()
            task = self._launch_task
            if task is None or task.done():
                if self._context is not None and self._headless == want:
                    return self._context
                task = self._launch_task = _keep(asyncio.get_running_loop().create_task(self._relaunch(want)))
            # Shielded: a search that gives up does not stop the launch
            await asyncio.shield(task)
        if self._context is None:
            raise BrowserUnavailable(self.error or "Le navigateur n'a pas pu démarrer.")
        return self._context

    async def _relaunch(self, headless: bool) -> None:
        if self._context is not None:
            # The searches running in the window end first (B42)
            await self._wait_idle(config.QUEUE_TIMEOUT_SECONDS)
            await self._close_context()
        try:
            context = await self._launch(headless)
        except BrowserUnavailable as e:
            self.error = str(e)
            raise
        self._context = context
        self._headless = headless
        self._pages = {}
        self.context_generation += 1
        self.error = None
        context.on("close", lambda *_: self._on_context_closed(context))

    async def _launch(self, headless: bool):
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise BrowserUnavailable("Playwright n'est pas installé : pip install -r requirements.txt") from e

        if self._pw is None:
            self._pw = await async_playwright().start()
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        channels = [self.preferred_channel] if self.preferred_channel else list(CHANNEL_ORDER)
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
                if is_profile_locked(message):
                    # Another channel would hit the same lock: say it at once
                    logger.warning("Browser profile in use: %s", short_error(e))
                    raise BrowserUnavailable(PROFILE_IN_USE) from e
                if not headless and ("XServer" in message or "DISPLAY" in message or "display" in message):
                    raise BrowserUnavailable(
                        "Impossible d'afficher la fenêtre du navigateur sur cette machine (pas d'écran)."
                    ) from e
                logger.info("Browser channel %s unavailable: %s", channel, short_error(e))
                continue
            self._channel = channel
            logger.info("Browser started (%s, %s)", channel, "headless" if headless else "visible")
            return context

        raise BrowserUnavailable(
            "Aucun navigateur utilisable. Installez Chromium avec : python -m playwright install chromium"
            + (f" ({short_error(last_error)})" if last_error else "")
        )

    @property
    def _ua_path(self) -> Path:
        return self.profile_dir.parent / "browser-ua.json"

    def _ua_memo(self) -> dict:
        try:
            memo = json.loads(self._ua_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return memo if isinstance(memo, dict) else {}

    def _save_ua(self, channel: str, version: str | None, user_agent: str) -> None:
        memo = self._ua_memo()
        memo[channel] = {"version": version, "user_agent": user_agent}
        try:
            self._ua_path.write_text(json.dumps(memo, indent=2), encoding="utf-8")
        except OSError as e:
            logger.debug("User agent not saved: %s", e)

    async def _launch_channel(self, channel: str, headless: bool, *, use_memo: bool = True):
        options: dict[str, Any] = {
            "headless": headless,
            "channel": channel,
            "args": LAUNCH_ARGS,
            "ignore_default_args": ["--enable-automation"],
            "locale": "fr-FR",
            "timezone_id": "Europe/Paris",
        }
        memo = self._ua_memo().get(channel) if headless and use_memo else None
        if headless:
            options["viewport"] = {"width": 1366, "height": 900}
            if isinstance(memo, dict) and memo.get("user_agent"):
                # Remembered: no need to start the browser twice
                options["user_agent"] = memo["user_agent"]
        else:
            # A visible window keeps the real user agent of the browser
            options["no_viewport"] = True

        context = await self._pw.chromium.launch_persistent_context(str(self.profile_dir), **options)
        self.launch_count += 1
        try:
            if headless:
                version = context.browser.version if context.browser is not None else None
                if "user_agent" in options:
                    if version and memo.get("version") and memo["version"] != version:
                        # The browser was updated: read its user agent again
                        await context.close()
                        return await self._launch_channel(channel, headless, use_memo=False)
                else:
                    # Headless Chrome announces itself as "HeadlessChrome": sites like
                    # Carrefour reject it outright. Relaunch with the regular user agent.
                    page = context.pages[0] if context.pages else await context.new_page()
                    user_agent = await page.evaluate("navigator.userAgent")
                    if "HeadlessChrome" in user_agent:
                        self._save_ua(channel, version, user_agent.replace("HeadlessChrome", "Chrome"))
                        await context.close()
                        return await self._launch_channel(channel, headless)
            await self._apply_stealth(context)
            await self._forget_old_sessions(context)
            context.set_default_timeout(20000)
            return context
        except BaseException:
            # Never leave a half-launched browser behind (B43)
            with contextlib.suppress(Exception):
                await context.close()
            raise

    async def _apply_stealth(self, context) -> None:
        if not USE_STEALTH:
            return
        try:
            from playwright_stealth import Stealth

            options: dict[str, Any] = {"navigator_languages_override": ("fr-FR", "fr")}
            if sys.platform != "win32":
                # The platform patch claims Windows: only true on Windows
                options.update(navigator_platform=False, navigator_platform_override=None)
            await Stealth(**options).apply_stealth_async(context)
        except Exception as e:  # noqa: BLE001 (optional dependency)
            logger.debug("Stealth not applied: %s", e)

    async def _forget_old_sessions(self, context) -> None:
        """Remove once the Intermarché (DataDome) cookies left in the shared profile."""
        mark = self.profile_dir / OLD_SESSION_MARK
        if mark.exists():
            return
        try:
            await context.clear_cookies(domain=_OLD_SESSION_COOKIES)
            mark.write_text(
                "Cookies Intermarché effacés de ce profil : Intermarché a maintenant sa propre fenêtre Chrome.\n",
                encoding="utf-8",
            )
            logger.info("Old Intermarché cookies removed from the shared profile")
        except Exception as e:  # noqa: BLE001 (tried again at the next launch)
            logger.debug("Old cookies not removed: %s", e)

    def _on_context_closed(self, context) -> None:
        # Ignore the late event of a context that PrixMalin closed or replaced itself
        if self._context is not context:
            return
        # Closed by the user (visible window closed) or the browser crashed (B42)
        visible = not self._headless
        store = self.setup_store if self._shared_setup else None
        self._context = None
        self._pages = {}
        self.context_generation += 1
        self.closed_by_user = visible
        self._pending.append(("closed", self.show_browser, store))
        self.show_browser = False
        if self._shared_setup:
            self._shared_setup = False
            self.setup_mode = False
            self.setup_store = None
        logger.info("The PrixMalin browser was closed (%s)", "visible window" if visible else "invisible")

    async def _get_page(self, key: str):
        if self.is_dedicated(key):
            return await self._dedicated_page(key)
        context = await self._ensure_context()
        page = self._pages.get(key)
        if page is not None and not page.is_closed():
            return page
        used = set(self._pages.values())
        blank = next((p for p in context.pages if p not in used and p.url == "about:blank"), None)
        page = blank or await context.new_page()
        if config.LIGHT_MODE and self._headless and key in LIGHT_STORES:
            await page.route("**/*", _light_route)
        self._pages[key] = page
        return page

    async def _reset_tab(self, key: str) -> None:
        page = self._pages.pop(key, None)
        if page is not None and not page.is_closed():
            with contextlib.suppress(Exception):
                await page.close()

    async def _close_context(self) -> None:
        context, self._context = self._context, None
        self._pages = {}
        if context is not None:
            try:
                await context.close()
            except Exception as e:  # noqa: BLE001 (already closed by the user)
                logger.debug("Context close: %s", e)

    # --- dedicated windows ------------------------------------------------------

    def _real_chrome(self, key: str):
        real = self._real.get(key)
        if real is None:
            from backend.real_chrome import RealChrome
            from backend.scrapers import SCRAPERS

            host = urlparse(SCRAPERS[key].home_url).hostname or key
            domain = host[4:] if host.startswith("www.") else host
            root = self.real_chrome_dir
            profile = root / f"chrome-{key}" if root is not None else config.real_chrome_profile_dir(key)
            real = self._real[key] = RealChrome(key, domain, profile, on_closed=self._on_window_closed)
        return real

    async def _dedicated_page(self, key: str):
        from backend.real_chrome import ChromeUnavailable

        try:
            return await self._real_chrome(key).page(minimized=True)
        except ChromeUnavailable as e:
            raise BrowserUnavailable(str(e)) from e

    def _on_window_closed(self, key: str) -> None:
        if self.setup_store == key:
            self.setup_mode = False
            self.setup_store = None
            self._pending.append(("window_closed", key))

    # --- « Ouvrir le site » / « J'ai terminé » ---------------------------------

    async def _open_setup(self, key: str | None, url: str) -> str | None:
        """Show ``url``; returns the kind of anti-robot page shown by a dedicated window."""
        if self.is_dedicated(key):
            return await self._open_dedicated(key, url)
        self._shared_setup = True
        self.setup_mode = True
        self.setup_store = key or "_setup"
        self.closed_by_user = False
        try:
            await self._ensure_context()
        except BrowserUnavailable:
            # No window can be shown: keep searching in the background
            self._shared_setup = self.setup_mode = False
            self.setup_store = None
            raise
        tab = key or "_setup"
        slot = self._slot(tab)
        await slot.acquire(0, config.QUEUE_TIMEOUT_SECONDS)
        try:
            page = await self._get_page(tab)
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.bring_to_front()
        finally:
            slot.release()
        return None

    async def _open_dedicated(self, key: str, url: str) -> str | None:
        from backend.real_chrome import ChromeUnavailable

        real = self._real_chrome(key)
        slot = self._slot(key)
        await slot.acquire(0, config.QUEUE_TIMEOUT_SECONDS)
        try:
            self.setup_mode = True
            self.setup_store = key
            try:
                page = await real.show(url, reload=real.challenge_pending)
            except ChromeUnavailable as e:
                self.setup_mode = False
                self.setup_store = None
                raise BrowserUnavailable(str(e)) from e
            kind = await detect_block(page)
            if kind == "hard_block":
                # Nothing to validate: the site refuses the connection for a while
                self.setup_mode = False
                self.setup_store = None
            return kind
        finally:
            self._last_request[key] = time.monotonic()
            slot.release()

    async def _end_setup(self) -> tuple[str | None, str | None]:
        store = self.setup_store
        was_shared = self._shared_setup
        self._shared_setup = self.setup_mode = False
        self.setup_store = None
        kind = None
        if was_shared and self._context is not None:
            await self._ensure_context()  # back to the invisible browser
        if store and self.is_dedicated(store):
            real = self._real.get(store)
            page = real.current_page() if real is not None else None
            if page is not None:
                # What the window shows now (no request to the site)
                kind = await detect_block(page)
                real.challenge_pending = kind == "captcha"
        return store, kind

    async def _shutdown(self) -> None:
        for real in list(self._real.values()):
            try:
                await real.close()
            except Exception as e:  # noqa: BLE001 (stopping anyway)
                logger.debug("Dedicated window close: %s", e)
        await self._close_context()
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None


async def _goto_if_blank(page, url: str) -> None:
    if page.url in ("", "about:blank"):
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)


browser = BrowserManager(config.BROWSER_PROFILE_DIR, config.BROWSER_CHANNEL, persist=True)
