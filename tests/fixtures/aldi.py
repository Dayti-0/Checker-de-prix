"""Aldi: search page with product tiles (P2)."""

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
