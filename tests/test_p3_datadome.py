"""B41: DataDome answers told apart (captcha or hard block), Intermarché API errors."""

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
