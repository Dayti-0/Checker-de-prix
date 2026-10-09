"""Pages shared by several scrapers: a home page, an anti-robot challenge."""

HOME_PAGE = "<!DOCTYPE html><html><head><title>Accueil</title></head><body>Bienvenue</body></html>"

DATADOME_PAGE = (
    "<!DOCTYPE html><html><head><title>intermarche.com</title></head><body>"
    "<iframe src='https://geo.captcha-delivery.com/captcha/?initialCid=x'></iframe></body></html>"
)
