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
