"""B41: the dedicated Intermarché window looks like a person's Chrome to the site's scripts.

The probe of the DataDome research (``fixtures.FINGERPRINT_PAGE``) is loaded as
the intermarche.com page of the dedicated window, with a cross-site iframe.
It checks what anti-robot scripts are known to read: ``navigator.webdriver``,
patched getters, the ``iframe.contentWindow.self`` leak of stealth scripts, the
notifications permission, page and worker languages, the window frame, and
the console serialisation that reveals ``Runtime.enable`` (errName and
protoProxy counters: 1 for a browser without automation, 2 and 3 under
Playwright). It also hooks ``window.fetch`` in the page: PrixMalin's in-page
API calls must not go through the page's own functions.

The same probe in the shared browser (Playwright + stealth, used by the other
retailers) is only logged, for information.
"""

import asyncio
import json
import logging

import pytest

from backend import config
from backend.browser import BrowserManager, BrowserUnavailable
from backend.scrapers.common import page_fetch
from tests import fixtures
from tests.conftest import browser_missing
from tests.p3_chrome import dedicated_manager

logger = logging.getLogger("prixmalin.tests")

HOME = "https://www.intermarche.com/"


def html(body):
    return lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)


async def probe(page):
    await page.unroute_all(behavior="ignoreErrors")
    await page.route("**/*", lambda route: route.abort())
    await page.route(HOME, html(fixtures.FINGERPRINT_PAGE))
    await page.route("https://probe-frame.example/", html(fixtures.FINGERPRINT_FRAME))
    await page.route(
        "https://www.intermarche.com/api/ping",
        lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok": true}'),
    )
    await page.goto(HOME)
    await page.wait_for_function(
        "() => { const p = document.getElementById('report'); return p && JSON.parse(p.textContent).frame; }",
        timeout=15000,
    )
    answer = await page_fetch(page, "https://www.intermarche.com/api/ping")
    await page.wait_for_timeout(400)  # the report is written every 300 ms
    report = json.loads(await page.inner_text("#report"))
    await page.goto("about:blank")
    return report, answer.status


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    with dedicated_manager(tmp_path_factory.mktemp("itm-fp")) as manager:
        yield asyncio.run(manager.run("intermarche", probe, timeout=60))


@pytest.mark.parametrize("role", ["main", "frame"])
def test_no_automation_visible(report, role):
    data, _ = report
    data = data if role == "main" else data["frame"]
    checks = data["checks"]
    assert checks["webdriver"] is False
    assert "HeadlessChrome" not in checks["userAgent"]
    assert checks["vendor"] == "Google Inc."
    for getter in ("nativeLanguages", "nativeUserAgent", "nativeVendor", "nativeWebdriver"):
        assert checks[getter] is True, getter  # no patched navigator getter
    assert checks["iframeSelf"] is True  # no stealth iframe patch
    assert checks["notifications"] in ("prompt", "denied", "granted")  # not the stealth "default"
    assert checks["workerLanguages"] == checks["languages"]  # no language override in the page only
    assert checks["outerGreaterThanInner"] is True  # a real window frame
    # Console serialisation: Runtime.enable (Playwright) reads these twice and three times
    assert data["variants"] == {"errName": 1, "protoProxy": 1}


def test_in_page_fetch_does_not_go_through_the_page_functions(report):
    data, status = report
    assert status == 200
    assert data["hooks"] == []  # window.fetch of the page was never called by PrixMalin


def test_shared_browser_probe_is_logged(tmp_path_factory, monkeypatch, caplog):
    """Information only: what the same probe sees in the shared Playwright browser."""
    monkeypatch.setattr(config, "MIN_REQUEST_INTERVAL_SECONDS", 0)
    manager = BrowserManager(tmp_path_factory.mktemp("shared-fp"))
    try:
        data, _ = asyncio.run(manager.run("probe", probe, timeout=60))
    except BrowserUnavailable as e:
        browser_missing(f"Chromium unavailable: {e}")
    finally:
        asyncio.run(manager.shutdown())
    with caplog.at_level(logging.INFO, logger="prixmalin.tests"):
        logger.info("Shared browser fingerprint: %s %s", data["checks"], data["variants"])
    assert data["checks"]["webdriver"] is False
