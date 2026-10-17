"""The shopping list: add, change, remove lines (area of P5)."""

from backend.errors import AppError
from backend.models import ListItem, ListItemCreate, ListItemUpdate
from backend.repos import shopping_list as repo
from backend.services import hooks
from backend.services.matching import query_key

# Longest shopping list (each line may be searched at every retailer)
MAX_ITEMS = 300


async def get_list() -> list[ListItem]:
    return [ListItem(**item) for item in await repo.list_items()]


async def add_item(data: ListItemCreate) -> ListItem:
    """Add a query to the list, or update the existing line for the same query."""
    key = query_key(data.query)
    items = await get_list()
    existing = next((i for i in items if query_key(i.query) == key), None)
    if existing is None:
        if len(items) >= MAX_ITEMS:
            raise AppError(f"Votre liste est pleine ({MAX_ITEMS} articles au maximum).", code="list_full")
        picks = {data.product.store: data.product} if data.product else {}
        item_id = await repo.insert_item(data.query.strip(), data.quantity, _dump(picks))
        return ListItem(id=item_id, query=data.query.strip(), quantity=data.quantity, picks=picks)
    if data.product:
        existing.picks[data.product.store] = data.product
    else:
        existing.quantity = min(99, existing.quantity + data.quantity)
    await repo.update_item(existing.id, existing.quantity, _dump(existing.picks))
    return existing


async def update_item(item_id: int, data: ListItemUpdate) -> ListItem | None:
    raw = await repo.get_item(item_id)
    if raw is None:
        return None
    item = ListItem(**raw)
    if data.quantity is not None:
        item.quantity = data.quantity
    if data.remove_pick:
        item.picks.pop(data.remove_pick, None)
    await repo.update_item(item.id, item.quantity, _dump(item.picks))
    return item


async def delete_item(item_id: int) -> None:
    await repo.delete_item(item_id)


async def clear() -> None:
    await repo.clear_items()


def _dump(picks: dict) -> dict:
    return {store: product.model_dump() for store, product in picks.items()}


# --- Backup provider -----------------------------------------------------------


async def export_backup() -> list[dict]:
    return [item.model_dump() for item in await get_list()]


async def restore_backup(data: list[dict]) -> None:
    """Replace the list with the lines of a backup (their ids are not kept)."""
    items = [ListItem(**item) for item in data]
    await repo.clear_items()
    for item in items:
        await repo.insert_item(item.query, item.quantity, _dump(item.picks))


hooks.register_backup("shopping_list", export_backup, restore_backup)
