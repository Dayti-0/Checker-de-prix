"""E.Leclerc Drive: products of the real search pages of 2025 (pure functions, P8)."""

import json

import pytest

from backend.models import Product
from backend.scrapers import leclerc
from backend.scrapers.leclerc import (
    element_to_product,
    page_widgets,
    parse_search_html,
    product_elements,
    scan_product_records,
    search_url,
    split_line2,
    tiles_to_products,
    widget,
)
from backend.services.products import is_store_brand, prepare_products
from tests import fixtures
from tests.fixtures.leclerc import LECLERC_BASE, leclerc_element

BASE = LECLERC_BASE


def product(product_id: int) -> Product:
    return element_to_product(leclerc_element(product_id), BASE)


# ---------------------------------------------------------------- widgets


def test_widgets_of_the_real_search_page():
    widgets = page_widgets(fixtures.LECLERC_SEARCH_HTML)
    suffixes = [wid.rsplit("_", 1)[-1] for wid in widgets]
    assert suffixes == ["BandeauMultiUnivers", "pnlCartouchePanier", "pnlBlocsFiltres", "panelTri", "pnlElementProduit"]
    # Found by the end of their id (the start changes with the page)
    results = widget(widgets, "pnlElementProduit")
    assert len(results["objContenu"]["lstElements"]) == 17
    assert len(results["objContenuMDD"]["lstElements"]) == 3
    assert widget(widgets, "pnlBlocsFiltres")["iNbTotalProduits"] == 17
    assert widget(widgets, "Inconnu") is None


def test_truncated_json_gives_nothing():
    text = fixtures.LECLERC_SEARCH_HTML
    cut = text[: text.index("pnlElementProduit',") + 400]
    assert widget(page_widgets(cut), "pnlElementProduit") is None
    assert page_widgets("") == {} and page_widgets("<html>rien</html>") == {}
    page = parse_search_html(cut, BASE)
    assert page.products == [] and page.source is None


def test_real_search_page():
    page = parse_search_html(fixtures.LECLERC_SEARCH_HTML, BASE)
    assert page.source == "api"
    assert len(page.products) == 20
    assert (page.total, page.listed, page.truncated) == (17, 17, False)
    assert page.store_page and page.store_no == "173301" and page.store_name == "Bruges"
    assert page.store_url == "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges.aspx"
    assert all(p.store == "leclerc" for p in page.products)
    # The 3 products of the own brand list come last, flagged by the site itself
    own = [p for p in page.products if p.store_brand]
    assert [p.name for p in own] == [
        "Soda Jean's Cola sans Caféine Zéro",
        "Soda Jean's Cola Zéro",
        "Soda Jean's Cola Cherry",
    ]
    assert page.products[-3:] == own
    assert all(p.store_brand is None for p in page.products[:-3])
    # Identifier of the product (national: 123422 at Bruges as at Bordeaux), never a lot code as barcode
    assert page.products[0].sku == "214087"
    assert all(p.ean is None for p in page.products)
    assert all(p.image_url.startswith("https://fd12-photos.leclercdrive.fr/image.ashx?id=") for p in page.products)
    assert all(p.product_url.startswith(BASE + "/fiche-produits-") for p in page.products)


def test_own_brand_kept_by_prepare_products():
    page = parse_search_html(fixtures.LECLERC_SEARCH_HTML, BASE)
    prepared = prepare_products(page.products, "cola")
    flags = {p.sku: p.store_brand for p in prepared}
    assert flags["12464"] is True and flags["214087"] is not True
    # Also known from the name alone (« Jean's » is an own brand of E.Leclerc)
    assert is_store_brand(Product(store="leclerc", name="Soda Jean's Cola Zéro")) is True
    assert is_store_brand(Product(store="leclerc", name="Farine", brand="Bio Village")) is True
    assert is_store_brand(Product(store="leclerc", name="Café", brand="Méo")) is False


def test_total_beyond_the_products_read_is_truncated():
    text = fixtures.LECLERC_SEARCH_HTML.replace('"iNbTotalProduits":17', '"iNbTotalProduits":200')
    assert text != fixtures.LECLERC_SEARCH_HTML
    page = parse_search_html(text, BASE)
    assert (page.total, page.listed, page.truncated) == (200, 17, True)


def test_page_of_a_drive_without_product():
    page = parse_search_html(fixtures.LECLERC_EMPTY_HTML, BASE)
    assert page.products == [] and page.source is None
    assert page.store_page and page.total == 0


def test_home_page_of_the_drive_lists_no_result():
    """The carousels of the home page are not search results."""
    page = parse_search_html(fixtures.LECLERC_HOME_HTML, BASE, search_page=False)
    assert page.products == []
    assert (page.store_no, page.store_name) == ("173301", "Bruges")
    page = parse_search_html(fixtures.LECLERC_HOME_HTML, BASE)
    assert page.products == []


# ---------------------------------------------------------------- the 10 real cases


def test_normal_product_in_litres():
    p = product(214087)
    assert (p.name, p.brand, p.quantity_label, p.price, p.old_price, p.promo) == (
        "Soda Coca-Cola Original",
        None,
        "1,75L",
        2.38,
        None,
        None,
    )
    assert p.unit_price_label == "1,36 € / l" and p.available
    assert p.product_url == BASE + "/fiche-produits-214087-Soda-Coca-Cola-Original.aspx"


def test_immediate_discount():
    """« Avantage immédiat »: the price paid is the discounted one, the old one struck out."""
    p = product(129235)
    assert (p.price, p.old_price) == (8.72, 10.22)
    assert p.unit_price_label == "0,83 € / l"  # of the discount, not 0,97 € / l
    assert p.promo == "Avantage immédiat de 1.50 €"
    assert p.quantity_label == "6x1.75L"
    water = product(15305)
    assert (water.name, water.price, water.old_price, water.promo) == (
        "Eau minérale Saint Antonin",
        1.75,
        2.65,
        "Avantage immédiat de 34%",
    )
    assert water.unit_price_label == "0,29 € / l"


def test_immediate_discount_without_its_text():
    element = leclerc_element(129235)
    element["sTexteTooltipLot"] = ""
    element["sPrixPromoParUniteDeMesure"] = None
    p = element_to_product(element, BASE)
    assert p.promo == "Au lieu de 10,22 €"
    assert p.unit_price_label == "0,83 € / l"  # nrPVMesureBRIIDeduit


def test_unavailable_product_keeps_its_normal_price():
    p = product(123416)
    assert (p.price, p.old_price, p.promo, p.available) == (14.22, None, None, False)
    assert p.quantity_label == "6x1,75L"


@pytest.mark.parametrize(
    "product_id, promo",
    [(75337, "Le 2ème article à -60%"), (224818, "Le 3ème est offert"), (42563, "Le 2ème article à -68%")],
)
def test_mixed_lots_keep_the_price(product_id, promo):
    """« Le 2ème à -60 % »: the price does not change (BRII flag true for those lots too)."""
    element = leclerc_element(product_id)
    assert element["fEstBRIIActifEtDisponible"] is True and element["neTypeLotBrii"] == 2
    p = element_to_product(element, BASE)
    assert (p.price, p.old_price, p.promo) == (element["nrPVUnitaireTTC"], None, promo)


def test_kilograms_grams_and_own_brand_of_the_second_line():
    flour = product(5125)
    assert (flour.name, flour.brand, flour.quantity_label, flour.price) == (
        "Farine de blé bio T65",
        "Bio Village",
        "1kg",
        0.99,
    )
    # « Recevez 20% en Ticket E.Leclerc »: loyalty card, no lower price at the till
    assert flour.promo is None and flour.old_price is None
    yoghurts = product(20010)
    assert (yoghurts.brand, yoghurts.quantity_label, yoghurts.unit_price_label) == (
        "Bio Village",
        "12x125g",
        "1,64 € / kg",
    )
    coffee = product(75337)
    assert (coffee.name, coffee.quantity_label) == ("Café en grains Méo L'original Bio", "500g")


def test_piece_without_price_per_kg():
    p = product(167220)
    assert p.name == "Calendrier de l'Avent Smarties chocolat Noël"
    assert p.unit_price_label is None and p.price == 10.95


def test_html_entities_are_decoded():
    names = [product(e["objElement"]["iIdProduit"]).name for e in fixtures.LECLERC_ELEMENTS]
    assert not any("&#" in n or "&amp;" in n for n in names)
    assert "Riz Basmati Ben's original Express 2mn" in names


def test_unit_prices_after_prepare_products():
    prepared = {p.sku: p for p in prepare_products([product(e) for e in (214087, 129235, 5125, 20010)], "x")}
    assert (prepared["214087"].unit_price, prepared["214087"].unit) == (1.36, "L")
    assert (prepared["129235"].unit_price, prepared["129235"].unit) == (0.83, "L")
    assert (prepared["5125"].unit_price, prepared["5125"].unit) == (0.99, "kg")
    assert (prepared["20010"].unit_price, prepared["20010"].unit) == (1.64, "kg")


def test_barcode_and_identifier():
    element = leclerc_element(214087)
    element["sCodeLotHeterogene"] = "3614708000017"
    element["sIdUniqueBrii"] = "3614708000024"
    assert element_to_product(element, BASE).ean is None  # lot codes are no barcodes
    element["sCodeEAN"] = "5449000000439"
    element["sLibelleMarque"] = "Coca-Cola"
    p = element_to_product(element, BASE)
    assert (p.ean, p.sku, p.brand) == ("5449000000439", "214087", "Coca-Cola")
    element["sCodeEAN"] = "123"
    assert prepare_products([element_to_product(element, BASE)], "coca")[0].ean is None


def test_sold_out_and_stock():
    element = leclerc_element(214087)
    element["fProduitEpuise"] = True
    assert not element_to_product(element, BASE).available
    element = leclerc_element(214087)
    element["iQteDisponible"] = 0
    assert not element_to_product(element, BASE).available
    element.pop("iQteDisponible")
    assert element_to_product(element, BASE).available


def test_product_page_on_another_site_is_not_kept():
    element = leclerc_element(214087)
    element["sUrlPageProduit"] = "https://evil.example.com/x"
    assert element_to_product(element, BASE).product_url == BASE
    element["sUrlPageProduit"] = "javascript:alert(1)"
    assert element_to_product(element, BASE).product_url == BASE


def test_not_a_product():
    assert element_to_product({"sLibelleLigne1": "x"}, BASE) is None
    assert element_to_product({"iIdProduit": 1, "sType": "Publicite", "sLibelleLigne1": "x"}, BASE) is None
    assert element_to_product({"iIdProduit": 1, "sLibelleLigne1": "  "}, BASE) is None
    assert product_elements(None) == [] and product_elements({"objContenu": {"lstElements": "x"}}) == []


@pytest.mark.parametrize(
    "line, expected",
    [
        ("Bouteille - 1,75L ", ("1,75L", None, "")),
        ("Bouteille - Pack 6x1,75L ", ("6x1,75L", None, "")),
        ("6x1L", ("6x1L", None, "")),
        ("Bio Village - 1kg", ("1kg", "Bio Village", "")),
        ("Bio village - 12x125g", ("12x125g", "Bio Village", "")),
        ("L&#39;original Bio - 500g", ("500g", None, "L'original Bio")),
        ("Express 2mn - 220g", ("220g", None, "Express 2mn")),
        ("La bouteille de 1.75L", ("1.75L", None, "")),
        ("Marque Repère - Le paquet de 1kg", ("1kg", "Marque Repère", "")),
        ("", (None, None, "")),
        # Real lines of 11/2025: a count and a weight or a volume, both kept as the site shows them
        ("x8 - 320g", ("x8 - 320g", None, "")),
        ("Gingembre Citron vert x20 - 36g", ("x20 - 36g", None, "Gingembre Citron vert")),
        ("25 lavages - 1.25L", ("25 lavages - 1.25L", None, "")),
        ("x30 pralines - 375g", ("x30 - 375g", None, "pralines")),
        ("Extra fins x17 - 240g", ("x17 - 240g", None, "Extra fins")),
    ],
)
def test_split_line2(line, expected):
    assert split_line2(line) == expected


def test_count_and_weight_give_the_price_per_kg():
    """« x8 - 320g »: the weight is the quantity (price per kg), not 8 pieces."""
    element = {"iIdProduit": 1, "sLibelleLigne1": "Croissants Epi d'Or", "sLibelleLigne2": "x8 - 320g"}
    element["nrPVUnitaireTTC"] = 1.62
    product = prepare_products([element_to_product(element, BASE)], "croissants")[0]
    assert product.quantity_label == "x8 - 320g"
    assert (product.unit, product.unit_price) == ("kg", 5.06)


@pytest.mark.parametrize(
    "query, expected",
    [
        ("farine", f"{BASE}/recherche.aspx?TexteRecherche=farine"),
        ("coca cola 1,75 l", f"{BASE}/recherche.aspx?TexteRecherche=coca%20cola%201%2C75%20l"),
        ("pâtes", f"{BASE}/recherche.aspx?TexteRecherche=p%C3%A2tes"),
        ("a&b=c/d", f"{BASE}/recherche.aspx?TexteRecherche=a%26b%3Dc%2Fd"),
        ("x" * 50, f"{BASE}/recherche.aspx?TexteRecherche={'x' * 40}"),
    ],
)
def test_search_url(query, expected):
    assert search_url(BASE, query) == expected


# ---------------------------------------------------------------- fallbacks


def test_widget_id_changed():
    """The results widget has another id: its lists are still found."""
    text = fixtures.LECLERC_SEARCH_HTML.replace("_pnlElementProduit'", "_pnlListeArticles'")
    page = parse_search_html(text, BASE)
    assert page.source == "api" and len(page.products) == 20


def test_structure_around_the_products_changed():
    """No ``lstElements`` any more: every object holding ``iIdProduit`` is read."""
    elements = [e["objElement"] for e in fixtures.LECLERC_ELEMENTS]
    text = (
        "<script>Utilitaires.widget.initOptions('ctl00_main_pnlNouveau', "
        + json.dumps({"resultats": {"articles": elements}})
        + ");</script>"
    )
    assert len(scan_product_records(text)) == 10
    page = parse_search_html(text, BASE)
    assert page.source == "api" and len(page.products) == 10
    assert len(scan_product_records(json.dumps({"a": [{"iIdProduit": 1, "x": {"y": 2}}]}))) == 1


def test_generic_reader_when_nothing_else_works():
    data = {"items": [{"name": "Farine de blé T45", "price": 0.89, "url": BASE + "/fiche-produits-1-farine.aspx"}]}
    text = f"<script>Utilitaires.widget.initOptions('ctl00_main_pnlAutre', {json.dumps(data)});</script>"
    page = parse_search_html(text, BASE)
    assert page.source == "generic"
    assert [(p.name, p.price) for p in page.products] == [("Farine de blé T45", 0.89)]


# Tiles collected by leclerc._TILES_JS on the real page of 24/09/2025 (innerText)
TILES = [
    {
        "name": "Soda Coca-Cola Original\nBouteille - 1,75L",
        "whole": " 2 ",
        "cents": " ,38 ",
        "unit": " 1,36 € / l ",
        "unavailable": False,
        "image": "https://fd12-photos.leclercdrive.fr/image.ashx?id=2940324&use=l&cat=p&typeid=i",
    },
    {
        "name": "Soda Coca-Cola sans sucres\nBouteille - 6x1.75L",
        "whole": "8",
        "cents": ",72",
        "unit": "Au lieu de\xa010,22 €\xa0Prix conseillé par la coopérative au(x) point(s) de vente participant à "
        "l'opération commerciale\xa0\xa00,83 € / l",
        "unavailable": False,
        "image": None,
    },
    {
        "name": "Soda Coca-Cola Original\nBouteille - Pack 6x1,75L",
        "whole": "14",
        "cents": ",22",
        "unit": "",
        "unavailable": True,
    },
    {"name": "", "whole": "1", "cents": ",00"},
    "pas une tuile",
]


def test_tiles_to_products():
    products = tiles_to_products(TILES, BASE)
    assert [(p.name, p.quantity_label, p.price, p.available) for p in products] == [
        ("Soda Coca-Cola Original", "1,75L", 2.38, True),
        ("Soda Coca-Cola sans sucres", "6x1.75L", 8.72, True),
        ("Soda Coca-Cola Original", "6x1,75L", 14.22, False),
    ]
    assert products[0].unit_price_label == "1,36 € / l"
    assert (products[1].old_price, products[1].promo, products[1].unit_price_label) == (
        10.22,
        "Au lieu de 10,22 €",
        "0,83 € / l",
    )
    assert all(p.product_url == BASE for p in products)  # no link to the product in the tiles


def test_own_brands_are_those_of_the_products_service():
    from backend.services.products import STORE_BRANDS

    assert STORE_BRANDS["leclerc"] == leclerc.OWN_BRANDS
