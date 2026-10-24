"""E.Leclerc Drive: pages and answers of the site (P8).

**Real** excerpts (provenance at the top of each file of tests/fixtures/leclerc_data/,
copied as is from public repositories; 2025 structures, to refresh from
``data/debug/leclerc-*.html`` after the first trial on the PC):

- ``LECLERC_SEARCH_HTML``: search page « coca cola 1,75 l » of the drive 173301
  Bruges (fd12), 27/09/2025, reduced to its widgets (17 products + 3 of the own
  brand, ``iNbTotalProduits`` 17);
- ``LECLERC_TILES_HTML``: the same kind of page of 24/09/2025 with its 6
  rendered tiles ``li.liWCRS310_Product`` (fallback read in the page);
- ``LECLERC_HOME_HTML``: home page of the drive (banner ``BandeauMultiUnivers``
  and one carousel), November 2025;
- ``LECLERC_ELEMENTS``: 10 ``objElement`` chosen in those pages (normal,
  immediate discount, unavailable, mixed lots, kg, g, L, piece);
- ``LECLERC_CAPTCHA_HTML``: DataDome captcha page (``t=fe``), 20/11/2025.

**Reconstructed** (marked as such): the « Access blocked. » page (text of a
real screenshot), its parent page (``t=bv``), a « session expirée » page, the
portal and a search page without product (the real search page emptied).

**SYNTHETIC**: the answers of the store finder ``api-recherchemagasins``
(shape of skunkobi/mcp-leclerc-drive docs/api-capture.md, values made up
except the drive numbers and hosts quoted there).
"""

import json
import re
from pathlib import Path

DATA = Path(__file__).with_name("leclerc_data")

LECLERC_BASE = "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges"
LECLERC_HOME_URL = LECLERC_BASE + ".aspx"
LECLERC_SEARCH_HTML = (DATA / "recherche_coca_bruges_2025-09-27.html").read_text(encoding="utf-8")
LECLERC_TILES_HTML = (DATA / "recherche_coca_bruges_2025-09-24.tuiles.html").read_text(encoding="utf-8")
LECLERC_HOME_HTML = (DATA / "accueil_drive_bruges_2025-11.html").read_text(encoding="utf-8")
LECLERC_CAPTCHA_HTML = (DATA / "datadome_captcha_2025-11-20.html").read_text(encoding="utf-8")
# [{"_source", "_cas", "objElement", "lstEnfants"}, ...]
LECLERC_ELEMENTS = json.loads((DATA / "elements_selection_2025.json").read_text(encoding="utf-8"))


def leclerc_element(product_id: int) -> dict:
    """The ``objElement`` of ``LECLERC_ELEMENTS`` with this ``iIdProduit`` (a copy)."""
    item = next(e for e in LECLERC_ELEMENTS if e["objElement"]["iIdProduit"] == product_id)
    return json.loads(json.dumps(item["objElement"]))


def _emptied(page: str) -> str:
    """RECONSTRUCTED: the real search page with no product (lists emptied, total 0)."""
    page = re.sub(r'"iNbTotalProduits"\s*:\s*\d+', '"iNbTotalProduits":0', page)
    start = page.index("pnlElementProduit',")
    head, tail = page[:start], page[start:]
    obj_start = tail.index("{")
    options, end = json.JSONDecoder().raw_decode(tail, obj_start)
    for key in ("objContenu", "objContenuMDD"):
        if isinstance(options.get(key), dict):
            options[key]["lstElements"] = []
    return head + tail[:obj_start] + json.dumps(options, ensure_ascii=False) + tail[end:]


LECLERC_EMPTY_HTML = _emptied(LECLERC_SEARCH_HTML)

# RECONSTRUCTED from a real screenshot (DataDome block page with the E.Leclerc
# logo, before 17/12/2025): the text of the frame geo.captcha-delivery.com
LECLERC_ACCESS_BLOCKED_HTML = """<!-- RECONSTITUÉ (texte d'une capture d'écran réelle, avant le 17/12/2025) -->
<html lang="en"><head><title>leclercdrive.fr</title></head><body>
<div class="logo"><img alt="E.Leclerc" src="https://img.captcha-delivery.com/b/logo.png"></div>
<p class="title">Access blocked.</p>
<div class="footer">
<p>We detected unusual activity from your device or network.</p>
<p>Reasons may include:</p>
<ul><li>Rapid taps or clicks</li><li>JavaScript disabled or not working</li>
<li>Automated (bot) activity on your network (IP 192.0.2.10)</li><li>Use of developer or inspection tools</li></ul>
<p>Need help? <a href="#">Submit feedback.</a></p>
<p>ID: 00000000-0000-0000-0000-000000000000</p>
</div></body></html>"""

# RECONSTRUCTED: the parent page of a hard block (the real captcha page with t=bv)
LECLERC_HARD_BLOCK_HTML = LECLERC_CAPTCHA_HTML.replace("'t':'fe'", "'t':'bv'").replace(
    "&amp;t=fe&amp;", "&amp;t=bv&amp;"
)

# RECONSTRUCTED: the French page « Accès temporairement restreint »
LECLERC_RESTRICTED_HTML = """<!-- RECONSTITUÉ -->
<html lang="fr"><head><title>leclercdrive.fr</title></head><body>
<p>Accès temporairement restreint</p><p>Nous avons détecté une activité inhabituelle.</p></body></html>"""

# RECONSTRUCTED: a page of the site after a long idle time (skunkobi client.ts)
LECLERC_SESSION_HTML = """<!-- RECONSTITUÉ -->
<!DOCTYPE html><html lang="fr"><head><title>E.Leclerc DRIVE</title></head>
<body><div class="divSessionExpiree"><p>Votre session a expiré.</p>
<a href="https://www.leclercdrive.fr/">Retour à l'accueil</a></div></body></html>"""

# RECONSTRUCTED: the national portal (where a closed drive leads)
LECLERC_PORTAL_HTML = """<!-- RECONSTITUÉ -->
<!DOCTYPE html><html lang="fr"><head><title>E.Leclerc DRIVE : vos courses en ligne</title></head>
<body><input id="wpad-recherche-magasin-input" placeholder="Code postal ou ville"></body></html>"""

# ---------------------------------------------------------------- store finder (SYNTHETIC)

# geo.api.gouv.fr: Montpellier 34000
LECLERC_ORIGIN = {"postal_code": "34000", "city": "Montpellier", "lat": 43.6119, "lon": 3.8772}

LECLERC_AUTOCOMPLETE = {
    "postalCodes": [{"id": "woosmap-34000-synthetique", "postalCode": "34000", "city": "Montpellier"}],
    "pointsLivraisonParNom": [],
}
LECLERC_COORDINATES = {"latitude": 43.6119, "longitude": 3.8772}

LECLERC_NEARBY = {
    "points": [
        {
            # Attested drive (number and host: Angelblot/courses-app); address made up
            "name": "Le Crès Montpellier",
            "noPL": "093401",
            "noPR": "093401",
            "serviceType": "drive",
            "distance": 6.1,
            "address": "Route de Nîmes",
            "postalCode": "34920",
            "city": "Le Crès",
            "coordinates": {"latitude": 43.6481, "longitude": 3.9395},
            "urlSiteCourse": "https://fd3-courses.leclercdrive.fr/",
            "urlBase": "https://fd3-courses.leclercdrive.fr/",
        },
        {
            # Pedestrian pick-up point, nearer: listed, never chosen automatically
            "name": "Montpellier Comédie",
            "noPL": "093401",
            "noPR": "193402",
            "serviceType": "relais",
            "distance": 0.4,
            "address": "Place de la Comédie",
            "postalCode": "34000",
            "city": "Montpellier",
            "coordinates": {"latitude": 43.6085, "longitude": 3.8797},
            "urlSiteCourse": "fd3-courses.leclercdrive.fr",
        },
        {
            # Whole address of the drive; no coordinates: the distance of the site is used
            "name": "Saint-Jean-de-Védas",
            "noPL": "190501",
            "noPR": "190501",
            "serviceType": "drive",
            "distance": 5.0,
            "postalCode": "34430",
            "city": "Saint-Jean-de-Védas",
            "urlSiteCourse": "https://fd3-courses.leclercdrive.fr/magasin-190501-190501-Saint-Jean-de-Vedas.aspx",
        },
        {
            # Generic host (redirects to the right one); « Lattes » is nearer than Le Crès
            "name": "Lattes",
            "noPL": "190601",
            "noPR": "190601",
            "serviceType": "drive",
            "distance": 4.4,
            "postalCode": "34970",
            "city": "Lattes",
            "coordinates": {"latitude": 43.5672, "longitude": 3.9000},
            "urlSiteCourse": "https://fd1-courses.leclercdrive.fr",
        },
        {
            "name": "Livraison Montpellier",
            "noPL": "190701",
            "serviceType": "livraison",
            "distance": 0.1,
            "postalCode": "34000",
        },
        {
            # Abroad (Belgian postal code): left out
            "name": "Mouscron",
            "noPL": "910101",
            "serviceType": "drive",
            "distance": 3.0,
            "postalCode": "7700",
            "urlSiteCourse": "https://fd5-courses.leclercdrive.fr/",
        },
        {
            # No urlSiteCourse: generic host and the name as slug
            "name": "Mauguio",
            "noPL": 190801,
            "serviceType": "drive",
            "distance": 11.8,
            "postalCode": "34130",
            "city": "Mauguio",
            "coordinates": {"latitude": 43.6158, "longitude": 4.0081},
        },
    ]
}
