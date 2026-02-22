"""Shared browser utilities with stealth support for all scrapers."""

import logging
import os
import random
from contextlib import contextmanager
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

# Modern Chrome user agents (rotated to reduce fingerprinting)
_USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
]

# Stealth instance (singleton)
_stealth = Stealth()


def _get_proxy_config() -> dict | None:
    """Build Playwright proxy config from environment variables."""
    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if not proxy_url:
        return None
    parsed = urlparse(proxy_url)
    config: dict = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        config["username"] = parsed.username
    if parsed.password:
        config["password"] = parsed.password
    return config


@contextmanager
def create_stealth_browser():
    """Create a stealth-enabled Playwright browser and context.

    Yields (browser, context, page) tuple.
    Usage::

        with create_stealth_browser() as (browser, context, page):
            page.goto(...)
    """
    proxy = _get_proxy_config()
    user_agent = random.choice(_USER_AGENTS)

    with _stealth.use_sync(sync_playwright()) as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
            proxy=proxy,
        )
        context = browser.new_context(
            user_agent=user_agent,
            locale="fr-FR",
            timezone_id="Europe/Paris",
            ignore_https_errors=True,
            viewport={"width": 1366, "height": 768},
            screen={"width": 1366, "height": 768},
        )
        page = context.new_page()

        try:
            yield browser, context, page
        finally:
            browser.close()


def accept_cookies(page: Page, timeout: int = 3000) -> None:
    """Try to accept cookies banner using common French site patterns."""
    selectors = [
        "#onetrust-accept-btn-handler",
        "#didomi-notice-agree-button",
        "[data-testid='accept-cookies']",
        "button[class*='cookie']",
        ".cookie-consent button",
        "#footer_tc_privacy_button_2",
        "#CybsAcceptAll",
        "button:has-text('Tout accepter')",
        "button:has-text('Accepter')",
        "button:has-text('J\\'accepte')",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=timeout):
                btn.click(timeout=3000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue
