"""Shopping list and basket comparison between retailers."""

import asyncio

from backend import database
from backend.errors import AppError
from backend.models import (
    BasketComparison,
    BasketLine,
    ListItem,
    ListItemCreate,
    ListItemUpdate,
    StoreBasket,
    StoreResult,
)
from backend.scrapers import SCRAPERS
from backend.services.matching import query_key
from backend.services.search import search_store
from backend.services.settings import load_settings

# Longest shopping list (each line may be searched at every retailer)
MAX_ITEMS = 300


async def get_list() -> list[ListItem]:
    return [ListItem(**item) for item in await database.list_items()]


async def add_item(data: ListItemCreate) -> ListItem:
    """Add a query to the list, or update the existing line for the same query."""
    key = query_key(data.query)
    items = await get_list()
    existing = next((i for i in items if query_key(i.query) == key), None)
    if existing is None:
        if len(items) >= MAX_ITEMS:
            raise AppError(f"Votre liste est pleine ({MAX_ITEMS} articles au maximum).", code="list_full")
        picks = {data.product.store: data.product} if data.product else {}
        item_id = await database.insert_item(data.query.strip(), data.quantity, _dump(picks))
        return ListItem(id=item_id, query=data.query.strip(), quantity=data.quantity, picks=picks)
    if data.product:
        existing.picks[data.product.store] = data.product
    else:
        existing.quantity = min(99, existing.quantity + data.quantity)
    await database.update_item(existing.id, existing.quantity, _dump(existing.picks))
    return existing


async def update_item(item_id: int, data: ListItemUpdate) -> ListItem | None:
    raw = await database.get_item(item_id)
    if raw is None:
        return None
    item = ListItem(**raw)
    if data.quantity is not None:
        item.quantity = data.quantity
    if data.remove_pick:
        item.picks.pop(data.remove_pick, None)
    await database.update_item(item.id, item.quantity, _dump(item.picks))
    return item


def _dump(picks: dict) -> dict:
    return {store: product.model_dump() for store, product in picks.items()}


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
            result = await search_store(key, item.query, refresh, settings)
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
    return comparison
