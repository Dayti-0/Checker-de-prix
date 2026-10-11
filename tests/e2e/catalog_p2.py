"""Fake products of the P2 E2E tests (search and results) and of the demo.

- « huile de tournesol »: food in sunflower oil cheaper than the oils (tuna,
  sardines, chips, mayonnaise): never the main list nor « Le moins cher »,
  at most « Produits proches »;
- « vinaigre »: the same product (same EAN) at Carrefour, Lidl and Intermarché
  (B38), organic with a promotion and an old price, unavailable;
- « crème fraîche »: prices per litre and per kilo mixed (B26);
- « tomate »: « Sauce tomate basilic » is a sauce (close product), « Tomates
  pelées » are tomatoes.

The names avoid the words searched by the other E2E tests (farine, blé, eau,
lait, pirate).
"""

# Same product in three retailers (valid EAN-13)
MAILLE_EAN = "3036810201006"

PRODUCTS = {
    "aldi": [
        {"name": "Thon à l'huile de tournesol", "brand": "Saint James", "price": 0.99, "quantity_label": "160 g"},
        {"name": "Sardines à l'huile de tournesol", "price": 1.15, "quantity_label": "135 g"},
        {"name": "Huile de tournesol bio", "brand": "Bio Nature", "price": 2.49, "quantity_label": "1 L"},
        {
            "name": "Vinaigre de cidre bio",
            "brand": "Bio Nature",
            "price": 1.19,
            "old_price": 1.49,
            "promo": "Au lieu de 1,49 €",
            "quantity_label": "50 cl",
            "ean": "3560070880010",
        },
        {"name": "Sauce tomate basilic", "brand": "Cucina", "price": 0.89, "quantity_label": "400 g"},
    ],
    "lidl": [
        {"name": "Mayonnaise à l'huile de tournesol", "brand": "Kania", "price": 1.09, "quantity_label": "500 ml"},
        {"name": "Chips à l'huile de tournesol", "brand": "Snack Day", "price": 0.79, "quantity_label": "150 g"},
        {"name": "Thon au naturel", "price": 1.05, "quantity_label": "140 g"},
        {
            "name": "Vinaigre de vin rouge",
            "brand": "Maille",
            "price": 2.09,
            "quantity_label": "50 cl",
            "ean": MAILLE_EAN,
        },
        {
            "name": "Crème fraîche épaisse",
            "brand": "Milbona",
            "price": 1.45,
            "quantity_label": "200 g",
            "unit_price_label": "7,25 €/kg",
        },
        {"name": "Tomates pelées", "brand": "Baresa", "price": 0.85, "quantity_label": "400 g"},
    ],
    "carrefour": [
        {
            "name": "Thon albacore à l'huile de tournesol",
            "brand": "PETIT NAVIRE",
            "price": 1.95,
            "quantity_label": "160 g",
            "ean": "3760112000011",
        },
        {
            "name": "Vinaigre de vin rouge",
            "brand": "MAILLE",
            "price": 1.95,
            "quantity_label": "50cl",
            "ean": MAILLE_EAN,
        },
        {
            "name": "Vinaigre balsamique de Modène",
            "brand": "CARREFOUR CLASSIC'",
            "price": 1.65,
            "quantity_label": "50cl",
            "ean": "3560070440016",
            "available": False,
        },
        {
            "name": "Crème fraîche épaisse",
            "brand": "CARREFOUR CLASSIC'",
            "price": 0.92,
            "quantity_label": "20cl",
            "unit_price_label": "4,60 € / L",
        },
    ],
    "intermarche": [
        {
            "name": "Vinaigre de vin rouge",
            "brand": "Maille",
            "price": 2.05,
            "quantity_label": "50 cl",
            "ean": MAILLE_EAN,
        },
    ],
    "coursesu": [
        {"name": "Pâtes sauce tomate", "brand": "U", "price": 1.79, "quantity_label": "300 g"},
    ],
}
