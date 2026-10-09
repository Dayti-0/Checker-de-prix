"""Fixtures of the E2E tests: one PrixMalin server with fake retailers, real Chromium.

- ``server``: base URL of the server (one for the whole tests/e2e package);
- ``desktop`` (1440x900) and ``mobile`` (390x844, touch, pixel ratio 2): a fresh
  page whose data were reset (list, settings, cache, fake sites). Any console
  error, uncaught exception or Content-Security-Policy violation fails the test.
"""

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.conftest import browser_missing  # noqa: E402
from tests.e2e import fake  # noqa: E402
from tests.e2e.server import LiveServer, reset_data, use_data_dir  # noqa: E402

VIEWPORTS = {
    "desktop": {"viewport": {"width": 1440, "height": 900}},
    "mobile": {
        "viewport": {"width": 390, "height": 844},
        "device_scale_factor": 2,
        "is_mobile": True,
        "has_touch": True,
    },
}

# Reports CSP violations as console errors (the fixtures fail on them)
CSP_WATCH = """
document.addEventListener("securitypolicyviolation", (e) => {
    console.error(`CSP: ${e.violatedDirective} ${e.blockedURI}`);
});
"""


@pytest.fixture(autouse=True)
def temp_data_dir():
    """The server of this package keeps its own data directory (see ``server``)."""
    yield


@pytest.fixture(scope="package")
def server(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PRIXMALIN_WARMUP", "0")
        use_data_dir(mp, tmp_path_factory.mktemp("e2e-data"))
        fake.install(mp)
        with LiveServer() as url:
            yield url


@pytest.fixture(scope="package")
def chromium():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(timeout=60000)
        except PlaywrightError as e:
            browser_missing(f"Chromium indisponible : {e}")
        yield browser
        browser.close()


def open_page(chromium, server, viewport, color_scheme="light"):
    reset_data()
    fake.reset()
    context = chromium.new_context(locale="fr-FR", color_scheme=color_scheme, **VIEWPORTS[viewport])
    context.add_init_script(CSP_WATCH)
    page = context.new_page()
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    page.base = server
    page.errors = errors
    return context, page


@pytest.fixture
def desktop(chromium, server):
    context, page = open_page(chromium, server, "desktop")
    yield page
    context.close()
    assert page.errors == []


@pytest.fixture
def mobile(chromium, server):
    context, page = open_page(chromium, server, "mobile")
    yield page
    context.close()
    assert page.errors == []


@pytest.fixture
def dark(chromium, server):
    """Desktop page in dark mode."""
    context, page = open_page(chromium, server, "desktop", color_scheme="dark")
    yield page
    context.close()
    assert page.errors == []
