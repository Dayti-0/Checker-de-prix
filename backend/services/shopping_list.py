"""The shopping list: add, change, remove, paste, export, templates (area of P5).

One line per query (``repos.shopping_list.list_key``): adding « Farine » when
« farine » is already there adds to its quantity. Writes go through one lock,
so two simultaneous additions of the same query still give one line.
"""

import asyncio
import csv
import io
import logging
import re
import time

from backend.errors import AppError
from backend.models import (
    CheckUpdate,
    ListItem,
    ListItemCreate,
    ListItemUpdate,
    ParsedLine,
    Pick,
    Product,
    Template,
    UsualItem,
)
from backend.repos import shopping_list as repo
from backend.repos import templates as templates_repo
from backend.services import hooks
from backend.services.categories import OTHER, categorize, category_order, is_category

logger = logging.getLogger("prixmalin.list")

# Longest shopping list (each line may be searched at every retailer)
MAX_ITEMS = 300

_lock: tuple[asyncio.AbstractEventLoop, asyncio.Lock] | None = None


def _get_lock() -> asyncio.Lock:
    global _lock
    loop = asyncio.get_running_loop()
    if _lock is None or _lock[0] is not loop:
        _lock = (loop, asyncio.Lock())
    return _lock[1]


def _to_item(raw: dict) -> ListItem:
    chosen = raw.get("category")
    data = {**raw, "category": chosen or categorize(raw["query"]), "category_set": bool(chosen)}
    return ListItem(**data)


async def get_list() -> list[ListItem]:
    return [_to_item(item) for item in await repo.list_items()]


async def get_item(item_id: int) -> ListItem | None:
    raw = await repo.get_item(item_id)
    return _to_item(raw) if raw else None


async def get_version() -> int:
    return await repo.get_version()


def _clean(text: str | None) -> str | None:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text or None


def _check_category(category: str | None) -> str | None:
    category = _clean(category)
    if category is not None and not is_category(category):
        raise AppError("Rayon inconnu.", 422, "validation")
    return category


# --- Prices of the chosen products (B63) ---------------------------------------


async def cached_products(store: str, query: str) -> list[Product]:
    """Products of the search cache for (retailer, chosen store, query), or []."""
    from backend.repos import cache
    from backend.scrapers import SCRAPERS
    from backend.services import search
    from backend.services.settings import load_settings

    try:
        settings = await load_settings()
        key = search.cache_key(SCRAPERS[store], settings.stores.get(store), query)
        entry = await cache.get_cached_entry(key)
    except Exception:  # noqa: BLE001 (the cache is optional here)
        logger.warning("Search cache unreadable for %s / %s", store, query, exc_info=True)
        return []
    if not entry:
        return []
    products = []
    for raw in entry[0]:
        try:
            products.append(Product(**raw))
        except ValueError:
            continue
    return products


def same_product(a: Product, b: Product) -> bool:
    """Same product of a retailer: same address, or same barcode."""
    if a.product_url and a.product_url == b.product_url:
        return True
    return bool(a.ean) and a.ean == b.ean


async def verified_pick(product: Product, query: str) -> Pick:
    """The product chosen by the user, with the price read by PrixMalin (never the client's).

    The price comes from the search results in the cache (same address or
    barcode); otherwise the product is kept as sent, marked « prix non vérifié ».
    """
    now = time.time()
    for cached in await cached_products(product.store, query):
        if same_product(cached, product):
            return Pick(**cached.model_dump(), picked_at=now, source="site", verified=True)
    data = product.model_dump()
    data.update(picked_at=now, source="site", verified=False)
    return Pick(**data)


def _dump(picks: dict) -> dict:
    return {store: product.model_dump() for store, product in picks.items()}


# --- Add, change, remove ---------------------------------------------------------


async def add_item(data: ListItemCreate) -> ListItem:
    """Add a query to the list, or update the existing line for the same query."""
    query = _clean(data.query) or data.query.strip()
    category = _check_category(data.category)
    pick = await verified_pick(data.product, query) if data.product else None
    async with _get_lock():
        return await _add_locked(query, data, category, pick)


async def _add_locked(query: str, data: ListItemCreate, category: str | None, pick: Pick | None) -> ListItem:
    existing = await repo.get_by_key(repo.list_key(query))
    if existing is None:
        if await repo.count_items() >= MAX_ITEMS:
            raise AppError(f"Votre liste est pleine ({MAX_ITEMS} articles au maximum).", code="list_full")
        picks = {pick.store: pick} if pick else {}
        item_id = await repo.insert_item(
            query,
            data.quantity,
            _dump(picks),
            target=_clean(data.target),
            category=category,
            note=_clean(data.note),
        )
        await repo.record_added(query)
        return await get_item(item_id)
    item = _to_item(existing)
    fields: dict = {}
    if pick:
        item.picks[pick.store] = pick
        fields["picks"] = _dump(item.picks)
        if pick.store in item.excluded:
            fields["excluded"] = [s for s in item.excluded if s != pick.store]
    else:
        fields["quantity"] = min(99, item.quantity + data.quantity)
    if _clean(data.target):
        fields["target"] = _clean(data.target)
    if _clean(data.note):
        fields["note"] = _clean(data.note)
    if category:
        fields["category"] = category
    await repo.update_fields(item.id, **fields)
    return await get_item(item.id)


async def bulk_add(items: list[ListItemCreate]) -> list[ListItem]:
    """Add several items (pasted list); returns the whole list."""
    current = await repo.list_items()
    new = {repo.list_key(i.query) for i in items} - {repo.list_key(i["query"]) for i in current}
    if len(current) + len(new) > MAX_ITEMS:
        raise AppError(f"Votre liste serait trop longue ({MAX_ITEMS} articles au maximum).", code="list_full")
    for item in items:
        await add_item(item)
    return await get_list()


def _later(new: float | None, old: float | None) -> bool:
    """A tick dated ``new`` replaces one dated ``old`` (the most recent wins)."""
    return old is None or new is None or new >= old


async def update_item(item_id: int, data: ListItemUpdate) -> ListItem | None:
    async with _get_lock():
        raw = await repo.get_item(item_id)
        if raw is None:
            return None
        item = _to_item(raw)
        fields: dict = {}
        if data.query is not None:
            query = _clean(data.query) or item.query
            other = await repo.get_by_key(repo.list_key(query))
            if other is not None and other["id"] != item.id:
                raise AppError("Cet article est déjà dans votre liste.", 409, "duplicate")
            fields["query"] = query
        if data.quantity is not None:
            fields["quantity"] = data.quantity
        if data.target is not None:
            fields["target"] = _clean(data.target)
        if data.note is not None:
            fields["note"] = _clean(data.note)
        if data.category is not None:
            fields["category"] = _check_category(data.category)
        if data.compare is not None:
            fields["compare"] = data.compare
        picks, excluded = dict(item.picks), set(item.excluded)
        if data.remove_pick:
            picks.pop(data.remove_pick, None)
            excluded.discard(data.remove_pick)
        if data.set_pick is not None:
            pick = await verified_pick(data.set_pick, fields.get("query", item.query))
            picks[pick.store] = pick
            excluded.discard(pick.store)
        if data.manual_price is not None:
            manual = data.manual_price
            picks[manual.store] = Pick(
                store=manual.store,
                name=_clean(manual.name) or manual.name,
                price=round(manual.price, 2),
                quantity_label=_clean(manual.quantity_label),
                picked_at=manual.seen_at or time.time(),
                source="manual",
                verified=True,
            )
            excluded.discard(manual.store)
        if data.exclude_store:
            excluded.add(data.exclude_store)
            picks.pop(data.exclude_store, None)
        if picks != item.picks:
            fields["picks"] = _dump(picks)
        if excluded != set(item.excluded):
            fields["excluded"] = sorted(excluded)
        if data.checked is not None and _later(data.checked_at, item.checked_at):
            fields["checked"] = data.checked
            fields["checked_at"] = data.checked_at or time.time()
        await repo.update_fields(item.id, **fields)
        return await get_item(item.id)


async def apply_checks(checks: list[CheckUpdate]) -> list[ListItem]:
    """Ticks made in the store, possibly offline: the most recent tick of each item wins."""
    async with _get_lock():
        for check in checks:
            raw = await repo.get_item(check.id)
            if raw is None or not _later(check.checked_at, raw.get("checked_at")):
                continue
            await repo.update_fields(check.id, checked=check.checked, checked_at=check.checked_at or time.time())
    return await get_list()


async def finish(mode: str) -> list[ListItem]:
    """End of the shopping: untick everything, or remove the ticked items."""
    async with _get_lock():
        if mode == "remove":
            await repo.delete_checked()
        else:
            await repo.uncheck_all()
    return await get_list()


async def delete_item(item_id: int) -> None:
    async with _get_lock():
        await repo.delete_item(item_id)


async def restore_item(item: ListItem) -> ListItem:
    """Put back a deleted line as it was (same id, choices, target, ticks…)."""
    category = _check_category(item.category) if item.category_set else None
    async with _get_lock():
        existing = await repo.get_by_key(repo.list_key(item.query))
        if existing is not None:
            # Added again meanwhile: the line takes back its choices and settings
            current = _to_item(existing)
            await repo.update_fields(
                current.id,
                quantity=item.quantity,
                picks=_dump({**current.picks, **item.picks}),
                target=item.target,
                note=item.note,
                compare=item.compare,
                excluded=item.excluded,
                category=category,
            )
            return await get_item(current.id)
        if await repo.count_items() >= MAX_ITEMS:
            raise AppError(f"Votre liste est pleine ({MAX_ITEMS} articles au maximum).", code="list_full")
        taken = await repo.get_item(item.id)
        item_id = await repo.insert_item(
            item.query,
            item.quantity,
            _dump(item.picks),
            item_id=None if taken else item.id,
            target=item.target,
            category=category,
            note=item.note,
            compare=item.compare,
            excluded=item.excluded,
            checked=item.checked,
            checked_at=item.checked_at,
        )
        return await get_item(item_id)


async def clear() -> None:
    async with _get_lock():
        await repo.clear_items()


async def usual_items() -> list[UsualItem]:
    return [UsualItem(**row) for row in await repo.usual_items()]


# --- Pasted lists (B67) -------------------------------------------------------------

_BULLET = re.compile(r"^(?:[-–—•·*▪◦●○■□✓✔☐☑☒>+]+|\[\s*[xX✓✔]?\s*\]|\(\s*\)|\d{1,3}[.)](?=\s))\s*")
_UNIT = r"(?:kg|kilos?|grammes?|gr|g|litres?|l|cl|ml)"
_SIZE = rf"(?:\d+\s*[x×]\s*)?\d+(?:[.,]\d+)?\s*{_UNIT}(?:\s*[x×]\s*\d+)?"
_PREFIX_SIZE = re.compile(rf"^({_SIZE})(?![a-zà-ÿ])\s*(?:de\s+|d['’]\s*)?(.+)$", re.I)
_PREFIX_TIMES = re.compile(r"^(\d{1,2})\s*[x×*]\s*(.+)$", re.I)
_PREFIX_NUMBER = re.compile(r"^(\d{1,3})\s+(.+)$")
_SUFFIX_SIZE = re.compile(rf"^(.+?)\s*[,:(-]?\s*({_SIZE})\s*\)?$", re.I)
_SUFFIX_TIMES = re.compile(r"^(.+?)\s*[x×*]\s*(\d{1,3})$", re.I)
_SUFFIX_COUNT = re.compile(r"^(.+?)\s*(?:\((\d{1,2})\)|[:=]\s*(\d{1,2}))$")
_COUNTABLE = re.compile(
    r"(?:oeufs?|œufs?|rouleaux?|yaourts?|yoghourts?|capsules?|dosettes?|sachets?|couches?|lingettes?|"
    r"tranches?|pots?|briques?|canettes?|bouteilles?|pastilles?|lavages?|pi[eè]ces?)\b",
    re.I,
)
_SPLIT = re.compile(r";|,(?!\d)\s*|\s+\+\s+")


def _size_text(text: str) -> str:
    """« 1kg » → « 1 kg », « 6x1,5L » → « 6 x 1,5 L »."""
    text = re.sub(r"\s+", " ", text.strip())
    text = re.sub(r"(\d)\s*([x×])\s*(\d)", r"\1 x \3", text)
    text = re.sub(rf"(\d)\s*({_UNIT})\b", r"\1 \2", text, flags=re.I)
    return re.sub(r"\b(l|litres?)\b", "L", text, flags=re.I)


def _countable(text: str) -> bool:
    return bool(_COUNTABLE.match(text.strip()))


def _parse_piece(text: str) -> ParsedLine | None:
    text = re.sub(r"\s+", " ", text).strip(" \t.;,:")
    previous = None
    while text != previous:  # « - [ ] beurre »
        previous = text
        text = _BULLET.sub("", text).strip()
    if not text:
        return None
    quantity, target = 1, None
    m = _PREFIX_SIZE.match(text)
    if m:
        target, text = _size_text(m.group(1)), m.group(2)
    elif m := _PREFIX_TIMES.match(text):
        quantity, text = int(m.group(1)), m.group(2)
    elif m := _PREFIX_NUMBER.match(text):
        # « 12 œufs »: twelve eggs; « 2 lait »: two packs
        if _countable(m.group(2)):
            target, text = m.group(1), m.group(2)
        else:
            quantity, text = int(m.group(1)), m.group(2)
    if target is None and (m := _SUFFIX_SIZE.match(text)):
        text, target = m.group(1), _size_text(m.group(2))
    if m := _SUFFIX_TIMES.match(text):
        text, count = m.group(1), int(m.group(2))
        if target is None and _countable(text):
            target = str(count)
        else:
            quantity = count
    if m := _SUFFIX_COUNT.match(text):
        text, quantity = m.group(1), int(m.group(2) or m.group(3))
    query = text.strip(" \t.;,:-–—")[:120].strip()
    if not query or not re.search(r"[^\W\d_]", query):
        return None
    return ParsedLine(query=query, quantity=max(1, min(99, quantity)), target=target)


def parse_list_text(text: str) -> list[ParsedLine]:
    """Items of a pasted list: « 2 lait demi-écrémé », « farine 1kg », « - beurre »,
    « • œufs x12 », « 3x yaourts »… (one item per line, or separated by « ; » or « , »).
    The same item twice is merged (quantities added)."""
    found: dict[str, ParsedLine] = {}
    for line in (text or "").splitlines():
        for piece in _SPLIT.split(line):
            parsed = _parse_piece(piece)
            key = repo.list_key(parsed.query) if parsed else ""
            if not key:
                continue
            if key in found:
                found[key].quantity = min(99, found[key].quantity + parsed.quantity)
                found[key].target = found[key].target or parsed.target
            elif len(found) < MAX_ITEMS:
                found[key] = parsed
    return list(found.values())


# --- Export (B69) -----------------------------------------------------------------


def _euros(value: float) -> str:
    return f"{value:.2f}".replace(".", ",") + " €"


def _cell(value: object) -> str:
    """A CSV cell that a spreadsheet never runs as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def group_items(items: list[ListItem], assignment: dict[int, dict], labels: dict[str, str]) -> list[tuple]:
    """[(store or None, [(aisle, [items])])]: retailers in the order of ``labels``, then aisles."""
    by_store: dict[str | None, list[ListItem]] = {}
    for item in items:
        store = assignment.get(item.id, {}).get("store")
        by_store.setdefault(store if store in labels else None, []).append(item)
    order = [s for s in labels if s in by_store] + ([None] if None in by_store else [])
    groups = []
    for store in order:
        aisles: dict[str, list[ListItem]] = {}
        for item in by_store[store]:
            aisles.setdefault(item.category or OTHER, []).append(item)
        groups.append((store, sorted(aisles.items(), key=lambda kv: (category_order(kv[0]), kv[0]))))
    return groups


def format_list(
    items: list[ListItem],
    fmt: str = "txt",
    assignment: dict[int, dict] | None = None,
    labels: dict[str, str] | None = None,
) -> str:
    """The list as text (to share) or CSV (for a spreadsheet), by retailer then by aisle.

    ``assignment``: {item id: {"store", "product", "price"}} of a basket plan;
    ``labels``: {retailer key: name} of the retailers to group by.
    """
    assignment = assignment or {}
    labels = labels or {}
    groups = group_items(items, assignment, labels)
    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
        writer.writerow(["Enseigne", "Rayon", "Article", "Quantité", "Objectif", "Produit", "Prix", "Note", "Coché"])
        for store, aisles in groups:
            for aisle, aisle_items in aisles:
                for item in aisle_items:
                    chosen = assignment.get(item.id, {}) if store else {}
                    price = chosen.get("price")
                    writer.writerow(
                        [
                            _cell(labels.get(store, "")),
                            _cell(aisle),
                            _cell(item.query),
                            item.quantity,
                            _cell(item.target or ""),
                            _cell(chosen.get("product") or ""),
                            f"{price:.2f}".replace(".", ",") if price is not None else "",
                            _cell(item.note or ""),
                            "oui" if item.checked else "non",
                        ]
                    )
        return out.getvalue()

    count = len(items)
    lines = [f"Ma liste de courses ({count} article{'s' if count > 1 else ''})"]
    for store, aisles in groups:
        lines.append("")
        if store:
            lines.append(labels[store].upper())
        elif len(groups) > 1:
            lines.append("AUTRES ARTICLES")
        total = 0.0
        for aisle, aisle_items in aisles:
            lines.append(f"{aisle} :")
            for item in aisle_items:
                text = item.query
                if item.quantity > 1:
                    text += f" x{item.quantity}"
                if item.target:
                    text += f" ({item.target})"
                chosen = assignment.get(item.id, {}) if store else {}
                if chosen.get("product"):
                    text += f" : {chosen['product']}"
                    if chosen.get("price") is not None:
                        text += f", {_euros(chosen['price'])}"
                        total += chosen["price"]
                if item.note:
                    text += f" ({item.note})"
                lines.append(f"{'[x]' if item.checked else '-'} {text}")
        if store and total:
            lines.append(f"Total {labels[store]} : {_euros(total)}")
    return "\n".join(lines) + "\n"


# --- Templates (B68) ----------------------------------------------------------------


def _template_item(item: ListItem) -> dict:
    return item.model_dump(exclude={"id", "checked", "checked_at"})


async def list_templates() -> list[Template]:
    return [Template(**row) for row in await templates_repo.list_templates()]


async def save_template(name: str) -> Template:
    name = _clean(name) or ""
    if not name:
        raise AppError("Donnez un nom à cette liste.", 422, "validation")
    items = await get_list()
    if not items:
        raise AppError("Votre liste est vide : il n'y a rien à enregistrer.", code="list_empty")
    template_id = await templates_repo.save_template(name, [_template_item(i) for i in items])
    saved = await templates_repo.get_template(template_id)
    return Template(**{k: v for k, v in saved.items() if k != "items"})


async def delete_template(template_id: int) -> bool:
    return await templates_repo.delete_template(template_id)


async def apply_template(template_id: int, mode: str = "replace") -> list[ListItem] | None:
    """Put a saved list back (``replace``) or add its items to the list (``merge``)."""
    template = await templates_repo.get_template(template_id)
    if template is None:
        return None
    saved = []
    for raw in template["items"]:
        try:
            saved.append(ListItem(**{**raw, "id": 0}))
        except ValueError:
            logger.warning("Invalid item in the template %s", template["name"])
    async with _get_lock():
        current = await repo.list_items() if mode == "merge" else []
        new = {repo.list_key(i.query) for i in saved} - {repo.list_key(i["query"]) for i in current}
        if len(current) + len(new) > MAX_ITEMS:
            raise AppError(f"Votre liste serait trop longue ({MAX_ITEMS} articles au maximum).", code="list_full")
        if mode == "replace":
            await repo.clear_items()
        for item in saved:
            existing = await repo.get_by_key(repo.list_key(item.query))
            if existing is None:
                await repo.insert_item(
                    item.query,
                    item.quantity,
                    _dump(item.picks),
                    target=item.target,
                    category=item.category if item.category_set else None,
                    note=item.note,
                    compare=item.compare,
                    excluded=item.excluded,
                )
                await repo.record_added(item.query)
            else:
                current_item = _to_item(existing)
                await repo.update_fields(
                    current_item.id,
                    quantity=min(99, current_item.quantity + item.quantity),
                    picks=_dump({**item.picks, **current_item.picks}),
                    target=current_item.target or item.target,
                )
    return await get_list()


# --- Backup providers ------------------------------------------------------------


async def export_backup() -> list[dict]:
    return [item.model_dump() for item in await get_list()]


async def restore_backup(data: list[dict]) -> None:
    """Replace the list with the lines of a backup (their ids are not kept)."""
    items = [ListItem(**item) for item in data]
    async with _get_lock():
        await repo.clear_items()
        for item in items:
            if await repo.get_by_key(repo.list_key(item.query)) is not None:
                continue
            await repo.insert_item(
                item.query,
                item.quantity,
                _dump(item.picks),
                target=item.target,
                category=item.category if item.category_set else None,
                note=item.note,
                compare=item.compare,
                excluded=item.excluded,
                checked=item.checked,
                checked_at=item.checked_at,
            )


async def export_templates() -> list[dict]:
    return [await templates_repo.get_template(row["id"]) for row in await templates_repo.list_templates()]


async def restore_templates(data: list[dict]) -> None:
    await templates_repo.clear_templates()
    for template in data or []:
        await templates_repo.save_template(template["name"], template.get("items", []))


hooks.register_backup("shopping_list", export_backup, restore_backup)
hooks.register_backup("list_templates", export_templates, restore_templates)
