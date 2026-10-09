from backend.scrapers import SCRAPERS, carrefour, intermarche, lidl
from backend.scrapers.coursesu import is_store_url, store_name_from_url
from backend.scrapers.parsing import finalize_product
from tests import fixtures


def test_registry_contains_the_five_retailers():
    assert list(SCRAPERS) == ["aldi", "lidl", "carrefour", "intermarche", "coursesu"]
    assert {k for k, s in SCRAPERS.items() if s.needs_store} == {"intermarche", "coursesu"}


def test_carrefour_json():
    products = carrefour.parse_search_json(fixtures.CARREFOUR_SEARCH)
    assert len(products) == 2
    first = products[0]
    assert first.name == "Farine de blé T45"
    assert first.brand == "CARREFOUR CLASSIC'"
    assert first.price == 0.85
    assert (first.unit_price, first.unit) == (0.85, "kg")
    assert first.product_url == "https://www.carrefour.fr/p/farine-de-ble-t45-carrefour-classic-3560070472888"
    assert first.image_url == "https://www.carrefour.fr/media/540x540/Photosite/farine.jpg"
    assert first.promo == "2ème à -50%"
    assert first.quantity_label == "1kg"
    second = finalize_product(products[1])
    assert second.available is False
    assert (second.unit_price, second.unit) == (1.89, "kg")


def test_carrefour_json_unexpected_shape():
    assert carrefour.parse_search_json({"errors": []}) == []
    assert carrefour.parse_search_json([]) == []


def test_intermarche_json():
    products = [finalize_product(p) for p in intermarche.parse_search_json(fixtures.INTERMARCHE_SEARCH)]
    first, second = products
    assert first.name == "Farine de blé T45"
    assert first.brand == "Chabrior"
    assert first.price == 0.89
    assert first.unit_price_label == "0,89 €/Kg"
    assert (first.unit_price, first.unit) == (0.89, "kg")
    assert first.promo == "Au lieu de 1,05 €"
    assert first.product_url == "https://www.intermarche.com/produit/farine-de-ble-t45/3250390018575"
    assert first.image_url == "https://cdn.intermarche.com/farine.jpg"
    assert second.available is False


def test_intermarche_older_shape():
    data = {"products": [{"libelle": "Sucre", "unitPrice": 1.2, "images": []}]}
    assert intermarche.parse_search_json(data)[0].price == 1.2


def test_intermarche_stores_sorted_by_distance():
    stores = intermarche.parse_stores(fixtures.INTERMARCHE_STORES)
    assert [s.id for s in stores] == ["06814", "08012"]
    assert stores[0].name == "Intermarché Hyper Lattes"
    assert stores[1].name == "Intermarché Super Montpellier Près d'Arènes"
    assert stores[1].address == "1 avenue de Palavas, 34070 Montpellier"
    assert stores[1].distance_km == 2.5


def test_intermarche_store_from_browser_storage():
    assert intermarche.store_from_storage({"store": "08012"}) == "08012"
    assert intermarche.store_from_storage({"store": '{"pdvRef": "06814", "name": "x"}'}) == "06814"
    analytic = '{"store": "{\\"storeRef\\":\\"01234\\"}"}'
    assert intermarche.store_from_storage({"store": "", "analytic": analytic}) == "01234"
    assert intermarche.store_from_storage({"store": "", "analytic": ""}) is None


def test_lidl_json():
    products = [finalize_product(p) for p in lidl.parse_search_json(fixtures.LIDL_SEARCH)]
    first, second = products
    assert first.name == "Farine de blé T55"
    assert first.brand == "Belbake"
    assert first.price == 0.75
    assert first.quantity_label == "1 kg"
    assert (first.unit_price, first.unit) == (0.75, "kg")
    assert first.promo == "Au lieu de 0,89 €"
    assert first.product_url == "https://www.lidl.fr/p/farine-de-ble-t55/p100012"
    assert second.quantity_label == "750 g"
    assert (second.unit_price, second.unit) == (1.72, "kg")


def test_coursesu_store_url_helpers():
    assert is_store_url("https://www.coursesu.com/drive-superu-roujan")
    assert not is_store_url("https://www.example.com/drive-superu-roujan")
    assert not is_store_url("https://www.coursesu.com/recherche?q=farine")
    assert store_name_from_url("https://www.coursesu.com/drive-superu-roujan") == "Super U Roujan"
    assert (
        store_name_from_url("https://www.coursesu.com/drive-hyperu-saint-jean-de-vedas/")
        == "Hyper U Saint Jean De Vedas"
    )
