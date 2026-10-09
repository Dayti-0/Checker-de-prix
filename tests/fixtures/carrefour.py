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
