"""Playwright page helpers shared by the scrapers."""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from backend import config
from backend.scrapers.base import BlockedError, HardBlockError

logger = logging.getLogger(__name__)

_ACCEPT_COOKIES_JS = r"""
() => {
  const visible = (el) => el && el.offsetParent !== null;
  const ids = ['#onetrust-accept-btn-handler', '#didomi-notice-agree-button', '#popin_tc_privacy_button_2',
    '#footer_tc_privacy_button_2', '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
    'button[data-testid="uc-accept-all-button"]', '[data-testid="cookie-banner-accept"]'];
  for (const sel of ids) {
    const el = document.querySelector(sel);
    if (visible(el)) { el.click(); return sel; }
  }
  const re = /^(tout accepter|accepter tout|accepter et fermer|accepter les cookies|j'accepte|accepter)$/i;
  const btn = [...document.querySelectorAll('button, a[role="button"]')]
    .find((b) => visible(b) && re.test((b.textContent || '').replace(/\s+/g, ' ').trim()));
  if (btn) { btn.click(); return 'text'; }
  return null;
}
"""

_FETCH_JS = """
async ({url, method, headers, body, timeoutMs}) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const r = await fetch(url, {method, headers, body, credentials: 'include', signal: controller.signal});
    return {status: r.status, contentType: r.headers.get('content-type') || '', text: await r.text(), url: r.url};
  } catch (e) {
    return {status: 0, contentType: '', text: String(e), url};
  } finally {
    clearTimeout(timer);
  }
}
"""

# Time left to an anti-bot challenge to pass by itself (Cloudflare often does)
CHALLENGE_WAIT_SECONDS = 15

# Debug snapshots kept per retailer (data/debug/{key}-{AAAAMMJJ-HHMMSS}-{status}.html)
SNAPSHOTS_KEPT = 5

# Title of a Cloudflare challenge or block page: only trusted together with the
# marks of such a page (a product called « Un instant gourmand » is no challenge)
_CHALLENGE_TITLE = re.compile(r"^\s*(just a moment|un instant|attention required|access denied|acc[eè]s refus)", re.I)
_CLOUDFLARE_CHALLENGE = (
    "#challenge-form, #challenge-running, #cf-challenge-running, #challenge-stage, "
    "iframe[src*='challenges.cloudflare.com']"
)
_CLOUDFLARE_MARKS = (
    "script[src*='/cdn-cgi/challenge-platform/'], #cf-wrapper, #cf-error-details, .cf-error-details, "
    ".ray-id, #cf-please-wait, .cf-browser-verification"
)

# DataDome's own block page: no captcha to solve, the connection is refused
# (« Access blocked. » on E.Leclerc Drive). Not « We detected unusual activity
# from your device or network »: that footer is on every DataDome page, the
# slider captcha the user can solve included
_DATADOME_HARD_TEXT = re.compile(
    r"acc[eè]s temporairement restreint|temporairement restreint|you have been blocked|vous avez [eé]t[eé] bloqu[eé]"
    r"|access blocked|access is temporarily restricted",
    re.I,
)
# A puzzle to solve (« Slide right to complete the puzzle », « Verification Required »)
_DATADOME_PUZZLE_TEXT = re.compile(
    r"slide right|faites glisser|glissez vers la droite|verification required|v[eé]rification requise",
    re.I,
)


def is_hard_block_text(text: str | None) -> bool:
    """The text of a page says the connection is refused for a while (DataDome block page).

    A text that also shows a puzzle to solve is a captcha, not a block.
    """
    return bool(text) and bool(_DATADOME_HARD_TEXT.search(text)) and not _DATADOME_PUZZLE_TEXT.search(text)


def _datadome_url(text: str) -> str | None:
    """The captcha URL of a DataDome JSON answer (``{"url": "https://geo.captcha-delivery.com/..."}``)."""
    stripped = (text or "").lstrip()
    if not stripped.startswith("{"):
        return None
    try:
        data = json.loads(stripped)
    except ValueError:
        return None
    url = data.get("url") if isinstance(data, dict) else None
    return url if isinstance(url, str) else None


def classify_datadome(url: str | None, text: str | None = None) -> str | None:
    """What a DataDome answer means: ``"hard_block"``, ``"captcha"`` or None (not DataDome).

    ``url`` is a page, iframe or JSON ``url`` value; ``text`` the text of the
    block page or the body of an API answer (``{"url": ...}``). ``t=bv`` in the
    captcha URL, or the text « Accès temporairement restreint » / « Access
    blocked », is a hard block: the connection is refused and there is nothing
    to solve. A text showing a puzzle (« Slide right… ») is a captcha whatever
    else it says; any other captcha-delivery.com URL is a captcha (or a check
    that passes by itself).
    """
    url = url or _datadome_url(text or "") or ""
    head = (text or "")[:5000]
    if "captcha-delivery.com" in url and "bv" in parse_qs(urlparse(url).query).get("t", []):
        return "hard_block"
    if is_hard_block_text(head):
        return "hard_block"
    if "captcha-delivery.com" in url or "captcha-delivery.com" in head:
        return "captcha"
    if _DATADOME_HARD_TEXT.search(head):
        return "captcha"  # a block text with a puzzle: the puzzle is shown
    return None


def classify_page(
    url: str,
    title: str = "",
    *,
    datadome_src: str | None = None,
    datadome_text: str = "",
    cloudflare_challenge: bool = False,
    cloudflare_marks: bool = False,
) -> str | None:
    """Kind of anti-bot page: ``"hard_block"``, ``"captcha"`` (DataDome), ``"cloudflare"`` or None.

    The values are collected by :func:`detect_block`: page URL and title, src
    and text of a captcha-delivery.com iframe, Cloudflare challenge elements and
    the weaker marks of a Cloudflare page.
    """
    if "captcha-delivery.com" in (url or ""):
        return classify_datadome(url, datadome_text) or "captcha"
    if datadome_src is not None:
        return classify_datadome(datadome_src, datadome_text) or "captcha"
    if cloudflare_challenge:
        return "cloudflare"
    if cloudflare_marks and _CHALLENGE_TITLE.search(title or ""):
        return "cloudflare"
    return None


def blocked_message(label: str) -> str:
    return (
        f"{label} demande une vérification anti-robot : appuyez sur « Ouvrir le site », "
        "validez-la une fois dans la fenêtre qui s'ouvre, puis relancez la recherche."
    )


def clock_text(when: float, now: float | None = None) -> str:
    """« 15 h 40 », « demain à 1 h 10 » or « le 12/10 à 9 h 05 » (local time of the PC)."""
    moment = datetime.fromtimestamp(when)
    today = datetime.fromtimestamp(now if now is not None else datetime.now().timestamp()).date()
    clock = f"{moment.hour} h {moment.minute:02d}"
    days = (moment.date() - today).days
    if days == 0:
        return clock
    if days == 1:
        return f"demain à {clock}"
    return f"le {moment:%d/%m} à {clock}"


def hard_block_message(label: str, until: float | None = None, now: float | None = None) -> str:
    """Message of a hard block: the site refuses the connection for a while."""
    if until is None:
        return (
            f"{label} bloque temporairement cette connexion. "
            "Inutile de relancer : PrixMalin attendra avant de réessayer."
        )
    return (
        f"{label} bloque temporairement cette connexion. PrixMalin ne réessaiera pas avant "
        f"{clock_text(until, now)}. Inutile de relancer."
    )


def is_timeout_error(error: BaseException) -> bool:
    """A time limit was reached (asyncio, or a Playwright/patchright action)."""
    if isinstance(error, TimeoutError):
        return True
    return type(error).__name__ == "TimeoutError" and type(error).__module__.startswith(("playwright", "patchright"))


# Messages of Playwright when the page or the browser went away, or a navigation failed
_NAVIGATION_ERROR = re.compile(
    r"net::ERR_|Navigation failed|navigation|Target page, context or browser has been closed|Target closed|"
    r"Page closed|has been closed|frame was detached|Execution context was destroyed",
    re.I,
)


def is_navigation_error(error: BaseException) -> bool:
    """The page failed to load or was closed (worth one more try in a fresh tab)."""
    if isinstance(error, (ValueError, TimeoutError)) or is_timeout_error(error):
        return False
    return bool(_NAVIGATION_ERROR.search(str(error)))


@dataclass
class FetchResult:
    status: int
    content_type: str
    text: str
    url: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self):
        return json.loads(self.text)

    @property
    def is_json(self) -> bool:
        return "json" in self.content_type or self.text.lstrip()[:1] in ("{", "[")


async def accept_cookies(page) -> None:
    try:
        clicked = await page.evaluate(_ACCEPT_COOKIES_JS)
        if clicked:
            await page.wait_for_timeout(400)
    except Exception as e:  # noqa: BLE001 (page navigated meanwhile, etc.)
        logger.debug("accept_cookies: %s", e)


async def _datadome_frame_text(page) -> str:
    """Text of the captcha-delivery.com frame (best effort, a cross-site frame)."""
    for frame in page.frames:
        if "captcha-delivery.com" in (frame.url or ""):
            try:
                return await asyncio.wait_for(
                    frame.evaluate("() => document.body ? document.body.innerText.slice(0, 3000) : ''"), 3
                )
            except Exception as e:  # noqa: BLE001 (frame not ready, navigated...)
                logger.debug("DataDome frame text: %s", e)
    return ""


async def detect_block(page) -> str | None:
    """Kind of anti-bot page shown: "hard_block", "captcha" (DataDome), "cloudflare" or None.

    Only reads the page already loaded: no request to the site.
    """
    try:
        url = page.url or ""
        if url in ("", "about:blank"):
            return None
        if "captcha-delivery.com" in url:
            text = await page.evaluate("() => document.body ? document.body.innerText.slice(0, 3000) : ''")
            return classify_page(url, datadome_text=text)
        frame = page.locator("iframe[src*='captcha-delivery.com']")
        if await frame.count():
            src = await frame.first.get_attribute("src")
            return classify_page(url, datadome_src=src or "", datadome_text=await _datadome_frame_text(page))
        return classify_page(
            url,
            await page.title(),
            cloudflare_challenge=bool(await page.locator(_CLOUDFLARE_CHALLENGE).count()),
            cloudflare_marks=bool(await page.locator(_CLOUDFLARE_MARKS).count()),
        )
    except Exception as e:  # noqa: BLE001 (page navigated meanwhile, etc.)
        logger.debug("detect_block: %s", e)
    return None


def raise_for_block(kind: str, label: str, captcha_message: str | None = None) -> None:
    if kind == "hard_block":
        raise HardBlockError(hard_block_message(label), label=label)
    raise BlockedError(captcha_message or blocked_message(label))


async def wait_for_clearance(page, label: str, captcha_message: str | None = None) -> None:
    """Give an anti-bot challenge time to pass by itself, else raise BlockedError.

    A hard block (nothing to solve) raises HardBlockError at once.
    """
    kind = await detect_block(page)
    waited = 0.0
    while kind and kind != "hard_block" and waited < CHALLENGE_WAIT_SECONDS:
        await page.wait_for_timeout(1000)
        waited += 1
        kind = await detect_block(page)
    if kind:
        raise_for_block(kind, label, captcha_message)


async def ensure_origin(
    page,
    home_url: str,
    label: str,
    *,
    settle: float = 0.0,
    accept: bool = True,
    reload_on_block: bool = True,
    captcha_message: str | None = None,
) -> bool:
    """Park the page on the retailer's site so that in-page fetch() calls work.

    Returns True when the page had to load the site. ``settle``: seconds to
    wait after that load, before any API call (the anti-bot script of the site
    runs first). ``reload_on_block=False``: a page that shows a challenge is not
    loaded again (that would only hit the site once more), the challenge is
    reported at once. ``accept``: click the cookie banner.
    """
    origin = "{0.scheme}://{0.netloc}".format(urlparse(home_url))
    on_site = page.url.startswith(origin)
    if on_site or not reload_on_block:
        kind = await detect_block(page)
        if kind and not reload_on_block:
            raise_for_block(kind, label, captcha_message)
        if on_site and not kind:
            return False
    await page.goto(home_url, wait_until="domcontentloaded", timeout=30000)
    await wait_for_clearance(page, label, captcha_message)
    if settle:
        try:
            await page.wait_for_load_state("load", timeout=10000)
        except Exception as e:  # noqa: BLE001 (slow third-party resources: go on)
            logger.debug("ensure_origin load: %s", e)
        await asyncio.sleep(settle)
        await wait_for_clearance(page, label, captcha_message)
    if accept:
        await accept_cookies(page)
    return True


async def page_fetch(
    page,
    url: str,
    method: str = "GET",
    headers: dict | None = None,
    json_body: object | None = None,
    timeout_ms: int = 15000,
) -> FetchResult:
    """fetch() from inside the page: same cookies and TLS fingerprint as the site itself."""
    result = await page.evaluate(
        _FETCH_JS,
        {
            "url": url,
            "method": method,
            "headers": headers or {},
            "body": json.dumps(json_body) if json_body is not None else None,
            "timeoutMs": timeout_ms,
        },
    )
    return FetchResult(result["status"], result["contentType"], result["text"], result["url"])


# Files of a snapshot (page, screenshot, raw answers of save_debug_text): all rotated
SNAPSHOT_SUFFIXES = (".html", ".png", ".json", ".txt")
_SNAPSHOT_NAME = r"^{key}-(\d{{8}}-\d{{6}})-[a-z_]+\.(" + "|".join(x[1:] for x in SNAPSHOT_SUFFIXES) + ")$"


def snapshot_path(key: str, status: str = "empty", when: datetime | None = None) -> Path:
    """Where a page of retailer ``key`` is saved (``.html``; ``.png`` or ``.json`` next to it).

    data/debug/{key}-{AAAAMMJJ-HHMMSS}-{status}.html, ``status`` being the
    search status that led to the snapshot ("empty", "blocked", "timeout",
    "error"). The last SNAPSHOTS_KEPT snapshots of each retailer are kept.
    """
    when = when or datetime.now()
    return config.DEBUG_DIR / f"{key}-{when:%Y%m%d-%H%M%S}-{status}.html"


def rotate_snapshots(key: str, keep: int = SNAPSHOTS_KEPT) -> None:
    """Remove the files of the snapshots of ``key`` older than the ``keep`` last ones."""
    pattern = re.compile(_SNAPSHOT_NAME.format(key=re.escape(key)))
    try:
        files = [(m.group(1), f) for f in config.DEBUG_DIR.iterdir() if (m := pattern.match(f.name))]
    except OSError:
        return
    stamps = sorted({stamp for stamp, _ in files}, reverse=True)
    old = set(stamps[keep:])
    for stamp, f in files:
        if stamp in old:
            f.unlink(missing_ok=True)


async def save_debug_snapshot(page, key: str, status: str = "empty", *, screenshot: bool = True) -> Path | None:
    """Keep the page of a search that went wrong, to help fixing a broken scraper."""
    try:
        path = snapshot_path(key, status)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            content = await page.content()
        except Exception as e:  # noqa: BLE001 (still loading: the address and the screenshot are kept)
            logger.debug("snapshot content: %s", e)
            content = f"<!-- PrixMalin : page en cours de chargement ({status}) : {page.url} -->\n"
        path.write_text(content, encoding="utf-8")
        if screenshot:
            await page.screenshot(path=str(path.with_suffix(".png")), full_page=False, timeout=5000)
        logger.info("%s: page saved in %s (%s)", key, path.name, status)
        return path
    except Exception as e:  # noqa: BLE001 (debugging aid only)
        logger.debug("save_debug_snapshot: %s", e)
        return None
    finally:
        rotate_snapshots(key)


def save_debug_text(key: str, status: str, text: str, suffix: str = ".json") -> Path | None:
    """Keep a raw answer of a site (JSON of unexpected shape...) next to the snapshots.

    ``suffix``: one of SNAPSHOT_SUFFIXES (else ``.txt``), so the file is rotated
    with the snapshots of ``key``.
    """
    if suffix not in SNAPSHOT_SUFFIXES:
        suffix = ".txt"
    try:
        path = snapshot_path(key, status).with_suffix(suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        logger.warning("%s: unexpected answer saved in %s", key, path.name)
        rotate_snapshots(key)
        return path
    except OSError as e:
        logger.debug("save_debug_text: %s", e)
        return None
