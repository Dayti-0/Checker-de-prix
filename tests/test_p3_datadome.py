"""B41: DataDome answers told apart (captcha or hard block), Intermarché API errors."""

import asyncio
import json

import pytest

from backend.scrapers import intermarche
from backend.scrapers.base import BlockedError, HardBlockError, ScraperError
from backend.scrapers.common import classify_datadome, classify_page
from tests import fixtures

CAPTCHA_URL = fixtures.DATADOME_CAPTCHA_JSON["url"]
BLOCK_URL = fixtures.DATADOME_BLOCK_JSON["url"]


@pytest.mark.parametrize(
    ("url", "text", "expected"),
    [
        (CAPTCHA_URL, "", "captcha"),  # t=fe: a puzzle the user can solve
        (BLOCK_URL, "", "hard_block"),  # t=bv: the connection is refused
        ("https://geo.captcha-delivery.com/interstitial/?initialCid=x&cid=y", "", "captcha"),
        (None, json.dumps(fixtures.DATADOME_CAPTCHA_JSON), "captcha"),  # 403 JSON of the API
        (None, json.dumps(fixtures.DATADOME_BLOCK_JSON), "hard_block"),
        (CAPTCHA_URL, "Accès temporairement restreint", "hard_block"),  # text of the block page
        (CAPTCHA_URL, "Vous avez été bloqué(e).", "hard_block"),
        (CAPTCHA_URL, "You have been blocked", "hard_block"),
        (CAPTCHA_URL, "Faites glisser vers la droite pour compléter le puzzle", "captcha"),
        # The slider captcha and its footer, shared with the block page: still a captcha
        (
            CAPTCHA_URL,
            "Verification Required. Slide right to complete the puzzle. Why is this step needed? "
            "We detected unusual activity from your device or network.",
            "captcha",
        ),
        (
            CAPTCHA_URL,
            "Vérification requise. Faites glisser vers la droite pour compléter le puzzle. "
            "Nous avons détecté une activité inhabituelle provenant de votre appareil.",
            "captcha",
        ),
        (None, "We detected unusual activity from your device or network.", None),
        ("https://www.intermarche.com/", "", None),
        (None, '{"produits": []}', None),
        (None, "<html>Forbidden</html>", None),
        (None, "", None),
    ],
)
def test_classify_datadome(url, text, expected):
    assert classify_datadome(url, text) == expected


def test_classify_page():
    home = "https://www.intermarche.com/"
    assert classify_page(home) is None
    assert classify_page(home, datadome_src=CAPTCHA_URL) == "captcha"
    assert classify_page(home, datadome_src=BLOCK_URL) == "hard_block"
    assert classify_page(home, datadome_src=CAPTCHA_URL, datadome_text="Accès temporairement restreint") == "hard_block"
    assert classify_page(BLOCK_URL) == "hard_block"
    assert classify_page(CAPTCHA_URL) == "captcha"


def test_api_captcha_is_a_check_the_user_can_validate():
    with pytest.raises(BlockedError) as error:
        intermarche.check_answer(403, json.dumps(fixtures.DATADOME_CAPTCHA_JSON))
    assert not isinstance(error.value, HardBlockError)
    assert error.value.status == "blocked"
    assert "Ouvrir le site" in str(error.value)


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (403, json.dumps(fixtures.DATADOME_BLOCK_JSON)),
        (403, "<h1>Accès temporairement restreint</h1>"),
        (429, "Too many requests"),
    ],
)
def test_api_hard_block(status, body):
    with pytest.raises(HardBlockError) as error:
        intermarche.check_answer(status, body)
    assert error.value.status == "blocked"
    assert "temporairement" in str(error.value)


def test_api_other_errors_are_in_french_without_technical_details():
    with pytest.raises(ScraperError) as unreachable:
        intermarche.check_answer(0, "TypeError: Failed to fetch")
    assert "injoignable" in str(unreachable.value) and "TypeError" not in str(unreachable.value)
    with pytest.raises(ScraperError) as server:
        intermarche.check_answer(500, "Internal Server Error")
    assert "500" not in str(server.value) and not isinstance(server.value, BlockedError)
    intermarche.check_answer(200, '{"produits": []}')  # no error


def test_products_have_ean_and_sku():
    products = intermarche.parse_search_json(fixtures.INTERMARCHE_SEARCH)
    assert [(p.ean, p.sku) for p in products] == [
        ("3250390018575", "3250390018575"),
        ("3250390018576", "41755"),  # no idProduit: the item id of the site
    ]
    assert products[0].product_url.endswith("/3250390018575")


def test_unexpected_shape_is_detected():
    assert intermarche.has_products_list({"produits": []})
    assert intermarche.has_products_list({"data": {"products": [{}]}})
    assert not intermarche.has_products_list({"error": "maintenance"})
    assert not intermarche.has_products_list([])


# --- pause after a hard block (services/circuit.py) ---------------------------------

HOUR = 3600


def test_hard_block_pause_doubles_up_to_four_hours():
    from backend.services.circuit import next_hard_block

    now = 1_000_000.0
    first = next_hard_block(None, now)
    assert (first.seconds, first.until) == (30 * 60, now + 30 * 60)
    pauses = [first.seconds]
    record = first
    for _ in range(5):
        now = record.until + 60  # blocked again just after the pause
        record = next_hard_block(record, now)
        pauses.append(record.seconds)
    assert pauses == [1800, 3600, 7200, 14400, 14400, 14400]
    # A day without block: back to 30 minutes
    later = next_hard_block(record, record.until + 25 * HOUR)
    assert later.seconds == 1800


def test_hard_block_pause_survives_a_restart(tmp_path):
    from backend.services.circuit import HardBlocks
    from tests.conftest import run

    async def scenario():
        blocks = HardBlocks(persist=True)
        record = await blocks.hard_block("intermarche", now=1000.0)
        assert await blocks.until("intermarche", now=1001.0) == record.until
        # PrixMalin restarted: a new object reads the database
        again = HardBlocks(persist=True)
        assert await again.until("intermarche", now=1001.0) == 1000.0 + 1800
        assert await again.until("intermarche", now=1000.0 + 1801) is None
        await again.clear("intermarche")
        assert await HardBlocks(persist=True).until("intermarche", now=1001.0) is None

    run(scenario())


def test_no_call_to_the_site_during_the_pause(tmp_path):
    from backend.browser import BrowserManager

    manager = BrowserManager(tmp_path / "profile")

    async def scenario():
        await manager.hard_blocks.hard_block("intermarche")

        async def must_not_run(page):
            raise AssertionError("site called")

        with pytest.raises(HardBlockError) as error:
            await manager.run("intermarche", must_not_run, timeout=5)
        assert error.value.retry_after is not None
        assert "ne réessaiera pas avant" in str(error.value)
        assert manager._thread is None  # no browser started at all

    asyncio.run(scenario())


def test_kill_switch_goes_back_to_the_shared_browser(tmp_path, monkeypatch):
    from backend import config
    from backend.browser import BrowserManager

    manager = BrowserManager(tmp_path / "profile")
    assert manager.is_dedicated("intermarche") and manager.is_dedicated("leclerc")
    assert [w.store for w in manager.status().windows] == ["intermarche", "leclerc"]
    assert [w.label for w in manager.status().windows] == ["Intermarché", "E.Leclerc"]
    monkeypatch.setattr(config, "REAL_CHROME_STORES", ())
    assert not manager.is_dedicated("intermarche") and not manager.is_dedicated("leclerc")
    assert manager.status().windows == []


def test_clock_text():
    from datetime import datetime

    from backend.scrapers.common import clock_text

    now = datetime(2026, 10, 3, 14, 0).timestamp()
    assert clock_text(datetime(2026, 10, 3, 15, 5).timestamp(), now) == "15 h 05"
    assert clock_text(datetime(2026, 10, 4, 1, 10).timestamp(), now) == "demain à 1 h 10"
    assert clock_text(datetime(2026, 10, 12, 9, 5).timestamp(), now) == "le 12/10 à 9 h 05"
