import pytest

from backend.models import Product
from backend.scrapers.extract import card_to_product, products_from_json, products_from_json_ld
from backend.scrapers.parsing import finalize_product, parse_price, parse_quantity, parse_unit_price
from backend.services.matching import query_key, relevance


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2,49 €", 2.49),
        ("2€49", 2.49),
        ("0.69", 0.69),
        ("3,5", 3.5),
        ("Prix : 12,90 €", 12.9),
        ("1,49\xa0€", 1.49),
        ("0,69 € 12 x", 0.69),
        ("5", 5.0),
        (3, 3.0),
        (1.255, 1.25),
        ("", None),
        ("Prix non disponible", None),
        (0, None),
        (None, None),
    ],
)
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Eau minérale 6x1,5L", (9.0, "L")),
        ("Farine de blé T55 1kg", (1.0, "kg")),
        ("Huile 1 L", (1.0, "L")),
        ("50cl", (0.5, "L")),
        ("Lait 1L x6", (6.0, "L")),
        ("4 x 125 g", (0.5, "kg")),
        ("Vinaigre 75 cl", (0.75, "L")),
        ("T45", None),
        ("1 l'huile", None),
        ("", None),
    ],
)
def test_parse_quantity(text, expected):
    assert parse_quantity(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("3,45 € / KG", (3.45, "kg")),
        ("KG = 0.69", (0.69, "kg")),
        ("1 kg = 2,49 €", (2.49, "kg")),
        ("0,35 €/100 g", (3.5, "kg")),
        ("Prix au litre : 1,20 €", (1.2, "L")),
        ("6,92 €/Kg", (6.92, "kg")),
        ("1,23 € la pièce", (1.23, "unité")),
        ("2,49 € le kg", (2.49, "kg")),
        ("€/Kg", None),
        (None, None),
    ],
)
def test_parse_unit_price(text, expected):
    assert parse_unit_price(text) == expected


def test_finalize_uses_label_then_pack_size():
    labelled = finalize_product(Product(store="x", name="Farine", price=1.0, unit_price_label="0,79 €/kg"))
    assert (labelled.unit_price, labelled.unit) == (0.79, "kg")

    computed = finalize_product(Product(store="x", name="Eau minérale 6x1,5L", price=1.8))
    assert (computed.unit_price, computed.unit) == (0.2, "L")

    unknown = finalize_product(Product(store="x", name="Vinaigre", price=1.0))
    assert unknown.unit_price is None


def test_relevance_whole_words_accents_and_plurals():
    assert relevance("Huile de tournesol Lesieur 1L", "huile de tournesol") == 1.0
    assert relevance("Huile d'olive vierge", "huile de tournesol") == 0.5
    assert relevance("Gâteau au chocolat", "eau") == 0.0
    assert relevance("Eaux minérales naturelles", "eau") == 1.0
    assert relevance("Laitue iceberg", "lait") == 0.0
    assert relevance("Crème fraîche épaisse", "creme fraiche") == 1.0
    assert relevance("Pâtes coquillettes", "pates") == 1.0
    assert relevance("N'importe quoi", "de la") == 1.0


def test_query_key_is_canonical():
    assert query_key("  Huile de TOURNESOL ") == query_key("huile de tournesol")
    assert query_key("Pâtes") == "pates"


def test_card_to_product_prefers_price_selector_and_skips_struck_price():
    card = {
        "url": "https://shop.example/p/farine-123",
        "names": ["Ajouter au panier", "Farine de blé T45 1kg"],
        "brand": "U",
        "priceTexts": ["1,10 €", "0,95 €"],
        "unitText": "0,95 € / kg",
        "quantityText": None,
        "strike": ["1,10 €"],
        "text": "Farine de blé T45 1kg 1,10 € 0,95 € 0,95 € / kg",
        "image": "https://img.example/farine.jpg",
    }
    p = card_to_product(card, "coursesu", "https://shop.example")
    assert p.name == "Farine de blé T45 1kg"
    assert p.price == 0.95
    assert p.unit_price_label == "0,95 € / kg"
    assert p.promo == "Au lieu de 1,10 €"


def test_card_to_product_reads_price_from_text_when_no_selector():
    card = {
        "url": "/p/huile-tournesol",
        "names": ["Huile de tournesol"],
        "priceTexts": [],
        "strike": [],
        "text": "Huile de tournesol 1L 1,79 € 1,79 €/L Ajouter",
    }
    p = card_to_product(card, "x", "https://shop.example")
    assert p.price == 1.79
    assert p.unit_price_label == "1,79 €/L"
    assert p.product_url == "https://shop.example/p/huile-tournesol"


def test_card_without_name_is_ignored():
    assert card_to_product({"names": ["Voir le produit", "2,49 €"], "text": "2,49 €"}, "x", "https://e") is None


def test_products_from_json_finds_nested_products():
    data = {
        "results": [
            {
                "hits": [
                    {"name": "Farine T55", "price": {"value": 0.79}, "image": ["/img/f.jpg"], "url": "/p/farine"},
                    {"productName": "Sucre", "salePrice": "1,05 €"},
                    {"name": "Catégorie sans prix"},
                ]
            }
        ]
    }
    products = products_from_json(data, "aldi", "https://www.aldi.fr")
    assert [(p.name, p.price) for p in products] == [("Farine T55", 0.79), ("Sucre", 1.05)]
    assert products[0].image_url == "https://www.aldi.fr/img/f.jpg"
    assert products[0].product_url == "https://www.aldi.fr/p/farine"


def test_products_from_json_ld_item_list():
    texts = [
        '{"@type": "ItemList", "itemListElement": [{"@type": "ListItem", "item": {"@type": "Product",'
        ' "name": "Vinaigre de vin", "brand": {"name": "Maille"}, "image": "https://i/v.jpg",'
        ' "url": "/p/vinaigre", "offers": {"@type": "Offer", "price": "1.35"}}}]}',
        "not json",
    ]
    products = products_from_json_ld(texts, "x", "https://shop.example")
    assert len(products) == 1
    assert products[0].brand == "Maille"
    assert products[0].price == 1.35
