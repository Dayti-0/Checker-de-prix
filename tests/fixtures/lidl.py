"""Lidl: search API response (P2)."""

LIDL_SEARCH = {
    "numFound": 2,
    "items": [
        {
            "gridbox": {
                "data": {
                    "productId": 100012,
                    "fullTitle": "Farine de blé T55",
                    "canonicalUrl": "/p/farine-de-ble-t55/p100012",
                    "image": "https://www.lidl.fr/assets/farine.jpg",
                    "brand": {"name": "Belbake"},
                    "keyfacts": {"supplementalDescription": "1 kg"},
                    "price": {"price": 0.75, "oldPrice": 0.89, "basePrice": {"text": "1 kg (1 kg = 0,75 €)"}},
                }
            }
        },
        {
            "gridbox": {
                "data": {
                    "productId": 100013,
                    "fullTitle": "Farine de seigle",
                    "canonicalUrl": "/p/farine-de-seigle/p100013",
                    "price": {"price": 1.29, "basePrice": {"text": "750 g (1 kg = 1,72 €)"}},
                }
            }
        },
    ],
}


def _lidl_item(product_id, title, price, base_price, ean=None):
    data = {
        "productId": product_id,
        "fullTitle": title,
        "canonicalUrl": f"/p/{title.lower().replace(' ', '-')}/p{product_id}",
        "price": {"price": price, "basePrice": {"text": base_price}},
    }
    if ean:
        data["ians"] = [ean]
    return {"gridbox": {"data": data}}


# Two answers of the API: 3 products found, 2 in the first answer, the third at offset 2
LIDL_SEARCH_PAGE1 = {"numFound": 3, "offset": 0, "items": LIDL_SEARCH["items"]}
LIDL_SEARCH_PAGE2 = {
    "numFound": 3,
    "offset": 2,
    "items": [_lidl_item(100014, "Farine de blé complète", 1.15, "1 kg (1 kg = 1,15 €)", ean="3200411000010")],
}
