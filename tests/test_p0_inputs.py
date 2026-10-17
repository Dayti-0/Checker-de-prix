"""B02: what a client or a retailer site sends is validated, cut or cleaned."""

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.errors import AppError
from backend.models import ListItemCreate, Product
from backend.services import shopping_list
from tests.conftest import run

XSS_STORE = 'x"><img src=x onerror="document.title=\'XSS-OK\'">'


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def test_unknown_retailer_in_a_list_item_is_rejected(client):
    response = client.post(
        "/api/list", json={"query": "farine", "product": {"store": XSS_STORE, "name": "Farine", "price": 1}}
    )
    assert response.status_code == 422
    assert client.get("/api/list").json() == []
    ok = client.post("/api/list", json={"query": "farine", "product": {"store": "lidl", "name": "Farine", "price": 1}})
    assert ok.status_code == 200


def test_long_texts_are_cut_not_rejected(client):
    product = {
        "store": "aldi",
        "name": "F" * 2_000_000,
        "brand": "B" * 400,
        "price": 1,
        "promo": "P" * 500,
        "unit_price_label": "U" * 150,
        "quantity_label": "Q" * 150,
    }
    response = client.post("/api/list", json={"query": "farine", "product": product})
    assert response.status_code == 200
    saved = client.get("/api/list").json()[0]["picks"]["aldi"]
    assert len(saved["name"]) == 300 and len(saved["brand"]) == 300
    assert len(saved["promo"]) == 200
    assert len(saved["unit_price_label"]) == 100 and len(saved["quantity_label"]) == 100


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.lidl.fr/p/farine", "https://www.lidl.fr/p/farine"),
        ("http://example.com/x", "http://example.com/x"),
        ("//cdn.example.com/x.jpg", "https://cdn.example.com/x.jpg"),
        ("javascript:alert(1)", ""),
        (" JavaScript:alert(1)", ""),
        ("data:text/html,<script>alert(1)</script>", ""),
        ("/relative/path", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_only_web_addresses_are_kept(url, expected):
    product = Product(store="aldi", name="Farine", product_url=url, image_url=url)
    assert product.product_url == expected
    assert product.image_url == (expected or None)


def test_the_list_is_capped(monkeypatch):
    monkeypatch.setattr(shopping_list, "MAX_ITEMS", 3)

    async def scenario():
        for name in ("farine", "sucre", "sel"):
            await shopping_list.add_item(ListItemCreate(query=name))
        # The same query is merged into its line, even when the list is full
        await shopping_list.add_item(ListItemCreate(query="Farine"))
        with pytest.raises(AppError) as error:
            await shopping_list.add_item(ListItemCreate(query="lait"))
        return error.value, await shopping_list.get_list()

    error, items = run(scenario())
    assert error.message == "Votre liste est pleine (3 articles au maximum)."
    assert [(i.query, i.quantity) for i in items] == [("farine", 2), ("sucre", 1), ("sel", 1)]


def test_full_list_message_reaches_the_client(client, monkeypatch):
    monkeypatch.setattr(shopping_list, "MAX_ITEMS", 2)
    for query in ("farine", "sucre"):
        assert client.post("/api/list", json={"query": query}).status_code == 200
    response = client.post("/api/list", json={"query": "sel"})
    assert response.status_code == 400
    assert response.json() == {"detail": "Votre liste est pleine (2 articles au maximum).", "code": "list_full"}
