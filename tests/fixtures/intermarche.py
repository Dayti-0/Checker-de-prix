"""Intermarché: product search and store finder API responses (P3)."""

INTERMARCHE_SEARCH = {
    "produits": [
        {
            "itemId": "41754",
            "produitEan13": "3250390018575",
            "idProduit": "3250390018575",
            "libelle": "Farine de blé T45",
            "marque": "Chabrior",
            "prix": 0.89,
            "prixBarre": 1.05,
            "prixKg": 0.89,
            "unitePrixVente": {"value": "€/Kg"},
            "conditionnement": "1 kg",
            "images": ["https://cdn.intermarche.com/farine.jpg"],
            "stock": 25,
            "dispoCataloguePdv": True,
        },
        {
            "itemId": "41755",
            "produitEan13": "3250390018576",
            "libelle": "Farine de sarrasin bio",
            "marque": "Bio Village",
            "prix": 2.35,
            "stock": 0,
        },
    ],
    "searchResultsMetaData": {"resultNbre": 2},
}

INTERMARCHE_STORES = {
    "resultats": [
        {
            "storeCode": "08012",
            "entityLabel": "Montpellier Près d'Arènes",
            "tradeNameLabel": "Intermarché Super",
            "distance": 2450,
            "addresses": [{"address": "1 avenue de Palavas", "postCode": "34070", "townLabel": "Montpellier"}],
        },
        {
            "storeCode": "06814",
            "entityLabel": "Intermarché Hyper Lattes",
            "tradeNameLabel": "Intermarché Hyper",
            "distance": 900,
            "addresses": [{"address": "Route de Mauguio", "postCode": "34970", "townLabel": "Lattes"}],
        },
    ]
}
