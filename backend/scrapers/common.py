"""Playwright page helpers shared by the scrapers."""

import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from backend import config
from backend.scrapers.base import BlockedError

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

_CHALLENGE_TITLE = re.compile(r"just a moment|un instant|attention required|access denied|acc[eè]s refus", re.I)


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


async def detect_block(page) -> str | None:
    """Return 'datadome' or 'cloudflare' when the page is an anti-bot challenge."""
    try:
        if "captcha-delivery.com" in page.url:
            return "datadome"
        if await page.locator("iframe[src*='captcha-delivery.com']").count():
            return "datadome"
        if await page.locator("#challenge-form, #challenge-running, iframe[src*='challenges.cloudflare.com']").count():
            return "cloudflare"
        if _CHALLENGE_TITLE.search(await page.title()):
            return "cloudflare"
    except Exception as e:  # noqa: BLE001 (page navigated meanwhile, etc.)
        logger.debug("detect_block: %s", e)
    return None


async def wait_for_clearance(page, label: str) -> None:
    """Give an anti-bot challenge time to pass by itself, else raise BlockedError."""
    kind = await detect_block(page)
    waited = 0.0
    while kind and waited < CHALLENGE_WAIT_SECONDS:
        await page.wait_for_timeout(1000)
        waited += 1
        kind = await detect_block(page)
    if kind:
        raise BlockedError(
            f"{label} affiche une vérification anti-robot. Ouvrez le navigateur PrixMalin "
            "(Réglages → Ouvrir le site) et validez-la une fois."
        )


async def ensure_origin(page, home_url: str, label: str) -> None:
    """Park the page on the retailer's site so that in-page fetch() calls work."""
    origin = "{0.scheme}://{0.netloc}".format(urlparse(home_url))
    if page.url.startswith(origin) and not await detect_block(page):
        return
    await page.goto(home_url, wait_until="domcontentloaded", timeout=30000)
    await wait_for_clearance(page, label)
    await accept_cookies(page)


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


async def save_debug_snapshot(page, key: str) -> None:
    """Keep the last page that gave no product, to help fixing a broken scraper."""
    try:
        config.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        (config.DEBUG_DIR / f"{key}.html").write_text(await page.content(), encoding="utf-8")
        await page.screenshot(path=str(config.DEBUG_DIR / f"{key}.png"), full_page=False)
        logger.info("%s: no product found, page saved in %s", key, config.DEBUG_DIR)
    except Exception as e:  # noqa: BLE001 (debugging aid only)
        logger.debug("save_debug_snapshot: %s", e)
