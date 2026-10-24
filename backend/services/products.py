"""Products of a search: unit prices, flags, duplicates, relevance and order (area of P2).

``prepare_products(products, query)`` is applied to every answer of a site,
cached or not (services/search.py):

1. prices per kg / L / piece normalised (``parsing.finalize_product``), barcode
   checked (``valid_ean``: a wrong one becomes None);
2. ``bio`` and ``store_brand`` computed (``is_bio``, ``is_store_brand``; a
   ``store_brand=True`` set by a scraper from the site itself is kept);
3. relevance (services/matching.py): ``relevance``, ``match_score`` and
   ``match_reason`` of each product;
4. duplicates dropped (``dedup_key``: the barcode, else the product page, the
   name, the contents and the price);
5. sorted: the products searched first (``relevance`` 1), by price, those
   without a price then the unavailable ones last; then the « Produits
   proches », closest first.
"""

from urllib.parse import urlsplit

from backend.models import Product
from backend.scrapers.leclerc import OWN_BRANDS as LECLERC_BRANDS
from backend.scrapers.parsing import finalize_product, valid_ean
from backend.services.matching import Matcher, tokenize

__all__ = ["STORE_BRANDS", "dedup_key", "is_bio", "is_store_brand", "prepare_products", "sort_key"]

# Own brands of each retailer (to complete): « Marque distributeur » filter.
# Compared without accents nor case; a brand starting with one of these names
# (« Carrefour Classic' », « U Bio ») is one of them.
STORE_BRANDS = {
    "carrefour": (
        "Carrefour",
        "Carrefour Classic'",
        "Carrefour Bio",
        "Carrefour Extra",
        "Carrefour Original",
        "Carrefour Sensation",
        "Carrefour Essential",
        "Simpl",
        "Reflets de France",
    ),
    "lidl": (
        "Milbona",
        "Belbake",
        "Solevita",
        "Cien",
        "W5",
        "Deluxe",
        "Pikok",
        "Freeway",
        "Chef Select",
        "Combino",
        "Crownfield",
        "Alesto",
        "Bellarom",
        "Fin Carré",
        "Italiamo",
        "Vitasia",
        "Snack Day",
        "Baresa",
        "Kania",
        "Lord Nelson",
        "Dulano",
        "Nixe",
        "Pilos",
    ),
    "aldi": ("Milsani", "Choceur", "Moser Roth"),
    "intermarche": (
        "Chabrior",
        "Pâturages",
        "Itinéraire des Saveurs",
        "Top Budget",
        "Saint Eloi",
        "Monique Ranou",
        "Paquito",
        "Capitaine Cook",
        "Fiorini",
        "Bouton d'Or",
        "Jean Rozé",
        "Ivoria",
        "Odyssée",
        "Planteur des Tropiques",
    ),
    "coursesu": ("U", "U Bio", "U Saveurs", "U Tout Petits", "Bien Vu"),
    # E.Leclerc (P8): kept with its scraper, which also reads the brand in the 2nd line of a product
    "leclerc": LECLERC_BRANDS,
}
_STORE_BRANDS = {store: tuple(" ".join(tokenize(b)) for b in brands) for store, brands in STORE_BRANDS.items()}

# Brands that only sell organic products
_BIO_BRANDS = ("bjorg", "bonneterre", "jardin bio", "bio village", "lima", "danival", "markal", "biocoop", "naturalia")
_BIO_WORDS = frozenset({"bio", "bios", "biologique", "biologiques"})


def _phrase_in(phrase: str, text: str) -> bool:
    return f" {phrase} " in f" {text} "


def is_bio(product: Product) -> bool:
    """Organic product: « bio » or « biologique » in its name or brand, or an organic brand."""
    words = tokenize(f"{product.name} {product.brand or ''}")
    if _BIO_WORDS & set(words):
        return True
    brand = " ".join(tokenize(product.brand or ""))
    return any(brand == b or brand.startswith(b + " ") for b in _BIO_BRANDS)


def is_store_brand(product: Product, store: str | None = None) -> bool | None:
    """Own brand of the retailer (True), national brand (False) or unknown brand (None).

    Without a brand, the name is searched for an own brand (« Farine de blé
    T45 U, 1kg » at Courses U, « ... CARREFOUR CLASSIC' » at Carrefour).
    """
    brands = _STORE_BRANDS.get(store or product.store, ())
    brand = " ".join(tokenize(product.brand or ""))
    if brand:
        return any(brand == b or brand.startswith(b + " ") for b in brands)
    name = " ".join(tokenize(product.name))
    return True if any(_phrase_in(b, name) for b in brands) else None


def _product_page(url: str) -> str:
    """``url`` when it is the page of a product, "" for a home page (``BASE_URL`` of a scraper)."""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return ""
    return url if parts.path.strip("/") or parts.query else ""


def dedup_key(product: Product) -> tuple:
    """Same key = same product: the barcode, else (product page, name, contents, price).

    « Eau minérale » in 50 cl and in 6x1,5 L are two products.
    """
    if product.ean:
        return ("ean", product.ean)
    return (
        "item",
        _product_page(product.product_url),
        " ".join(tokenize(product.name)),
        " ".join(tokenize(product.quantity_label or "")),
        product.price,
    )


def _better(kept: Product, other: Product) -> bool:
    """``other`` is a better copy of the same product than ``kept`` (a price, available)."""
    return (kept.price is None and other.price is not None) or (not kept.available and other.available)


def _complete(kept: Product, other: Product) -> None:
    for field in ("image_url", "sku", "brand", "quantity_label", "unit_price_label", "promo", "old_price"):
        if getattr(kept, field) is None and getattr(other, field) is not None:
            setattr(kept, field, getattr(other, field))


def sort_key(product: Product) -> tuple:
    """Products searched first, by price (no price, then unavailable, last); then the closest ones."""
    if product.relevance >= 1:
        return (0, not product.available, product.price is None, product.price or 0, product.name)
    return (1, not product.available, -product.match_score, product.price is None, product.price or 0, product.name)


def prepare_products(products: list[Product], query: str) -> list[Product]:
    """Normalise, flag, score, drop duplicates and sort the products of one retailer."""
    matcher = Matcher(query)
    unique: dict[tuple, Product] = {}
    for product in products:
        finalize_product(product)
        product.ean = valid_ean(product.ean)
        product.bio = is_bio(product)
        if product.store_brand is not True:  # a scraper may know it from the site (E.Leclerc)
            product.store_brand = is_store_brand(product)
        match = matcher.match(product.name, product.brand)
        product.relevance, product.match_score, product.match_reason = match.relevance, match.score, match.reason
        key = dedup_key(product)
        kept = unique.get(key)
        if kept is None:
            unique[key] = product
        elif _better(kept, product):
            _complete(product, kept)
            unique[key] = product
        else:
            _complete(kept, product)
    return sorted(unique.values(), key=sort_key)
