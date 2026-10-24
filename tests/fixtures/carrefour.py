"""Carrefour: search API response and search page (P2)."""

CARREFOUR_SEARCH = {
    "data": [
        {
            "type": "product",
            "id": "3560070472888",
            "attributes": {
                "ean": "3560070472888",
                "title": "Farine de blé T45",
                "brand": "CARREFOUR CLASSIC'",
                "slug": "farine-de-ble-t45-carrefour-classic",
                "format": "1kg",
                "images": [
                    {"large": "/media/540x540/Photosite/farine.jpg", "medium": "/media/280x280/Photosite/farine.jpg"}
                ],
                "offers": {
                    "3560070472888": {
                        "0001_1": {
                            "type": "offer",
                            "id": "0001_1",
                            "attributes": {
                                "price": {
                                    "price": 0.85,
                                    "perUnit": 0.85,
                                    "perUnitLabel": "0,85 € / KG",
                                    "unitOfMeasure": "KG",
                                },
                                "availability": {"purchasable": True},
                                "promotion": {"label": "2ème à -50%"},
                            },
                        }
                    }
                },
            },
        },
        {
            "type": "product",
            "id": "3229820129488",
            "attributes": {
                "ean": "3229820129488",
                "title": "Farine de blé fluide T45",
                "brand": "FRANCINE",
                "slug": "farine-de-ble-fluide-t45-francine",
                "offers": {
                    "3229820129488": {
                        "0001_1": {
                            "attributes": {
                                "price": {"price": 1.89, "perUnitLabel": "1,89 € / KG"},
                                "availability": {"purchasable": False},
                            }
                        }
                    }
                },
            },
        },
    ],
    "meta": {"total": 2},
}

CARREFOUR_PAGE = """<!DOCTYPE html>
<html><head><title>farine - Carrefour</title></head><body>
<ul>
  <li><article class="x1">
    <a href="/p/farine-de-ble-t45-carrefour-classic-3560070472888"><img src="/media/farine.jpg" alt="Farine T45">
      <h3>Farine de blé T45 CARREFOUR CLASSIC'</h3></a>
    <div class="x2"><span>0</span><span>,85 €</span></div><div class="x3">0,85 € / KG</div>
    <button aria-label="Ajouter le produit au panier">+</button>
  </article></li>
  <li><article class="x1">
    <a href="/p/farine-francine-3229820129488"><h3>Farine fluide FRANCINE</h3></a>
    <div class="x2">1,89 €</div>
  </article></li>
</ul>
</body></html>"""


def _carrefour_item(ean, title, brand, price, per_unit_label, images=None):
    return {
        "type": "product",
        "id": ean,
        "attributes": {
            "ean": ean,
            "title": title,
            "brand": brand,
            "slug": title.lower().replace(" ", "-"),
            "format": "1kg",
            "images": images or [{"large": f"/media/540x540/Photosite/{ean}.jpg"}],
            "offers": {
                ean: {"0001_1": {"attributes": {"price": {"price": price, "perUnitLabel": per_unit_label}}}},
            },
        },
    }


# Two pages of a search: page 1 says there are 3 products, page 2 holds the
# third one and again one of page 1 (merged once)
CARREFOUR_SEARCH_PAGE1 = {
    "data": CARREFOUR_SEARCH["data"],
    "meta": {"total": 3},
    "links": {"self": "/s?q=farine&page=1", "next": "/s?q=farine&page=2"},
}
CARREFOUR_SEARCH_PAGE2 = {
    "data": [
        _carrefour_item("3560070123452", "Farine de blé T55", "CARREFOUR CLASSIC'", 0.79, "0,79 € / KG"),
        CARREFOUR_SEARCH["data"][0],
    ],
    "meta": {"total": 3},
}
