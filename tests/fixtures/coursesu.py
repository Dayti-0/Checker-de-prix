"""Courses U: search page (P4)."""

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
