"""Products of a search: unit prices, duplicates, relevance and order (area of P2)."""

from backend.models import Product
from backend.scrapers.parsing import finalize_product
from backend.services.matching import match_score


def prepare_products(products: list[Product], query: str) -> list[Product]:
    """Normalise unit prices, drop duplicates, score and sort by price."""
    unique: dict[tuple[str, str], Product] = {}
    for product in products:
        finalize_product(product)
        product.relevance = match_score(f"{product.name} {product.brand or ''}", query)
        unique.setdefault((product.product_url, product.name.lower()), product)
    return sorted(
        unique.values(),
        key=lambda p: (p.relevance < 1, -p.relevance, p.price is None, p.price or 0),
    )
