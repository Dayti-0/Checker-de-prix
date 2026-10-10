"""Courses U: search page and store directory (P4)."""

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


# ---------------------------------------------------------------------------
# Store directory /drive-france. SYNTHETIC: written to fit the markup described
# by the research of 2026 (mcp-superU regexes: data-wrapper-store-details,
# data-store-id, data-store-name, stores-text-address, link /drive-{slug}), NOT
# a capture of the real site. Replace with an excerpt of the real page once
# data/debug/coursesu-stores.html has been saved on the PC.
#
# Stores: Roujan (11111, <br> in the address, data-store-id before the
# marker), Pézenas (&eacute;), Montpellier (relative link), Eysines (95524,
# listed twice); an entry without store link (skipped) and links to pages that
# are not stores (/drive-herault, /drive-dept-paris, /f-...-informations).
# ---------------------------------------------------------------------------

COURSESU_DIRECTORY_HTML = """<!DOCTYPE html>
<html lang="fr"><head><title>Drive et livraison de courses en France - www.coursesu.com</title>
<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script></head><body>
<nav class="breadcrumb">
  <a href="https://www.coursesu.com/drive-herault">Drive Hérault</a>
  <a href="/drive-dept-paris">Drive Paris</a>
  <a href="/drive-pieton-paris">Drive piéton</a>
</nav>
<ul class="stores-list">
  <li class="stores-item" data-store-id="11111" data-wrapper-store-details>
    <h3 class="stores-title" data-store-name>Super U Roujan</h3>
    <p class="stores-text-address">Avenue de P&eacute;zenas<br>Zone commerciale Cap Caroux<br/>34320 Roujan</p>
    <ul class="stores-services"><li>Drive</li><li>Livraison à domicile</li></ul>
    <a class="stores-link" href="https://www.coursesu.com/drive-superu-roujan">Choisir ce magasin</a>
    <a href="https://www.coursesu.com/f-superu-roujan-informations">Infos du magasin</a>
  </li>
  <li class="stores-item" data-wrapper-store-details data-store-id="22222">
    <h3 class="stores-title" data-store-name>Super U P&eacute;zenas</h3>
    <p class="stores-text-address">Route de B&eacute;ziers, 34120 P&eacute;zenas</p>
    <ul class="stores-services"><li>Drive</li><li>Retrait en magasin</li></ul>
    <a class="stores-link" href="https://www.coursesu.com/drive-superu-pezenas/">Choisir ce magasin</a>
  </li>
  <li class="stores-item" data-wrapper-store-details data-store-id="33333">
    <h3 class="stores-title" data-store-name="U Express Montpellier Pres d'Arenes"><span>U Express</span></h3>
    <p class="stores-text-address">12 avenue de Palavas<br>34070 Montpellier</p>
    <a class="stores-link" href="/drive-uexpress-montpellierpresdarenes">Choisir ce magasin</a>
  </li>
  <li class="stores-item" data-wrapper-store-details data-store-id="44444">
    <h3 class="stores-title" data-store-name>Magasin fermé</h3>
    <p class="stores-text-address">1 rue du Moulin, 34000 Montpellier</p>
  </li>
  <li class="stores-item" data-wrapper-store-details data-store-id="95524">
    <h3 class="stores-title" data-store-name>Super U Eysines</h3>
    <p class="stores-text-address">Avenue du M&eacute;doc<br>33320 Eysines</p>
    <ul class="stores-services"><li>Drive</li></ul>
    <a class="stores-link" href="https://www.coursesu.com/drive-superu-eysines">Choisir ce magasin</a>
  </li>
  <li class="stores-item" data-wrapper-store-details data-store-id="95524">
    <h3 class="stores-title" data-store-name>Super U Eysines</h3>
    <p class="stores-text-address">Avenue du M&eacute;doc<br>33320 Eysines</p>
    <a class="stores-link" href="https://www.coursesu.com/drive-superu-eysines">Choisir ce magasin</a>
  </li>
</ul>
</body></html>"""

# The same stores with other class and attribute names (SYNTHETIC): only the
# link-based reader (_DIRECTORY_LINKS_JS + cards_to_stores) can read it
COURSESU_DIRECTORY_ALT_HTML = """<!DOCTYPE html>
<html lang="fr"><head><title>Nos drives</title></head><body>
<nav><a href="/drive-herault">Hérault</a> <a href="/drive-dept-paris">Paris</a></nav>
<section class="drive-directory">
  <article class="shop" data-store-id="11111">
    <div class="shop__title"><a href="https://www.coursesu.com/drive-superu-roujan">Super U Roujan</a></div>
    <div class="shop__addr"><span>Avenue de Pézenas</span><span>34320 Roujan</span></div>
    <div class="shop__tags">Drive · Livraison</div>
  </article>
  <article class="shop" data-store-id="22222">
    <div class="shop__title"><a href="/drive-superu-pezenas">Super U Pézenas</a></div>
    <div class="shop__addr">Route de Béziers, 34120 Pézenas</div>
    <a href="/drive-superu-pezenas">Choisir</a>
  </article>
  <article class="shop">
    <div class="shop__title"><a href="/drive-uexpress-montpellierpresdarenes">U Express</a></div>
    <div class="shop__addr"><span>12 avenue de Palavas</span><span>34070 Montpellier</span></div>
  </article>
  <article class="shop" data-store-id="95524">
    <div class="shop__title"><a href="/drive-superu-eysines">Super U Eysines</a></div>
    <div class="shop__addr"><span>Avenue du Médoc</span><span>33320 Eysines</span></div>
    <div class="shop__tags">Drive</div>
  </article>
</section>
</body></html>"""

# Cloudflare check instead of the directory
COURSESU_CHALLENGE_HTML = """<!DOCTYPE html>
<html><head><title>Just a moment...</title></head><body>
<div id="challenge-running"></div>
<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script>
</body></html>"""

# geo.api.gouv.fr /communes?fields=nom,codesPostaux,centre (excerpt, coordinates
# rounded). 34320 is shared by several towns: Gabian is listed before Roujan.
COMMUNES_JSON = [
    {"nom": "Gabian", "codesPostaux": ["34320"], "centre": {"type": "Point", "coordinates": [3.2742, 43.5106]}},
    {"nom": "Roujan", "codesPostaux": ["34320"], "centre": {"type": "Point", "coordinates": [3.3108, 43.5050]}},
    {"nom": "Pézenas", "codesPostaux": ["34120"], "centre": {"type": "Point", "coordinates": [3.4236, 43.4590]}},
    {
        "nom": "Montpellier",
        "codesPostaux": ["34000", "34070", "34080", "34090"],
        "centre": {"type": "Point", "coordinates": [3.8767, 43.6109]},
    },
    {"nom": "Eysines", "codesPostaux": ["33320"], "centre": {"type": "Point", "coordinates": [-0.6497, 44.8836]}},
    {"nom": "Lattes", "codesPostaux": ["34970"], "centre": {"type": "Point", "coordinates": [3.9030, 43.5676]}},
    {"nom": "Sans centre", "codesPostaux": ["99998"]},
]
