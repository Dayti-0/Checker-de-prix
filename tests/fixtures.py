"""Sample responses shaped like the retailer sites (structures observed in 2026)."""

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

ALDI_PAGE = """<!DOCTYPE html>
<html><head><title>Recherche | ALDI France</title></head><body>
<div id="onetrust-banner-sdk">
  <button id="onetrust-accept-btn-handler" onclick="this.parentNode.remove()">Tout accepter</button>
</div>
<div class="search-results">
  <div class="product-tile">
    <a href="/produits/epicerie/farine-de-ble-t55.html">
      <div class="product-tile__image-section"><img src="/img/farine.jpg" alt="Farine de blé T55"></div>
      <div class="product-tile__content__upper__brand-name">BELBAKE</div>
      <div class="product-tile__content__upper__product-name">Farine de blé T55</div>
    </a>
    <div class="tag__marker--salesunit">1 kg</div>
    <span class="tag__label--price" data-testid="product-tile-tag-current-price-amount">0,79</span>
    <div class="tag__marker--base-price">1 kg = 0,79 €</div>
  </div>
  <div class="product-tile">
    <a href="/produits/epicerie/farine-de-sarrasin.html">
      <div class="product-tile__content__upper__product-name">Farine de sarrasin</div>
    </a>
    <div class="tag__marker--salesunit">500 g</div>
    <span class="tag__label--price" data-testid="product-tile-tag-current-price-amount">1,49</span>
  </div>
  <div class="product-tile">
    <a href="/produits/epicerie/gateau-marbre.html">
      <div class="product-tile__content__upper__product-name">Gâteau marbré</div>
    </a>
    <span class="tag__label--price" data-testid="product-tile-tag-current-price-amount">2,19</span>
  </div>
</div>
</body></html>"""

COURSESU_PAGE = """<!DOCTYPE html>
<html><head><title>Recherche farine - Courses U</title></head><body>
<div class="search-result-items">
  <div class="product-tile" data-pid="123">
    <div class="image-container"><a href="/p/farine-de-ble-t45-u/123.html">
      <img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" data-src="/images/farine-u.jpg"
           alt="Farine de blé T45 U"></a></div>
    <div class="tile-body">
      <div class="pdp-link"><a href="/p/farine-de-ble-t45-u/123.html">Farine de blé T45 U, 1kg</a></div>
      <div class="price">
        <span class="strike-through list"><span class="value" content="1.10">1,10 €</span></span>
        <span class="sales"><span class="value" content="0.95">0,95 €</span></span>
      </div>
      <div class="unit-price">0,95 € / kg</div>
      <button class="add-to-cart" data-pid="123">Ajouter</button>
    </div>
  </div>
  <div class="product-tile" data-pid="456">
    <div class="tile-body">
      <div class="pdp-link"><a href="/p/farine-francine/456.html">Farine Francine fluide 1kg</a></div>
      <div class="price"><span class="sales"><span class="value" content="1.75">1,75 €</span></span></div>
    </div>
  </div>
</div>
</body></html>"""

# Product listing with unknown class names: only the generic extractor can read it
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

HOME_PAGE = "<!DOCTYPE html><html><head><title>Accueil</title></head><body>Bienvenue</body></html>"

DATADOME_PAGE = (
    "<!DOCTYPE html><html><head><title>intermarche.com</title></head><body>"
    "<iframe src='https://geo.captcha-delivery.com/captcha/?initialCid=x'></iframe></body></html>"
)
