"""E.Leclerc Drive: answers of the site, DataDome and the visit of the drive (pure functions, P8)."""

import json

import pytest

from backend.scrapers import common
from backend.scrapers.base import BlockedError, HardBlockError, ScraperError, StoreRequiredError
from backend.scrapers.leclerc import (
    CAPTCHA_MESSAGE,
    REVISIT_SECONDS,
    STORE_GONE,
    DriveVisit,
    captcha_url,
    check_answer,
    classify_answer,
    is_portal,
    needs_store_visit,
    parse_store_url,
)
from tests import fixtures

DRIVE = "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges/recherche.aspx?TexteRecherche=coca"
CAPTCHA_JSON = json.dumps(
    {"url": "https://geo.captcha-delivery.com/captcha/?initialCid=x&hash=y&cid=z&t=fe&referer=https%3A%2F%2Ffd12"}
)
HARD_JSON = CAPTCHA_JSON.replace("t=fe", "t=bv")


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
    assert common.classify_datadome(None, "Nous avons détecté une activité inhabituelle") == "hard_block"
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
