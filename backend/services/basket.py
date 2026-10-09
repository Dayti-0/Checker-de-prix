"""Basket comparison between retailers (area of P5).

The list itself lives in services/shopping_list.py; its functions are
re-exported here (``basket.add_item``...) as before the split.
"""

import asyncio

from backend.errors import AppError
from backend.models import BasketComparison, BasketLine, ListItem, StoreBasket, StoreResult
from backend.scrapers import SCRAPERS
from backend.services import hooks
from backend.services.search import search_store
from backend.services.settings import load_settings
from backend.services.shopping_list import MAX_ITEMS, add_item, get_list, update_item

__all__ = [
    "MAX_ITEMS",
    "AppError",
    "add_item",
    "choose_line",
    "compare_basket",
    "get_list",
    "update_item",
]


def choose_line(item: ListItem, store: str, result: StoreResult) -> BasketLine:
    """The product bought for ``item``: the user's pick, else the cheapest relevant one."""
    line = BasketLine(item_id=item.id, query=item.query, quantity=item.quantity)
    pick = item.picks.get(store)
    if pick is not None:
        fresh = next((p for p in result.products if p.product_url == pick.product_url and p.price is not None), None)
        line.product = fresh or (pick if pick.price is not None else None)
        line.picked = True
    else:
        candidates = [p for p in result.products if p.relevance >= 1 and p.price is not None and p.available]
        line.product = min(candidates, key=lambda p: p.price) if candidates else None
    if line.product is not None:
        line.line_total = round(line.product.price * item.quantity, 2)
    return line


async def compare_basket(stores: list[str] | None = None, refresh: bool = False) -> BasketComparison:
    items = await get_list()
    keys = [k for k in (stores or SCRAPERS) if k in SCRAPERS]
    settings = await load_settings()

    async def for_store(key: str) -> StoreBasket:
        basket = StoreBasket(store=key, label=SCRAPERS[key].label)
        for item in items:
            result = await search_store(key, item.query, refresh, settings=settings, priority="basket")
            line = choose_line(item, key, result)
            basket.lines.append(line)
            if line.line_total is None:
                basket.missing += 1
                if result.status not in ("ok", "empty") and basket.message is None:
                    basket.message = result.message
            else:
                basket.total = round(basket.total + line.line_total, 2)
        return basket

    baskets = list(await asyncio.gather(*(for_store(k) for k in keys)))
    comparison = BasketComparison(stores=baskets)

    complete = [b for b in baskets if b.lines and b.missing < len(b.lines)]
    if complete:
        comparison.best_store = min(complete, key=lambda b: (b.missing, b.total)).store

    if items:
        split_total = 0.0
        for index in range(len(items)):
            totals = [b.lines[index].line_total for b in baskets if b.lines[index].line_total is not None]
            if totals:
                split_total += min(totals)
            else:
                comparison.split_missing += 1
        comparison.split_total = round(split_total, 2)
    await hooks.emit("basket_compared", comparison=comparison)
    return comparison
