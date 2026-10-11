"""Contents, prices per kg / L / piece and barcodes (B36, B37)."""

import logging

import pytest

from backend.models import Product
from backend.scrapers.parsing import (
    PIECE,
    finalize_product,
    parse_pack,
    parse_quantity,
    parse_unit_price,
    quantity_spans,
    valid_ean,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        # Backlog B36
        ("1L5", (1.5, "L")),
        ("6x1L5", (9.0, "L")),
        ("Lot de 3 bouteilles de 1L", (3.0, "L")),
        ("6 bouteilles de 1,5L", (9.0, "L")),
        ("Pack 6 bouteilles 1,5 L", (9.0, "L")),
        ("2 x 1 L + 1 offert", (3.0, "L")),
        ("1L + 20% gratuit", (1.2, "L")),
        ("Oeufs x12", (12.0, PIECE)),
        # More shapes seen on the sites
        ("1L50", (1.5, "L")),
        ("Eau minérale 6x1,5L", (9.0, "L")),
        ("Pack de 6 x 50cl", (3.0, "L")),
        ("Bière 33cl x 6", (1.98, "L")),
        ("Yaourt nature 4x125g", (0.5, "kg")),
        ("Lot de 2 paquets de 500g", (1.0, "kg")),
        ("500g + 50% gratuit", (0.75, "kg")),
        ("100 gr", (0.1, "kg")),
        ("le kg", (1.0, "kg")),
        ("Tomates grappe au kg", (1.0, "kg")),
        ("la pièce", (1.0, PIECE)),
        ("12 œufs frais", (12.0, PIECE)),
        ("Papier toilette 6 rouleaux", (6.0, PIECE)),
        ("Lessive 40 lavages", (40.0, PIECE)),
        ("Couches x 52", (52.0, PIECE)),
        ("Café 10 capsules", (10.0, PIECE)),
        ("3 x 4 yaourts", (12.0, PIECE)),
        ("Lot de 6", (6.0, PIECE)),
        ("Oeufs x12 + 2 offerts", (14.0, PIECE)),
        ("T45", None),
        ("1 l'huile", None),
        ("", None),
        (None, None),
    ],
)
def test_contents(text, expected):
    assert parse_quantity(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        # Contents offered in kg or L, not only items or a share
        ("Huile de tournesol 1L + 50cl offerts", (1.5, "L")),
        ("Coca 1,5L + 50cl gratuit", (2.0, "L")),
        ("Huile 1L + 50 cl offerte", (1.5, "L")),
        ("Lessive 2 kg + 250 g offerts", (2.25, "kg")),
        ("6 x 1L + 1L offert", (7.0, "L")),
        ("Eau 6x1,5L + 50cl offerts", (9.5, "L")),
        # Another family of unit: nothing added
        ("Café 250g + 50cl offerts", (0.25, "kg")),
    ],
)
def test_contents_offered(text, expected):
    assert parse_quantity(text) == expected


@pytest.mark.parametrize(
    "text, label",
    [
        ("Oeufs x12", "œuf"),
        ("12 œufs", "œuf"),
        ("Papier toilette 6 rouleaux", "rouleau"),
        ("Lessive 40 lavages", "lavage"),
        ("Couches x 52", "couche"),
        ("Café 10 capsules", "capsule"),
        ("x12", None),
        ("la pièce", None),
    ],
)
def test_what_is_counted(text, label):
    pack = parse_pack(text)
    assert pack.unit == PIECE
    assert pack.count_label == label


@pytest.mark.parametrize(
    "text, expected",
    [
        # Backlog B36
        ("0,35 €/100gr", (3.5, "kg")),
        ("1 kg = 12 €", (12.0, "kg")),
        ("2,49 € / 500 g", (4.98, "kg")),
        ("1,99 € / 75 cl", (2.65, "L")),
        # More shapes
        ("3,45 € / KG", (3.45, "kg")),
        ("KG = 0.69", (0.69, "kg")),
        ("1 L = 1,58 €", (1.58, "L")),
        ("Prix au litre : 1,20 €", (1.2, "L")),
        ("0,85 € / KG", (0.85, "kg")),
        ("1,23 € la pièce", (1.23, PIECE)),
        ("2,50 € / U", (2.5, PIECE)),
        ("0,25 €/œuf", (0.25, PIECE)),
        ("1,99 € les 6 oeufs", (0.33, PIECE)),
        ("0,12 € / lavage", (0.12, PIECE)),
        ("Le sachet de 500 g : 2,49 €", (4.98, "kg")),
        ("€/Kg", None),
        ("", None),
    ],
)
def test_price_per_unit(text, expected):
    assert parse_unit_price(text) == expected


def test_finalize_computes_the_price_per_piece_with_what_is_counted():
    eggs = finalize_product(Product(store="x", name="Oeufs frais x12", price=3.0))
    assert (eggs.unit_price, eggs.unit, eggs.count_label) == (0.25, PIECE, "œuf")

    labelled = finalize_product(Product(store="x", name="Oeufs", price=3.0, unit_price_label="0,25 €/œuf"))
    assert (labelled.unit_price, labelled.unit, labelled.count_label) == (0.25, PIECE, "œuf")


def test_finalize_reads_the_contents_label_first():
    water = finalize_product(Product(store="x", name="Eau minérale", price=1.8, quantity_label="6x1L5"))
    assert (water.unit_price, water.unit) == (0.2, "L")


def test_finalize_names_the_units_the_same_way():
    carrefour = finalize_product(Product(store="x", name="Laitue", price=0.99, unit_price=0.99, unit="U"))
    assert carrefour.unit == PIECE
    assert finalize_product(Product(store="x", name="Lait", price=1.0, unit_price=1.0, unit="l")).unit == "L"


def test_finalize_rejects_a_price_per_unit_3_times_off(caplog):
    # The site says 0,19 €/kg for 1,90 € the kilo: a typo of the site
    with caplog.at_level(logging.WARNING, logger="prixmalin.parsing"):
        product = finalize_product(
            Product(store="aldi", name="Farine de blé", price=1.9, quantity_label="1 kg", unit_price_label="0,19 €/kg")
        )
    assert (product.unit_price, product.unit) == (1.9, "kg")
    assert "écarté" in caplog.text

    close = finalize_product(
        Product(store="aldi", name="Farine", price=1.9, quantity_label="1 kg", unit_price=1.5, unit="kg")
    )
    assert close.unit_price == 1.5  # the site may round or use another contents: kept


def test_finalize_never_mixes_units():
    cream = finalize_product(
        Product(store="x", name="Crème fraîche 20cl", price=0.9, unit_price_label="4,50 € / L", quantity_label="20 cl")
    )
    assert (cream.unit_price, cream.unit) == (4.5, "L")
    by_weight = finalize_product(
        Product(
            store="x", name="Crème fraîche épaisse", price=1.5, unit_price_label="7,50 €/kg", quantity_label="20 cl"
        )
    )
    assert (by_weight.unit_price, by_weight.unit) == (7.5, "kg")  # shown by the site, not compared to the litre


def test_quantities_found_in_a_query():
    assert quantity_spans("eau 1,5 l") == [(4, 9)]
    assert quantity_spans("eau 6x1,5L gazeuse") == [(4, 10)]
    assert quantity_spans("farine") == []


@pytest.mark.parametrize(
    "value, expected",
    [
        ("3560070472888", "3560070472888"),
        (" 3229820129488 ", "3229820129488"),
        (3560070472888, "3560070472888"),
        ("96385074", "96385074"),  # EAN-8
        ("036000291452", "0036000291452"),  # UPC-A
        ("3560070472889", None),  # wrong check digit
        ("356007047288", None),
        ("0000000000000", None),
        ("abc", None),
        ("", None),
        (None, None),
        (True, None),
    ],
)
def test_valid_ean(value, expected):
    assert valid_ean(value) == expected
