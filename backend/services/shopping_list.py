"""The shopping list: add, change, remove, paste, export, templates (area of P5).

One line per query (``repos.shopping_list.list_key`` = ``matching.query_key``):
adding « Farine » when « farine » is already there adds to its quantity (or
sets the product chosen at a retailer). Every change that writes several rows
is written in one transaction (``database.transaction()``): all or nothing, and
two simultaneous additions of the same query still give one line.

The price of a chosen product is never the one sent by the page: it is read
again in the search cache (same address or barcode), else the product is
marked « prix non vérifié » (``Pick.verified``).
"""

import csv
import io
import logging
import re
import time

from backend import config
from backend.database import transaction
from backend.errors import AppError
from backend.models import (
    BasketComparison,
    CheckUpdate,
    ListItem,
    ListItemCreate,
    ListItemUpdate,
    ManualPrice,
    ParsedLine,
    Pick,
    Product,
    Template,
    TemplateDetail,
    Trip,
    TripAisle,
    TripItem,
    TripStore,
    UsualItem,
)
from backend.repos import shopping_list as repo
from backend.repos import templates as templates_repo
from backend.scrapers.parsing import finalize_product
from backend.services import hooks
from backend.services.categories import CATEGORIES, OTHER, categorize, category_order, is_category

logger = logging.getLogger("prixmalin.list")

# Longest shopping list (each line may be searched at every retailer)
MAX_ITEMS = 300


def plural(n: int, singular: str, plural_form: str | None = None) -> str:
    """« 0 article », « 1 article », « 2 articles » (as fmt.plural of the page)."""
    return f"{n} {singular if abs(n) < 2 else plural_form or singular + 's'}"


def _to_item(raw: dict) -> ListItem:
    chosen = raw.get("category")
    data = {**raw, "category": chosen or categorize(raw["query"]), "category_set": bool(chosen)}
    picks = {}
    for store, pick in (data.get("picks") or {}).items():
        try:
            picks[store] = Pick(**pick)
        except (TypeError, ValueError):
            logger.warning("Invalid choice of %s ignored in « %s »", store, raw["query"])
    data["picks"] = picks
    return ListItem(**data)


async def get_list() -> list[ListItem]:
    return [_to_item(item) for item in await repo.list_items()]


async def get_item(item_id: int) -> ListItem | None:
    raw = await repo.get_item(item_id)
    return _to_item(raw) if raw else None


async def get_version() -> int:
    return await repo.get_version()


def categories() -> list[str]:
    """Aisles the user may choose, in the order of a walk in a supermarket."""
    return list(CATEGORIES)


def _clean(text: str | None) -> str | None:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text or None


def _check_category(category: str | None, query: str | None = None) -> str | None:
    """The aisle chosen by the user; None when it is the one guessed for ``query``
    (the guess follows the improvements of the dictionary)."""
    category = _clean(category)
    if category is not None and not is_category(category):
        raise AppError("Rayon inconnu.", 422, "validation")
    if category is not None and query is not None and category == categorize(query):
        return None
    return category


def _full() -> AppError:
    return AppError(f"Votre liste est pleine ({MAX_ITEMS} articles au maximum).", code="list_full")


# --- Prices of the chosen products (B63) ---------------------------------------


async def cached_products(store: str, query: str) -> tuple[list[Product], float | None]:
    """Products of the search cache for (retailer, chosen store, query) younger than
    7 days, and when they were read; ([], None) when there are none."""
    from backend.repos import cache
    from backend.scrapers import SCRAPERS
    from backend.services import search
    from backend.services.settings import load_settings

    try:
        settings = await load_settings()
        key = search.cache_key(SCRAPERS[store], settings.stores.get(store), query)
        entry = await cache.get_entry(key, config.CACHE_STALE_MAX_SECONDS)
    except Exception:  # noqa: BLE001 (the cache is optional here)
        logger.warning("Search cache unreadable for %s / %s", store, query, exc_info=True)
        return [], None
    if not entry:
        return [], None
    products = []
    for raw in entry.products:
        try:
            products.append(Product(**raw))
        except (TypeError, ValueError):
            continue
    return products, entry.created_at


def same_product(a: Product, b: Product) -> bool:
    """Same product of a retailer: same address, or same barcode."""
    if a.product_url and a.product_url == b.product_url:
        return True
    return bool(a.ean) and a.ean == b.ean


def pick_from(product: Product, cached: list[Product], read_at: float | None, now: float) -> Pick:
    """The product chosen by the user with the price read by PrixMalin (pure).

    The price comes from ``cached`` (search results read at ``read_at``) when
    the product is there (same address or barcode); otherwise the product is
    kept as sent, marked unverified.
    """
    for found in cached:
        if same_product(found, product):
            return Pick(**found.model_dump(), picked_at=now, price_at=read_at, source="site", verified=True)
    data = product.model_dump()
    data.update(picked_at=now, price_at=None, source="site", verified=False)
    return Pick(**data)


async def verified_pick(product: Product, query: str) -> Pick:
    """The product chosen by the user, with the price read by PrixMalin (never the client's)."""
    cached, read_at = await cached_products(product.store, query)
    return pick_from(product, cached, read_at, time.time())


def manual_pick(manual: ManualPrice, now: float) -> Pick:
    """A price seen in the store (« saisi le 03/10 »), with its price per kg/L when the contents say it."""
    seen = min(manual.seen_at or now, now)
    product = Product(
        store=manual.store,
        name=_clean(manual.name) or manual.name,
        price=round(manual.price, 2),
        quantity_label=_clean(manual.quantity_label),
    )
    finalize_product(product)
    return Pick(**product.model_dump(), picked_at=seen, price_at=seen, source="manual", verified=True)


def _dump(picks: dict) -> dict:
    return {store: product.model_dump() for store, product in picks.items()}


# --- Add, change, remove ---------------------------------------------------------


async def _add(db, query: str, data: ListItemCreate, category: str | None, pick: Pick | None) -> int:
    """Add ``query`` in the transaction ``db``, or update its line; returns the id of the line."""
    existing = await repo.get_by_key(repo.list_key(query))
    if existing is None:
        if await repo.count_items() >= MAX_ITEMS:
            raise _full()
        picks = {pick.store: pick} if pick else {}
        item_id = await repo.insert_item(
            query,
            data.quantity,
            _dump(picks),
            db=db,
            target=_clean(data.target),
            category=category,
            note=_clean(data.note),
        )
        await repo.record_added(query, db=db)
        return item_id
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
    await repo.update_fields(item.id, db=db, **fields)
    return item.id


async def add_item(data: ListItemCreate) -> ListItem:
    """Add a query to the list, or update the existing line for the same query."""
    query = _clean(data.query) or data.query.strip()
    category = _check_category(data.category, query)
    pick = await verified_pick(data.product, query) if data.product else None
    async with transaction() as db:
        item_id = await _add(db, query, data, category, pick)
    return await get_item(item_id)


async def bulk_add(items: list[ListItemCreate]) -> list[ListItem]:
    """Add several items at once (pasted list), merged with the existing lines; returns the list."""
    prepared = []
    for data in items:
        query = _clean(data.query) or data.query.strip()
        pick = await verified_pick(data.product, query) if data.product else None
        prepared.append((query, data, _check_category(data.category, query), pick))
    async with transaction() as db:
        current = {item["key"] for item in await repo.list_items()}
        new = {repo.list_key(query) for query, *_ in prepared} - current
        if len(current) + len(new) > MAX_ITEMS:
            raise AppError(f"Votre liste serait trop longue ({MAX_ITEMS} articles au maximum).", code="list_full")
        for query, data, category, pick in prepared:
            await _add(db, query, data, category, pick)
    return await get_list()


def _later(new: float | None, old: float | None) -> bool:
    """A tick dated ``new`` replaces one dated ``old`` (the most recent wins)."""
    return old is None or new is None or new >= old


async def update_item(item_id: int, data: ListItemUpdate) -> ListItem | None:
    now = time.time()
    current = await repo.get_item(item_id)
    if current is None:
        return None
    query = (_clean(data.query) or current["query"]) if data.query is not None else current["query"]
    pick = await verified_pick(data.set_pick, query) if data.set_pick is not None else None
    category = _check_category(data.category, query) if data.category is not None else None
    async with transaction() as db:
        raw = await repo.get_item(item_id)
        if raw is None:
            return None
        item = _to_item(raw)
        fields: dict = {}
        if data.query is not None and query != item.query:
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
            fields["category"] = category
        if data.compare is not None:
            fields["compare"] = data.compare
        picks, excluded = dict(item.picks), set(item.excluded)
        if data.remove_pick:
            picks.pop(data.remove_pick, None)
            excluded.discard(data.remove_pick)
        if pick is not None:
            picks[pick.store] = pick
            excluded.discard(pick.store)
        if data.manual_price is not None:
            manual = manual_pick(data.manual_price, now)
            picks[manual.store] = manual
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
            fields["checked_at"] = min(data.checked_at or now, now)
        await repo.update_fields(item.id, db=db, **fields)
    return await get_item(item_id)


async def apply_checks(checks: list[CheckUpdate]) -> list[ListItem]:
    """Ticks made in the store, possibly offline: the most recent tick of each item wins."""
    now = time.time()
    async with transaction() as db:
        for check in checks:
            raw = await repo.get_item(check.id)
            if raw is None or not _later(check.checked_at, raw.get("checked_at")):
                continue
            moment = min(check.checked_at or now, now)
            await repo.update_fields(check.id, db=db, checked=check.checked, checked_at=moment)
    return await get_list()


async def finish(mode: str) -> list[ListItem]:
    """End of the shopping: untick everything, or remove the ticked items."""
    if mode == "remove":
        await repo.delete_checked()
    else:
        await repo.uncheck_all()
    return await get_list()


# --- Delete, « Annuler » (B66) ------------------------------------------------------

# How long a deleted line can be put back (the page offers it for 6 s): the lines
# are kept by the server (table list_trash) and the page sends only their ids, so a
# line comes back exactly as it was saved (choices and their verified prices, ticks,
# date of addition), never as the page describes it.
TRASH_SECONDS = 15 * 60


async def delete_item(item_id: int) -> bool:
    """Delete a line (kept a while for « Annuler »)."""
    async with transaction() as db:
        raw = await repo.get_item(item_id)
        if raw is None:
            return False
        await repo.delete_item(item_id, db=db)
        await repo.trash_items([raw], time.time(), TRASH_SECONDS, db=db)
    return True


async def clear() -> None:
    """Empty the list (its lines are kept a while for « Annuler »)."""
    async with transaction() as db:
        rows = await repo.list_items()
        await repo.clear_items(db=db)
        await repo.trash_items(rows, time.time(), TRASH_SECONDS, db=db)


async def _restore_row(db, raw: dict) -> None:
    """Put back the deleted line ``raw`` in the transaction ``db``."""
    existing = await repo.get_by_key(repo.list_key(raw["query"]))
    if existing is not None:
        # Added again meanwhile: the line takes back its choices and settings
        await repo.update_fields(
            existing["id"],
            db=db,
            quantity=raw["quantity"],
            picks={**raw["picks"], **existing["picks"]},
            target=raw["target"],
            note=raw["note"],
            compare=raw["compare"],
            excluded=raw["excluded"],
            category=raw["category"],
        )
        return
    if await repo.count_items() >= MAX_ITEMS:
        raise _full()
    taken = await repo.get_item(raw["id"])
    await repo.insert_item(
        raw["query"],
        raw["quantity"],
        raw["picks"],
        db=db,
        item_id=None if taken else raw["id"],
        target=raw["target"],
        category=raw["category"],
        note=raw["note"],
        compare=raw["compare"],
        excluded=raw["excluded"],
        checked=raw["checked"],
        checked_at=raw["checked_at"],
        created_at=raw["created_at"],
    )


async def restore_items(ids: list[int]) -> list[ListItem]:
    """« Annuler » after a deletion: the lines ``ids`` come back as they were; returns the list.

    AppError 404 ``restore_expired`` when none of them can be put back any more.
    """
    wanted = list(dict.fromkeys(ids))
    async with transaction() as db:
        rows = await repo.trashed_items(wanted, time.time() - TRASH_SECONDS)
        if not rows:
            message = (
                "Cet article ne peut plus être rétabli."
                if len(wanted) < 2
                else "Ces articles ne peuvent plus être rétablis."
            )
            raise AppError(message, 404, "restore_expired")
        for raw in rows:
            await _restore_row(db, raw)
        await repo.untrash([raw["id"] for raw in rows], db=db)
    return await get_list()


async def usual_items() -> list[UsualItem]:
    return [UsualItem(**row) for row in await repo.usual_items()]


async def forget_usual(query: str) -> bool:
    return await repo.forget_usual(query)


# --- Pasted lists (B67) -------------------------------------------------------------

_BULLET = re.compile(r"^(?:[-–—•·*▪◦●○■□✓✔☐☑☒>+]+|\[\s*[xX✓✔]?\s*\]|\(\s*\)|\d{1,3}[.)](?=\s))\s*")
# Units of a size, longest names first (« kilogrammes » before « kilo » before « kg »)
_UNIT = r"(?:kilogrammes?|kilos?|kg|grammes?|gr|g|centilitres?|millilitres?|litres?|cl|ml|l)"
_UNIT_NAMES = (
    (r"kilogrammes?|kilos?|kg", "kg"),
    (r"grammes?|gr|g", "g"),
    (r"centilitres?|cl", "cl"),
    (r"millilitres?|ml", "ml"),
    (r"litres?|l", "L"),
)
_SIZE = rf"(?:\d+\s*[x×]\s*)?\d+(?:[.,]\d+)?\s*{_UNIT}(?:\s*[x×]\s*\d+)?"
_SIZE_ONLY = re.compile(rf"^\(?\s*({_SIZE})\s*\)?$", re.I)
_PREFIX_SIZE = re.compile(rf"^({_SIZE})(?![a-zà-ÿ])\s*(?:de\s+|d['’]\s*)?(.+)$", re.I)
_PREFIX_TIMES = re.compile(r"^(\d{1,2})\s*[x×*]\s*(.+)$", re.I)
_PREFIX_NUMBER = re.compile(r"^(\d{1,3})\s+(.+)$")
_SUFFIX_SIZE = re.compile(rf"^(.+?)\s*[,:(-]?\s*({_SIZE})\s*\)?$", re.I)
_SUFFIX_TIMES = re.compile(r"^(.+?)\s*[x×*]\s*(\d{1,3})$", re.I)
_SUFFIX_COUNT = re.compile(r"^(.+?)\s*(?:\((\d{1,2})\)|[:=]\s*(\d{1,2}))$")
# Products counted by the piece: « 12 œufs » is twelve eggs (a target), not twelve boxes
_COUNTABLE = re.compile(
    r"(?:oeufs?|œufs?|rouleaux?|yaourts?|yoghourts?|capsules?|dosettes?|couches?|lingettes?|"
    r"tranches?|pastilles?|lavages?|pi[eè]ces?)\b",
    re.I,
)
# Pieces of a product: « 10 rouleaux de papier toilette » is ten rolls (a target) of « papier toilette »
_PIECES = re.compile(r"^(?:rouleaux|rouleau|tranches?|pi[eè]ces?|unit[eé]s?)\s+(?:de\s+|d['’]\s*)?(.+)$", re.I)
_SUFFIX_PIECES = re.compile(r"^(.+?)\s+(\d{1,3})\s*(?:rouleaux|rouleau|tranches?|pi[eè]ces?|unit[eé]s?)$", re.I)
# Packaging: « 2 paquets de pâtes » and « chocolat 2 tablettes » are two packs
_PACKAGING = (
    r"(?:paquets?|bo[iî]tes?|packs?|sachets?|bouteilles?|briques?|pots?|barquettes?|tubes?|flacons?|"
    r"bocal|bocaux|conserves?|filets?|lots?|canettes?|bidons?|sacs?|tablettes?|plaquettes?|bottes?|"
    r"cartons?|berlingots?)"
)
_CONTAINER = re.compile(rf"^{_PACKAGING}\s+(?:de\s+|d['’]\s*)(.+)$", re.I)
_SUFFIX_CONTAINER = re.compile(rf"^(.+?)\s+(\d{{1,2}})\s*{_PACKAGING}$", re.I)
_FRACTIONS = ((re.compile(r"(?<![\d/])1/2(?![\d/])|½"), "0,5"), (re.compile(r"(?<![\d/])1/4(?![\d/])|¼"), "0,25"))
_SPLIT = re.compile(r";|,(?!\d)\s*|\s+\+\s+")


def _size_text(text: str) -> str:
    """« 1kg » → « 1 kg », « 6x1,5L » → « 6 x 1,5 L », « 500 grammes » → « 500 g »."""
    text = re.sub(r"\s+", " ", text.strip())
    text = re.sub(r"(\d)\s*([x×])\s*(\d)", r"\1 x \3", text)
    for names, unit in _UNIT_NAMES:
        text = re.sub(rf"(\d)\s*(?:{names})(?![a-zà-ÿ])", rf"\1 {unit}", text, flags=re.I)
    return text


def _countable(text: str) -> bool:
    return bool(_COUNTABLE.match(text.strip()))


def _clean_piece(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip(" \t.;,:")
    previous = None
    while text != previous:  # « - [ ] beurre »
        previous = text
        text = _BULLET.sub("", text).strip()
    for pattern, value in _FRACTIONS:
        text = pattern.sub(value, text)
    return text


def size_only(text: str) -> str | None:
    """« 500g » alone (after a comma: « pâtes, 500g »): the size, else None."""
    m = _SIZE_ONLY.match(_clean_piece(text))
    return _size_text(m.group(1)) if m else None


def _parse_piece(text: str) -> ParsedLine | None:
    text = _clean_piece(text)
    if not text:
        return None
    quantity, target = 1, None
    m = _PREFIX_SIZE.match(text)
    if m:
        target, text = _size_text(m.group(1)), m.group(2)
    elif m := _PREFIX_TIMES.match(text):
        quantity, text = int(m.group(1)), m.group(2)
    elif m := _PREFIX_NUMBER.match(text):
        rest = m.group(2)
        if container := _CONTAINER.match(rest):  # « 2 paquets de pâtes »: two packs
            quantity, text = int(m.group(1)), container.group(1)
        elif pieces := _PIECES.match(rest):  # « 10 rouleaux de papier toilette »: ten rolls
            target, text = m.group(1), pieces.group(1)
        elif _countable(rest):  # « 12 œufs »: twelve eggs
            target, text = m.group(1), rest
        else:  # « 2 lait »: two packs
            quantity, text = int(m.group(1)), rest
    if container := _CONTAINER.match(text):  # « paquet de pâtes »
        text = container.group(1)
        if target is None and (m := _PREFIX_NUMBER.match(text)):  # « pack de 6 bières »
            target, text = m.group(1), m.group(2)
    if target is None and (m := _SUFFIX_SIZE.match(text)):
        text, target = m.group(1), _size_text(m.group(2))
    if target is None and (m := _SUFFIX_PIECES.match(text)):  # « jambon 4 tranches »
        text, target = m.group(1), m.group(2)
    if m := _SUFFIX_CONTAINER.match(text):  # « chocolat noir 2 tablettes »
        text, quantity = m.group(1), int(m.group(2))
    if m := _SUFFIX_TIMES.match(text):
        text, count = m.group(1), int(m.group(2))
        if target is None and _countable(text):
            target = str(count)
        else:
            quantity = count
    if m := _SUFFIX_COUNT.match(text):
        text, count = m.group(1), int(m.group(2) or m.group(3))
        if target is None and _countable(text):  # « œufs (12) »
            target = str(count)
        else:
            quantity = count
    query = text.strip(" \t.;,:-–—")[:120].strip()
    if not query or not re.search(r"[^\W\d_]", query):
        return None
    return ParsedLine(query=query, quantity=max(1, min(99, quantity)), target=target, category=categorize(query))


def parse_list_text(text: str) -> list[ParsedLine]:
    """Items of a pasted list (pure): « 2 lait demi-écrémé », « farine 1kg », « - beurre »,
    « • œufs x12 », « 3x yaourts », « 2 paquets de pâtes »… (one item per line, or separated
    by « ; », « , » or « + »; a size alone after a comma belongs to the item before it).
    The same item twice is merged (quantities added)."""
    found: dict[str, ParsedLine] = {}
    for line in (text or "").splitlines():
        last: ParsedLine | None = None
        for piece in _SPLIT.split(line):
            size = size_only(piece)
            if size is not None:
                if last is not None and last.target is None:
                    last.target = size
                continue
            parsed = _parse_piece(piece)
            key = repo.list_key(parsed.query) if parsed else ""
            if not key:
                continue
            if key in found:
                found[key].quantity = min(99, found[key].quantity + parsed.quantity)
                found[key].target = found[key].target or parsed.target
                last = found[key]
            elif len(found) < MAX_ITEMS:
                found[key] = last = parsed
    return list(found.values())


async def preview_text(text: str) -> list[ParsedLine]:
    """``parse_list_text`` with the items already in the list marked ``existing``."""
    keys = {item["key"] for item in await repo.list_items()}
    lines = parse_list_text(text)
    for line in lines:
        line.existing = repo.list_key(line.query) in keys
    return lines


# --- Export (B69) -----------------------------------------------------------------


def _euros(value: float) -> str:
    return f"{value:.2f}".replace(".", ",") + " €"


def _cell(value: object) -> str:
    """A CSV cell that a spreadsheet never runs as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def assignment_of(
    comparison: BasketComparison | None, *, plan: int | None = None, store: str | None = None
) -> tuple[dict[int, dict], dict[str, str]]:
    """Where each item is bought in a basket comparison (pure).

    ``store``: everything at that retailer; ``plan``: plan number ``plan`` of
    the optimizer. Returns ({item id: {"store", "product", "price"}}, {retailer:
    name}) for format_list; nothing when the comparison does not say.
    """
    if comparison is None:
        return {}, {}
    baskets = {basket.store: basket for basket in comparison.stores}
    if store is not None:
        if store not in baskets:
            return {}, {}
        where = {line.item_id: store for line in baskets[store].lines}
        order = [store]
    elif plan is not None and 0 <= plan < len(comparison.plans):
        chosen = comparison.plans[plan]
        where = {item_id: part.store for part in chosen.stores for item_id in part.item_ids}
        order = [part.store for part in chosen.stores]
    else:
        return {}, {}
    assignment = {}
    for item_id, key in where.items():
        line = next((li for li in baskets[key].lines if li.item_id == item_id), None) if key in baskets else None
        entry = {"store": key, "product": None, "price": None}
        if line is not None and line.status == "found" and line.product is not None:
            entry["product"] = line.product.name
            entry["price"] = line.line_total
        assignment[item_id] = entry
    labels = {key: baskets[key].label for key in order if key in baskets}
    return assignment, labels


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
    """The list as text (to share) or CSV (for a spreadsheet), by retailer then by aisle (pure).

    ``assignment``: {item id: {"store", "product", "price"}} of a basket plan
    (``assignment_of``); ``labels``: {retailer key: name} of the retailers to group by.
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

    lines = [f"Ma liste de courses ({plural(len(items), 'article')})"]
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
                if item.target:
                    text += f" ({item.target})"
                elif item.quantity > 1:
                    text += f" x{item.quantity}"
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


# --- In the store (B64) -------------------------------------------------------------

OTHER_ITEMS = "Autres articles"
WHOLE_LIST = "Ma liste"


def trip_of(
    items: list[ListItem],
    comparison: BasketComparison | None,
    *,
    plan: int | None = None,
    store: str | None = None,
) -> Trip:
    """The list for the mode « En magasin » (pure): by retailer (``store``, or the plan
    number ``plan`` of the basket ``comparison``), then by aisle, with the product and
    the price the basket retained. Items the plan does not place (missing, or left out
    of the comparison) are in a last group (``store`` None, « Autres articles »)."""
    trip = Trip(store=store, plan=plan, outdated=bool(comparison and comparison.outdated))
    assignment, labels = assignment_of(comparison, plan=plan, store=store)
    if (plan is not None or store is not None) and not labels:
        trip.unknown = True
    baskets = {b.store: b for b in comparison.stores} if comparison is not None else {}
    if comparison is not None and labels:
        trip.basket_at = comparison.created_at
    lines = {(b.store, li.item_id): li for b in baskets.values() for li in b.lines}
    for key, aisles in group_items(items, assignment, labels):
        basket = baskets.get(key) if key else None
        group = TripStore(
            store=key,
            label=labels[key] if key else (OTHER_ITEMS if labels else WHOLE_LIST),
            store_label=basket.store_label if basket else None,
        )
        for aisle, aisle_items in aisles:
            entries = []
            for item in aisle_items:
                entry = TripItem(item=item, store=key)
                line = lines.get((key, item.id)) if key else None
                if line is not None:
                    entry.status = line.status
                    if line.status == "found":
                        entry.product, entry.packs, entry.line_total = line.product, line.packs, line.line_total
                        entry.picked, entry.manual, entry.stale = line.picked, line.manual, line.stale
                        entry.fetched_at = line.fetched_at
                entries.append(entry)
                group.item_count += 1
                group.checked_count += item.checked
                if entry.line_total is not None:
                    group.total = round(group.total + entry.line_total, 2)
                    if item.checked:
                        group.checked_total = round(group.checked_total + entry.line_total, 2)
            group.aisles.append(TripAisle(name=aisle, items=entries))
        trip.stores.append(group)
        trip.item_count += group.item_count
        trip.checked_count += group.checked_count
        trip.total = round(trip.total + group.total, 2)
        trip.checked_total = round(trip.checked_total + group.checked_total, 2)
    return trip


# --- Templates (B68) ----------------------------------------------------------------


def _template_item(item: ListItem) -> dict:
    data = item.model_dump(exclude={"id", "key", "checked", "checked_at", "created_at"})
    if not item.category_set:
        data["category"] = None
    return data


async def list_templates() -> list[Template]:
    return [Template(**row) for row in await templates_repo.list_templates()]


async def get_template(template_id: int) -> TemplateDetail | None:
    saved = await templates_repo.get_template(template_id)
    if saved is None:
        return None
    queries = [str(i.get("query", "")) for i in saved.pop("items")]
    return TemplateDetail(**saved, queries=queries)


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


def _saved_items(raw_items: list[dict], name: str) -> list[ListItem]:
    saved = []
    for raw in raw_items:
        try:
            item = ListItem(**{**raw, "id": 0, "category": raw.get("category") or ""})
        except (TypeError, ValueError):
            logger.warning("Invalid item in the template %s", name)
            continue
        item.category_set = bool(raw.get("category"))
        saved.append(item)
    return saved


async def apply_template(template_id: int, mode: str = "replace") -> list[ListItem] | None:
    """Put a saved list back (``replace``) or add its items to the list (``merge``)."""
    template = await templates_repo.get_template(template_id)
    if template is None:
        return None
    saved = _saved_items(template["items"], template["name"])
    async with transaction() as db:
        current = await repo.list_items() if mode == "merge" else []
        new = {repo.list_key(i.query) for i in saved} - {i["key"] for i in current}
        if len(current) + len(new) > MAX_ITEMS:
            raise AppError(f"Votre liste serait trop longue ({MAX_ITEMS} articles au maximum).", code="list_full")
        if mode == "replace":
            await repo.clear_items(db=db)
        for item in saved:
            existing = await repo.get_by_key(repo.list_key(item.query))
            if existing is None:
                await repo.insert_item(
                    item.query,
                    item.quantity,
                    _dump(item.picks),
                    db=db,
                    target=item.target,
                    category=item.category if item.category_set else None,
                    note=item.note,
                    compare=item.compare,
                    excluded=item.excluded,
                )
                await repo.record_added(item.query, db=db)
            else:
                current_item = _to_item(existing)
                await repo.update_fields(
                    current_item.id,
                    db=db,
                    quantity=min(99, current_item.quantity + item.quantity),
                    picks=_dump({**item.picks, **current_item.picks}),
                    target=current_item.target or item.target,
                )
    return await get_list()


# --- Backup providers ------------------------------------------------------------


async def export_backup() -> list[dict]:
    return [item.model_dump() for item in await get_list()]


async def restore_backup(data: list[dict]) -> None:
    """Replace the list with the lines of a backup (their ids are not kept), all at once."""
    items = []
    for raw in data or []:
        item = ListItem(**{**raw, "category": raw.get("category") or ""})
        item.category_set = bool(raw.get("category_set", raw.get("category")))
        items.append(item)
    async with transaction() as db:
        await repo.clear_items(db=db)
        seen = set()
        for item in items:
            key = repo.list_key(item.query)
            if key in seen or not key:
                continue
            seen.add(key)
            await repo.insert_item(
                item.query,
                item.quantity,
                _dump(item.picks),
                db=db,
                target=item.target,
                category=item.category if item.category_set and is_category(item.category) else None,
                note=item.note,
                compare=item.compare,
                excluded=item.excluded,
                checked=item.checked,
                checked_at=item.checked_at,
                created_at=item.created_at,
            )


async def export_templates() -> list[dict]:
    return [{"name": t["name"], "items": t["items"]} for t in await templates_repo.all_templates()]


async def restore_templates(data: list[dict]) -> None:
    async with transaction() as db:
        await templates_repo.clear_templates(db=db)
        for template in data or []:
            await templates_repo.save_template(str(template["name"]), list(template.get("items", [])), db=db)


async def export_history() -> list[dict]:
    return await repo.history_rows()


async def restore_history(data: list[dict]) -> None:
    await repo.replace_history(list(data or []))


hooks.register_backup("shopping_list", export_backup, restore_backup)
hooks.register_backup("list_templates", export_templates, restore_templates)
hooks.register_backup("list_history", export_history, restore_history)
