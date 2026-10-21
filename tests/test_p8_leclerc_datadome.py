"""E.Leclerc Drive: answers of the site, DataDome and the visit of the drive (pure functions, P8)."""

import json

import pytest

from backend.scrapers import common
from backend.scrapers.base import BlockedError, HardBlockError, ScraperError, StoreRequiredError
from backend.scrapers.leclerc import (
    CAPTCHA_MESSAGE,
    REFUSED_MESSAGE,
    REVISIT_SECONDS,
    STORE_GONE,
    DriveVisit,
    captcha_url,
    check_answer,
    classify_answer,
    is_portal,
    needs_store_visit,
    parse_store_url,
    refusal_record,
)
from tests import fixtures

DRIVE = "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges/recherche.aspx?TexteRecherche=coca"
CAPTCHA_JSON = json.dumps(
    {"url": "https://geo.captcha-delivery.com/captcha/?initialCid=x&hash=y&cid=z&t=fe&referer=https%3A%2F%2Ffd12"}
)
HARD_JSON = CAPTCHA_JSON.replace("t=fe", "t=bv")
CAPTCHA_FRAME_URL = "https://geo.captcha-delivery.com/captcha/?initialCid=x&hash=y&cid=z&t=fe&referer=x&s=1&dm=cd"
# Text of the DataDome slider captcha (public captures, 2025-2026): its footer
# « We detected unusual activity… » is the same as the one of the block page
SLIDER_TEXT = (
    "Verification Required Slide right to complete the puzzle. Why is this step needed? "
    "We detected unusual activity from your device or network. Reasons may include: Rapid taps or clicks "
    "JavaScript disabled or not working Automated (bot) activity on your network Use of developer or "
    "inspection tools Need help? Submit feedback."
)
SLIDER_TEXT_FR = (
    "Vérification requise Faites glisser vers la droite pour compléter le puzzle. Pourquoi cette étape ? "
    "Nous avons détecté une activité inhabituelle provenant de votre appareil ou de votre réseau."
)
# Refusals without any DataDome mark (firewall, server): nothing to validate in the window
PLAIN_403 = (
    "<html><head><title>403 - Forbidden: Access is denied.</title></head><body><h1>403 Forbidden</h1></body></html>"
)
PLAIN_401 = '{"Message":"Authorization has been denied for this request."}'
REJECTED = '{"message":"Request Rejected","supportID":"123"}'


@pytest.mark.parametrize(
    "status, url, text, expected",
    [
        (200, DRIVE, fixtures.LECLERC_SEARCH_HTML, "ok"),
        (200, DRIVE, fixtures.LECLERC_EMPTY_HTML, "ok"),  # a page of the drive without product
        (403, DRIVE, CAPTCHA_JSON, "captcha"),
        (403, DRIVE, HARD_JSON, "hard_block"),
        (429, DRIVE, "", "hard_block"),
        (403, DRIVE, fixtures.LECLERC_CAPTCHA_HTML, "captcha"),
        (200, DRIVE, fixtures.LECLERC_CAPTCHA_HTML, "captcha"),
        (403, DRIVE, fixtures.LECLERC_HARD_BLOCK_HTML, "hard_block"),
        (200, DRIVE, fixtures.LECLERC_ACCESS_BLOCKED_HTML, "hard_block"),
        (403, DRIVE, fixtures.LECLERC_RESTRICTED_HTML, "hard_block"),
        (200, DRIVE, "<p>Access is temporarily restricted</p>", "hard_block"),
        (0, DRIVE, "TypeError: Failed to fetch", "retry"),
        (0, DRIVE, "AbortError: signal is aborted without reason", "timeout"),
        (403, DRIVE, PLAIN_403, "refused"),
        (401, DRIVE, PLAIN_401, "refused"),
        (405, DRIVE, "", "refused"),
        (403, DRIVE, REJECTED, "refused"),
        (403, DRIVE, SLIDER_TEXT + " " + CAPTCHA_FRAME_URL, "captcha"),
        (200, DRIVE, fixtures.LECLERC_SESSION_HTML, "retry"),
        (200, "https://www.leclercdrive.fr/", fixtures.LECLERC_PORTAL_HTML, "portal"),
        (200, "https://leclercdrive.fr/", "", "portal"),
        (500, DRIVE, "<h1>Erreur serveur</h1>", "error"),
        (404, DRIVE, "Not found", "error"),
    ],
)
def test_classify_answer(status, url, text, expected):
    assert classify_answer(status, url, text) == expected


def test_check_answer_raises_the_matching_error():
    with pytest.raises(BlockedError) as error:
        check_answer(403, DRIVE, CAPTCHA_JSON)
    assert str(error.value) == CAPTCHA_MESSAGE and not isinstance(error.value, HardBlockError)
    assert "Ouvrir le site" in CAPTCHA_MESSAGE and "E.Leclerc" in CAPTCHA_MESSAGE
    for text in (HARD_JSON, fixtures.LECLERC_ACCESS_BLOCKED_HTML):
        with pytest.raises(HardBlockError) as hard:
            check_answer(403, DRIVE, text)
        assert hard.value.label == "E.Leclerc" and "E.Leclerc bloque temporairement" in str(hard.value)
    with pytest.raises(StoreRequiredError) as gone:
        check_answer(200, "https://www.leclercdrive.fr/", fixtures.LECLERC_PORTAL_HTML)
    assert str(gone.value) == STORE_GONE
    with pytest.raises(ScraperError) as failed:
        check_answer(502, DRIVE, "Bad gateway")
    assert str(failed.value) == "E.Leclerc a renvoyé une erreur. Réessayez plus tard."
    assert check_answer(200, DRIVE, fixtures.LECLERC_SEARCH_HTML) == "ok"
    assert check_answer(0, DRIVE, "TypeError: Failed to fetch") == "retry"


def test_captcha_url_is_read_from_the_page():
    url = captcha_url(fixtures.LECLERC_CAPTCHA_HTML)
    assert url.startswith("https://geo.captcha-delivery.com/captcha/?initialCid=")
    assert "&t=fe&" in url and "&amp;" not in url
    assert common.classify_datadome(url) == "captcha"
    assert captcha_url("<html></html>") is None


def test_new_datadome_texts_without_false_positive():
    assert common.classify_datadome(None, fixtures.LECLERC_ACCESS_BLOCKED_HTML) == "hard_block"
    assert common.classify_datadome(None, "Access is temporarily restricted") == "hard_block"
    # The footer of every DataDome page, the captcha to solve included: no block by itself
    assert common.classify_datadome(None, "Nous avons détecté une activité inhabituelle") is None
    assert common.classify_datadome(None, "We detected unusual activity from your device or network.") is None
    assert common.is_hard_block_text("Access blocked.")
    assert not common.is_hard_block_text(fixtures.LECLERC_SEARCH_HTML)
    assert not common.is_hard_block_text("")
    assert common.classify_datadome(None, fixtures.LECLERC_SEARCH_HTML[:5000]) is None
    # The real results page is a page of the drive, whatever its scripts
    assert classify_answer(200, DRIVE, fixtures.LECLERC_SEARCH_HTML) == "ok"


def test_is_portal():
    assert is_portal("https://www.leclercdrive.fr/")
    assert is_portal("https://www.leclercdrive.fr/region-occitanie/")
    assert not is_portal(DRIVE)
    assert not is_portal(None)


BRUGES = parse_store_url("https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges.aspx")
CRES = parse_store_url("https://fd3-courses.leclercdrive.fr/magasin-093401-093401-Le-Cres-Montpellier")


def test_needs_store_visit():
    now = 10_000.0
    visit = DriveVisit("173301", BRUGES.base, now - 60)
    assert needs_store_visit(None, BRUGES, DRIVE, now)
    # Same drive, tab still on it, recent visit: no new visit
    assert not needs_store_visit(visit, BRUGES, BRUGES.base + ".aspx", now)
    assert not needs_store_visit(visit, BRUGES, DRIVE, now)
    # Another drive
    assert needs_store_visit(visit, CRES, DRIVE, now)
    # The tab is elsewhere (window closed then opened again, portal, other drive)
    assert needs_store_visit(visit, BRUGES, "about:blank", now)
    assert needs_store_visit(visit, BRUGES, "https://www.leclercdrive.fr/", now)
    assert needs_store_visit(visit, BRUGES, BRUGES.base + "x.aspx", now)
    # After 15 minutes the session may be sent elsewhere by the site
    assert needs_store_visit(DriveVisit("173301", BRUGES.base, now - REVISIT_SECONDS - 1), BRUGES, DRIVE, now)
    # The address of the visit is the one the site ended on (fd1 → fd10)
    fd1 = parse_store_url("https://fd1-courses.leclercdrive.fr/magasin-085111-Reims-Jean-Jaures")
    landed = DriveVisit("085111", "https://fd10-courses.leclercdrive.fr/magasin-085111-Reims-Jean-Jaures", now)
    assert not needs_store_visit(landed, fd1, landed.base + "/recherche.aspx?TexteRecherche=x", now)


@pytest.mark.parametrize("text", [SLIDER_TEXT, SLIDER_TEXT_FR])
def test_slider_captcha_is_a_check_not_a_block(text):
    """The slider captcha shares its footer with the block page: it stays a check to validate."""
    assert not common.is_hard_block_text(text)
    assert common.classify_datadome(CAPTCHA_FRAME_URL, text) == "captcha"
    assert common.classify_datadome(None, text) is None
    assert common.classify_page(DRIVE, datadome_src=CAPTCHA_FRAME_URL, datadome_text=text) == "captcha"
    assert common.classify_page(CAPTCHA_FRAME_URL, datadome_text=text) == "captcha"
    # A slider text next to a block text: the puzzle is what the page shows
    assert common.classify_datadome(CAPTCHA_FRAME_URL, "Access blocked. " + text) == "captcha"
    # t=bv stays a hard block whatever the text
    assert common.classify_datadome(CAPTCHA_FRAME_URL.replace("t=fe", "t=bv"), text) == "hard_block"


@pytest.mark.parametrize("status, text", [(403, PLAIN_403), (401, PLAIN_401), (405, ""), (403, REJECTED)])
def test_refusal_without_datadome_is_an_error_not_a_check(status, text):
    with pytest.raises(ScraperError) as error:
        check_answer(status, DRIVE, text)
    assert not isinstance(error.value, BlockedError)
    assert str(error.value) == REFUSED_MESSAGE and error.value.status == "error"
    assert "Ouvrir le site" not in REFUSED_MESSAGE


def test_fetch_stopped_by_its_time_limit_is_a_timeout():
    with pytest.raises(TimeoutError):
        check_answer(0, DRIVE, "AbortError: signal is aborted without reason")
    assert check_answer(0, DRIVE, "TypeError: Failed to fetch") == "retry"


def test_refusal_record_keeps_no_address():
    record = json.loads(refusal_record(403, "text/html", PLAIN_403 + "x" * 30000))
    assert record["status"] == 403 and record["content_type"] == "text/html"
    assert record["body"].startswith("<html>") and len(record["body"]) == 20000
    assert set(record) == {"status", "content_type", "body"}
