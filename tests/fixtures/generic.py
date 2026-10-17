"""Pages shared by several scrapers: a home page, an anti-robot challenge."""

HOME_PAGE = "<!DOCTYPE html><html><head><title>Accueil</title></head><body>Bienvenue</body></html>"

DATADOME_PAGE = (
    "<!DOCTYPE html><html><head><title>intermarche.com</title></head><body>"
    "<iframe src='https://geo.captcha-delivery.com/captcha/?initialCid=x'></iframe></body></html>"
)

# A product page with its JSON-LD (gtin13, availability)
JSON_LD_PRODUCT = """{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Huile de tournesol",
  "brand": {"@type": "Brand", "name": "Lesieur"},
  "gtin13": "3265478901236",
  "sku": "LES-1L",
  "image": ["/img/huile-tournesol.jpg"],
  "url": "/p/huile-de-tournesol-lesieur",
  "offers": {"@type": "Offer", "price": "2.65", "availability": "https://schema.org/OutOfStock"}
}"""

JSON_LD_PAGE = (
    "<!DOCTYPE html><html><head><title>Huile</title>"
    f'<script type="application/ld+json">{JSON_LD_PRODUCT}</script></head><body>Huile</body></html>'
)
