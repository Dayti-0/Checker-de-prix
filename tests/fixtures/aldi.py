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

_ALDI_TILE = """
  <div class="product-tile" data-article-id="{sku}">
    <a href="/produits/epicerie/{slug}.html">
      <div class="product-tile__content__upper__product-name">{name}</div>
    </a>
    <div class="tag__marker--salesunit">1 kg</div>
    <span class="tag__label--price" data-testid="product-tile-tag-current-price-amount">{price}</span>
  </div>"""


def aldi_tile(sku, slug, name, price):
    return _ALDI_TILE.format(sku=sku, slug=slug, name=name, price=price)


# A search page with a « Voir plus de produits » button: the site adds the next tiles
ALDI_PAGE_MORE = (
    """<!DOCTYPE html>
<html><head><title>Recherche | ALDI France</title></head><body>
<div class="search-results">"""
    + aldi_tile("1001", "farine-de-ble-t55", "Farine de blé T55", "0,79")
    + aldi_tile("1002", "farine-de-sarrasin", "Farine de sarrasin", "1,49")
    + """
</div>
<button type="button" id="more">Voir plus de produits</button>
<script>
document.getElementById('more').addEventListener('click', () => {
  setTimeout(() => {
    document.querySelector('.search-results').insertAdjacentHTML('beforeend', """
    + repr(aldi_tile("1003", "farine-de-seigle", "Farine de seigle", "1,29"))
    + """);
    document.getElementById('more').remove();
  }, 200);
});
</script>
</body></html>"""
)

# A search page whose next page is a link (rel="next")
ALDI_PAGE_1_OF_2 = (
    """<!DOCTYPE html>
<html><head><title>Recherche | ALDI France</title></head><body>
<div class="search-results">"""
    + aldi_tile("1001", "farine-de-ble-t55", "Farine de blé T55", "0,79")
    + """</div>
<nav><a rel="next" href="/recherche.html?query=farine&amp;page=2">Page suivante</a></nav>
</body></html>"""
)
ALDI_PAGE_2_OF_2 = (
    """<!DOCTYPE html>
<html><head><title>Recherche | ALDI France</title></head><body>
<div class="search-results">"""
    + aldi_tile("1004", "farine-complete", "Farine complète", "1,09")
    + aldi_tile("1001", "farine-de-ble-t55", "Farine de blé T55", "0,79")
    + """</div></body></html>"""
)
