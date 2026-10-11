"""Basket comparison between retailers (area of P5).

**Lines** (``choose_line``, pure). For each item of the list (``compare`` true)
and each retailer, in this order:

1. « pas disponible ici » (``ListItem.excluded``): ``excluded``, no search;
2. a price typed by hand (``Pick.source == "manual"``) younger than the
   ``manual_weeks`` setting: counted (``basis="manual"``), no search; older: shown
   (``pick``, ``expired``), not counted;
3. the retailer could not be searched (``store_required``, ``blocked``,
   ``timeout``, ``error``): ``unchecked`` with its message, unless the product
   chosen by the user has a price younger than 7 days (counted, ``stale``);
4. the product chosen by the user (``basis="pick"``), found in the results by
   address or barcode; missing from the results: its last price, younger than 7
   days, ``stale`` (« Prix du 12/09, produit non retrouvé »); unavailable or too
   old: the automatic choice below, with ``pick_issue``;
5. the automatic choice, **only among the relevant products** (``relevance >= 1``
   and ``match_score >= matching.RELEVANT_SCORE``), available and with a price:
   the same barcode as a product chosen at another retailer (``basis="ean"``);
   with a target (« 6 L »), the cheapest ``packs × price`` with ``packs =
   ceil(target / contents)``; else the lowest price per kg/L among the products
   whose contents are within 0.5 to 2 times the reference (contents of a chosen
   product, else the median contents at the retailers), else the lowest price;
6. nothing relevant: ``not_found`` (never a close product instead).

**Totals** (``build_comparison``, pure): per retailer the total of the found
lines, ``found_count``/``item_count``, ``common_total`` (items found at every
ranked retailer), ``estimated_total`` (total plus, for each missing or excluded
item, the median of the other retailers), ``complete``. A retailer whose lines
are all unchecked is not ranked; the others are ranked when complete or with at
least half of the items: complete baskets first, then by estimated total.
« Panier le moins cher » (``best_store``) only for a complete basket.

**Searches** (``compare_basket``): items one after the other at a retailer,
retailers at the same time, cached results first, priority ``basket``. After a
failed search (or old prices served because the site failed), the other items
of that retailer are read in the cache only (never the site): old prices when
there are some, else ``unchecked``. ``on_event`` receives the progress (start,
line, store, done) for the live basket (``GET /api/basket/compare/stream``).

Emits ``basket_compared(comparison)`` after each comparison (P0 contract).
The list itself lives in services/shopping_list.py; its functions are
re-exported here (``basket.add_item``...) as before the split.
"""

import asyncio
import inspect
import logging
import math
import re
import statistics
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from backend import config
from backend.errors import AppError
from backend.models import (
    BasketComparison,
    BasketLine,
    BasketPrefs,
    BasketPrefsUpdate,
    Candidates,
    ListItem,
    Pick,
    Product,
    Settings,
    StoreBasket,
    StoreResult,
)
from backend.repos import cache
from backend.repos import shopping_list as list_repo
from backend.scrapers import SCRAPERS
from backend.scrapers.parsing import PIECE, parse_quantity
from backend.services import hooks, matching, optimizer, prefs, search
from backend.services.search import search_store
from backend.services.settings import load_settings
from backend.services.shopping_list import MAX_ITEMS, add_item, get_item, get_list, update_item

__all__ = [
    "MAX_ITEMS",
    "AppError",
    "add_item",
    "build_comparison",
    "candidates",
    "choose_auto",
    "choose_line",
    "compare_basket",
    "get_list",
    "update_item",
]

logger = logging.getLogger("prixmalin.basket")

PREFS_SECTION = "p5.basket"

# Searches that could not be done: the line is « unchecked »
FAILED = ("store_required", "blocked", "timeout", "error")
# Action offered by the card of a retailer that could not be searched
ACTIONS = {"store_required": "choose_store", "blocked": "unblock", "timeout": "retry", "error": "retry"}
# Window of contents around the reference (0.5 to 2 times)
WINDOW = (0.5, 2.0)
# A chosen product missing from the results is counted at its last price this long
PICK_MAX_AGE = config.CACHE_STALE_MAX_SECONDS
# More packs than this for a target: not a sensible product
MAX_PACKS = 99
# A retailer is ranked with at least this share of the items
MIN_COVERAGE = 0.5
UNITS = ("kg", "L", PIECE)


# ---------------------------------------------------------------------------
# Quantities (pure)
# ---------------------------------------------------------------------------


# Unit names typed by hand, as parse_quantity reads them (« 500 grammes » → « 500 g »)
_UNIT_WORDS = (
    (r"kilogrammes?|kilos?", "kg"),
    (r"grammes?|gr", "g"),
    (r"centilitres?", "cl"),
    (r"millilitres?", "ml"),
    (r"litres?", "L"),
)


def parse_target(text: str | None) -> tuple[float, str] | None:
    """Quantity wanted: « 1 kg » → (1.0, "kg"), « 6 L » → (6.0, "L"), « 12 » → (12.0, "pièce"),
    « 500 grammes » → (0.5, "kg"), « 1/2 litre » → (0.5, "L")."""
    if not text or not text.strip():
        return None
    text = re.sub(r"(?<![\d/])1/2(?![\d/])|½", "0,5", text)
    for words, unit in _UNIT_WORDS:
        text = re.sub(rf"(\d)\s*(?:{words})(?![a-zà-ÿ])", rf"\1 {unit}", text, flags=re.I)
    quantity = parse_quantity(text)
    if quantity and quantity[0] > 0:
        return quantity
    m = re.fullmatch(r"\s*(\d{1,4})\s*(?:pi[eè]ces?|unit[eé]s?|x)?\s*", text, re.I)
    if m and int(m.group(1)) > 0:
        return float(m.group(1)), PIECE
    return None


def contents_of(product: Product) -> tuple[float, str] | None:
    """Contents of a product (kg, L or pièces), from its label, its name or its price per unit."""
    for text in (product.quantity_label, product.name):
        quantity = parse_quantity(text)
        if quantity and quantity[0] > 0:
            return quantity
    if product.unit in UNITS and product.unit_price and product.price:
        return round(product.price / product.unit_price, 6), product.unit
    return None


def packs_for(target: tuple[float, str] | None, contents: tuple[float, str] | None) -> int | None:
    """Packs to buy for ``target``: ceil(target / contents), None when the units differ."""
    if target is None or contents is None or target[1] != contents[1] or contents[0] <= 0:
        return None
    packs = max(1, math.ceil(target[0] / contents[0] - 1e-9))
    return packs if packs <= MAX_PACKS else None


def unit_price_of(product: Product, contents: tuple[float, str] | None = None) -> float:
    contents = contents or contents_of(product)
    if contents and product.price:
        return product.price / contents[0]
    return math.inf


def is_suitable(product: Product) -> bool:
    """A product the basket may count: the one searched (never a close product), available, with a price."""
    return (
        product.relevance >= 1
        and product.match_score >= matching.RELEVANT_SCORE
        and product.price is not None
        and product.price > 0
        and product.available
    )


def suitable(products: Iterable[Product]) -> list[Product]:
    return [p for p in products if is_suitable(p)]


def dominant_unit(contents: Iterable[tuple[float, str]]) -> str | None:
    """The unit of most of the contents (kg before L before pièce at equal count)."""
    counts = Counter(unit for _, unit in contents)
    if not counts:
        return None
    return max(counts, key=lambda unit: (counts[unit], -UNITS.index(unit) if unit in UNITS else -len(UNITS)))


def reference_for(item: ListItem, product_lists: Iterable[Sequence[Product]]) -> tuple[float, str] | None:
    """Contents the automatic choice compares with: those of a product chosen by the user,
    else the median of the median contents of each retailer (dominant unit)."""
    for pick in item.picks.values():
        contents = contents_of(pick)
        if contents:
            return contents
    per_store = [[c for p in suitable(products) if (c := contents_of(p))] for products in product_lists]
    unit = dominant_unit(c for contents in per_store for c in contents)
    if unit is None:
        return None
    medians = [
        statistics.median(amount for amount, u in contents if u == unit)
        for contents in per_store
        if any(u == unit for _, u in contents)
    ]
    return round(statistics.median(medians), 6), unit


def choose_auto(
    products: Sequence[Product],
    quantity: int = 1,
    target: tuple[float, str] | None = None,
    reference: tuple[float, str] | None = None,
    ean: str | None = None,
) -> tuple[Product, int, str] | None:
    """The product the basket takes by itself: (product, packs, basis) or None (B58)."""
    candidates = suitable(products)
    if not candidates:
        return None
    basis = "auto"
    if ean:
        same = [p for p in candidates if p.ean == ean]
        if same:
            candidates, basis = same, "ean"
    if target is not None:
        options = [(p, packs) for p in candidates if (packs := packs_for(target, contents_of(p)))]
        if options:
            product, packs = min(
                options, key=lambda o: (round(o[0].price * o[1], 2), o[1], unit_price_of(o[0]), o[0].price)
            )
            return product, packs, basis
    if reference is not None:
        low, high = reference[0] * WINDOW[0] - 1e-9, reference[0] * WINDOW[1] + 1e-9
        in_window = []
        for p in candidates:
            contents = contents_of(p)
            if contents and contents[1] == reference[1] and low <= contents[0] <= high:
                in_window.append((p, contents))
        if in_window:
            product, _ = min(in_window, key=lambda o: (round(unit_price_of(o[0], o[1]), 4), o[0].price))
            return product, quantity, basis
    return min(candidates, key=lambda p: p.price), quantity, basis


def ean_hint(item: ListItem, store: str) -> str | None:
    """Barcode of a product chosen by the user at another retailer."""
    for key, pick in item.picks.items():
        if key != store and pick.source == "site" and pick.ean:
            return pick.ean
    return None


# ---------------------------------------------------------------------------
# One line (pure)
# ---------------------------------------------------------------------------


def _day(moment: float) -> str:
    return datetime.fromtimestamp(moment).strftime("%d/%m")


def _found(
    line: BasketLine, product: Product, packs: int, basis: str, fetched_at: float | None, *, stale: bool = False
) -> BasketLine:
    line.status = "found"
    line.product = Product(**product.model_dump(include=set(Product.model_fields)))
    line.packs = packs
    line.line_total = round(product.price * packs, 2)
    line.basis = basis
    line.picked = basis in ("pick", "manual")
    line.fetched_at = fetched_at
    line.stale = stale
    return line


def _pick_packs(item: ListItem, product: Product) -> int:
    return packs_for(parse_target(item.target), contents_of(product)) or item.quantity


def _recent(pick: Pick, now: float) -> bool:
    moment = pick.price_at or pick.picked_at
    return pick.price is not None and moment is not None and now - moment <= PICK_MAX_AGE


def needs_search(item: ListItem, store: str, now: float, manual_max_age: float) -> bool:
    """False when the line does not depend on the site: excluded, or a valid price typed by hand."""
    if store in item.excluded:
        return False
    pick = item.picks.get(store)
    return not (pick is not None and pick.source == "manual" and _manual_valid(pick, now, manual_max_age))


def _manual_valid(pick: Pick, now: float, manual_max_age: float) -> bool:
    return pick.price is not None and now - (pick.picked_at or now) <= manual_max_age


def choose_line(
    item: ListItem,
    store: str,
    result: StoreResult | None,
    *,
    reference: tuple[float, str] | None = None,
    now: float | None = None,
    manual_max_age: float = 6 * 7 * 86400,
) -> BasketLine:
    """What the basket counts for ``item`` at ``store`` (see the module docstring)."""
    now = time.time() if now is None else now
    line = BasketLine(item_id=item.id, query=item.query, quantity=item.quantity, target=item.target)
    pick = item.picks.get(store)
    line.pick = pick
    if store in item.excluded:
        line.status = "excluded"
        return line
    if pick is not None and pick.source == "manual":
        if _manual_valid(pick, now, manual_max_age):
            line.manual = True
            return _found(line, pick, _pick_packs(item, pick), "manual", pick.picked_at)
        line.expired, line.pick_issue = True, "expired"
        pick = None  # too old: the price of the site instead
    if result is None or result.status in FAILED:
        reason = result.status if result is not None else "error"
        if pick is not None and _recent(pick, now):
            moment = pick.price_at or pick.picked_at
            label = result.label if result is not None else store
            line.message = search.stale_message(label, moment, reason, result.retry_after if result else None)
            line.verified = pick.verified
            return _found(line, pick, _pick_packs(item, pick), "pick", moment, stale=True)
        line.status = "unchecked"
        line.message = result.message if result is not None else None
        return line

    products = result.products
    line.alternatives = len(suitable(products))
    old_prices = result.message if result.stale else None
    if pick is not None:
        fresh = next((p for p in products if p.price is not None and _same(p, pick)), None)
        if fresh is not None and fresh.available:
            line.message = old_prices
            return _found(line, fresh, _pick_packs(item, fresh), "pick", result.fetched_at, stale=result.stale)
        if fresh is not None:
            line.pick_issue = "unavailable"
        elif _recent(pick, now):
            moment = pick.price_at or pick.picked_at
            line.message = f"Prix du {_day(moment)}, produit non retrouvé"
            line.verified = pick.verified
            return _found(line, pick, _pick_packs(item, pick), "pick", moment, stale=True)
        else:
            line.pick_issue = "not_found" if pick.verified else "unverified"

    target = parse_target(item.target)
    chosen = choose_auto(products, item.quantity, target, reference, ean_hint(item, store))
    if chosen is None:
        line.status = "not_found"
        line.message = _pick_note(line.pick_issue)
        return line
    product, packs, basis = chosen
    line.message = old_prices or _pick_note(line.pick_issue)
    return _found(line, product, packs, basis, result.fetched_at, stale=result.stale)


def _same(a: Product, b: Product) -> bool:
    if a.product_url and a.product_url == b.product_url:
        return True
    return bool(a.ean) and a.ean == b.ean


def _pick_note(issue: str | None) -> str | None:
    return {
        "unavailable": "Le produit choisi est indisponible.",
        "not_found": "Le produit choisi n'a pas été retrouvé.",
        "unverified": "Le produit choisi n'a pas été retrouvé (prix non vérifié).",
        "expired": "Le prix saisi est trop ancien.",
    }.get(issue or "")


# ---------------------------------------------------------------------------
# The comparison (pure)
# ---------------------------------------------------------------------------


@dataclass
class StoreInfo:
    """A retailer compared: key, name, store chosen, and its failed search (if any)."""

    key: str
    label: str
    store_label: str | None = None
    failure: StoreResult | None = None


def _usable(result: StoreResult | None) -> bool:
    return result is not None and result.status not in FAILED


def references(
    items: Sequence[ListItem], stores: Sequence[str], results: dict[tuple[str, int], StoreResult | None]
) -> dict[int, tuple[float, str] | None]:
    """Reference contents of each item, from the results of every retailer."""
    refs = {}
    for item in items:
        lists = [results[(key, item.id)].products for key in stores if _usable(results.get((key, item.id)))]
        refs[item.id] = reference_for(item, lists)
    return refs


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def build_comparison(
    items: Sequence[ListItem],
    stores: Sequence[StoreInfo],
    results: dict[tuple[str, int], StoreResult | None],
    *,
    now: float | None = None,
    manual_max_age: float = 6 * 7 * 86400,
    min_saving: float = 3.0,
) -> BasketComparison:
    """The basket comparison of ``items`` from the search ``results`` of each (retailer, item id)."""
    now = time.time() if now is None else now
    compared = [i for i in items if i.compare]
    skipped = [i.id for i in items if not i.compare]
    keys = [s.key for s in stores]
    refs = references(compared, keys, results)
    baskets: list[StoreBasket] = []
    for info in stores:
        basket = StoreBasket(store=info.key, label=info.label, store_label=info.store_label, item_count=len(compared))
        for item in compared:
            line = choose_line(
                item,
                info.key,
                results.get((info.key, item.id)),
                reference=refs.get(item.id),
                now=now,
                manual_max_age=manual_max_age,
            )
            basket.lines.append(line)
        _count(basket, info)
        baskets.append(basket)

    # Estimates of the missing and excluded lines: median of the other retailers
    amounts = {
        b.store: {li.item_id: li.line_total for li in b.lines if li.status == "found" and li.line_total is not None}
        for b in baskets
    }
    for basket in baskets:
        added = 0.0
        for line in basket.lines:
            if line.status in ("not_found", "unchecked", "excluded"):
                others = [a[line.item_id] for key, a in amounts.items() if key != basket.store and line.item_id in a]
                line.estimate = _median(others)
                if line.estimate is not None:
                    added += line.estimate
                    basket.estimated = True
        if basket.status == "ok" and basket.found_count:
            basket.estimated_total = round(basket.total + added, 2)

    # Ranking: complete baskets, then at least half of the items, by estimated total
    order = {b.store: index for index, b in enumerate(baskets)}
    for basket in baskets:
        countable = basket.item_count - basket.excluded_count
        coverage = basket.found_count / countable if countable else 0.0
        basket.ranked = (
            basket.status == "ok" and basket.found_count > 0 and (basket.complete or coverage >= MIN_COVERAGE)
        )
    ranked = sorted(
        (b for b in baskets if b.ranked),
        key=lambda b: (not b.complete, b.estimated_total, -b.found_count, order[b.store]),
    )
    for rank, basket in enumerate(ranked, start=1):
        basket.rank = rank

    comparison = BasketComparison(
        stores=ranked + [b for b in baskets if not b.ranked],
        ranking=[b.store for b in ranked],
        item_count=len(compared),
        skipped_count=len(skipped),
        skipped_item_ids=skipped,
        min_saving=min_saving,
        created_at=now,
    )
    complete = [b for b in ranked if b.complete]
    comparison.complete_count = len(complete)
    if complete:
        comparison.best_store = complete[0].store
        if len(complete) > 1:
            dearest = max(b.estimated_total for b in complete)
            for basket in complete:
                basket.saving = round(dearest - basket.estimated_total, 2)
    else:
        answered = ranked or [b for b in baskets if b.status == "ok" and b.found_count]
        if answered:
            best = min(answered, key=lambda b: (-b.found_count, b.estimated_total or 0.0, order[b.store]))
            comparison.most_items_store = best.store

    # Items found at every ranked retailer
    if ranked and compared:
        common = [i.id for i in compared if all(i.id in amounts[b.store] for b in ranked)]
        comparison.common_item_ids = common
        comparison.common_count = len(common)
        for basket in ranked:
            basket.common_total = round(sum(amounts[basket.store][i] for i in common), 2)

    # Each item at the cheapest retailer (kept for the pages of version 2)
    if compared:
        split_total = 0.0
        for item in compared:
            totals = [a[item.id] for a in amounts.values() if item.id in a]
            if totals:
                split_total += min(totals)
            else:
                comparison.split_missing += 1
        comparison.split_total = round(split_total, 2)

    comparison.plans = optimizer.optimize(comparison.stores, max_stores=2, min_saving=min_saving)
    return comparison


def _count(basket: StoreBasket, info: StoreInfo) -> None:
    """Totals and counts of a basket whose lines are chosen."""
    oldest = None
    for line in basket.lines:
        if line.status == "found":
            basket.found_count += 1
            basket.total = round(basket.total + line.line_total, 2)
            basket.stale_count += line.stale
            basket.manual_count += line.manual
            if line.fetched_at is not None:
                oldest = line.fetched_at if oldest is None else min(oldest, line.fetched_at)
        elif line.status == "not_found":
            basket.not_found_count += 1
        elif line.status == "unchecked":
            basket.unchecked_count += 1
        else:
            basket.excluded_count += 1
    basket.fetched_at = oldest
    basket.missing = basket.not_found_count + basket.unchecked_count
    basket.complete = basket.found_count > 0 and basket.missing == 0
    if basket.unchecked_count and basket.found_count == 0 and basket.not_found_count == 0:
        basket.status = "unchecked"
    failure = info.failure
    if failure is not None and (basket.unchecked_count or basket.stale_count):
        reason = failure.problem if failure.status == "ok" else failure.status
        basket.reason = reason
        basket.message = failure.message
        basket.retry_after = failure.retry_after
        basket.action = "retry" if failure.retry_after else ACTIONS.get(reason)


# ---------------------------------------------------------------------------
# Searches
# ---------------------------------------------------------------------------

EventHandler = Callable[[str, dict[str, Any]], Awaitable[None] | None]


async def _emit(on_event: EventHandler | None, name: str, data: dict[str, Any]) -> None:
    if on_event is None:
        return
    result = on_event(name, data)
    if inspect.isawaitable(result):
        await result


def _failure_of(result: StoreResult) -> StoreResult | None:
    """The failed search behind ``result`` (old prices served because the site failed included)."""
    if result.status in FAILED:
        return result
    if result.stale and result.problem:
        return result
    return None


async def cached_result(
    key: str, query: str, settings: Settings, failure: StoreResult | None = None, now: float | None = None
) -> StoreResult:
    """The result of a search read in the cache only (no call to the site).

    Fresh prices are served as such; older ones (up to 7 days) are marked stale
    with the message of ``failure``; nothing in the cache: the failure itself,
    or « not searched yet ».
    """
    now = time.time() if now is None else now
    scraper = SCRAPERS[key]
    store = settings.stores.get(key)
    result = StoreResult(store=key, label=scraper.label, status="ok", store_label=scraper.store_label(store))
    entry = await cache.get_entry(search.cache_key(scraper, store, query), config.CACHE_STALE_MAX_SECONDS, now)
    products: list[Product] = []
    if entry is not None:
        try:
            products = search.prepare_products([Product(**p) for p in entry.products], query)
        except (ValidationError, TypeError):
            entry = None
    if entry is not None:
        result.products, result.fetched_at, result.source, result.cached = (
            products,
            entry.created_at,
            entry.source,
            True,
        )
        if now - entry.created_at < search.cache_ttl(products):
            result.status, result.message = search.final_status(scraper, store, products)
            return result
        if products:  # older prices: shown, marked as old
            result.stale = True
            if failure is not None:
                problem = failure.problem if failure.status == "ok" else failure.status
                result.problem = problem
                result.retry_after = failure.retry_after
                result.message = search.stale_message(scraper.label, entry.created_at, problem, failure.retry_after)
            else:
                result.message = f"Prix du {_day(entry.created_at)} ({scraper.label})"
            result.status, _ = search.final_status(scraper, store, products)
            return result
    if failure is not None:
        if failure.status == "ok":  # old prices of the first search: same problem
            return StoreResult(
                store=key,
                label=scraper.label,
                status=failure.problem or "error",
                message=failure.message,
                retry_after=failure.retry_after,
                store_label=result.store_label,
            )
        return failure.model_copy(update={"products": [], "store": key})
    return StoreResult(
        store=key,
        label=scraper.label,
        status="error",
        message=f"Prix pas encore lus chez {scraper.label}.",
        store_label=result.store_label,
    )


async def _fresh_in_cache(key: str, query: str, settings: Settings, now: float) -> bool:
    scraper = SCRAPERS[key]
    entry = await cache.get_entry(search.cache_key(scraper, settings.stores.get(key), query))
    return entry is not None and now - entry.created_at < search.cache_ttl(entry.products)


@dataclass
class _Run:
    """What a comparison collects while the retailers answer."""

    items: list[ListItem]
    stores: list[StoreInfo]
    results: dict[tuple[str, int], StoreResult | None]
    now: float
    manual_max_age: float
    total: int = 0
    done: int = 0


async def _search_retailer(
    run: _Run,
    info: StoreInfo,
    settings: Settings,
    refresh: bool,
    cache_only: bool,
    on_event: EventHandler | None,
) -> None:
    """Search the items at one retailer, one after the other (cached results first)."""
    key = info.key
    todo = [i for i in run.items if needs_search(i, key, run.now, run.manual_max_age)]
    if not refresh and not cache_only:
        cached = [await _fresh_in_cache(key, i.query, settings, run.now) for i in todo]
        todo = [i for i, c in zip(todo, cached, strict=True) if c] + [
            i for i, c in zip(todo, cached, strict=True) if not c
        ]
    for item in todo:
        if cache_only or info.failure is not None:
            result = await cached_result(key, item.query, settings, info.failure, run.now)
        else:
            result = await search_store(key, item.query, refresh, settings=settings, priority="basket")
            info.failure = _failure_of(result)
        run.results[(key, item.id)] = result
        run.done += 1
        if on_event is not None:
            known = [
                run.results[(k.key, item.id)].products for k in run.stores if _usable(run.results.get((k.key, item.id)))
            ]
            line = choose_line(
                item,
                key,
                result,
                reference=reference_for(item, known),
                now=run.now,
                manual_max_age=run.manual_max_age,
            )
            await _emit(
                on_event, "line", {"store": key, "item_id": item.id, "line": line, "done": run.done, "total": run.total}
            )
    failure = info.failure
    await _emit(
        on_event,
        "store",
        {
            "store": key,
            "status": "ok" if failure is None else (failure.problem if failure.status == "ok" else failure.status),
            "message": failure.message if failure is not None else None,
            "retry_after": failure.retry_after if failure is not None else None,
        },
    )


async def get_prefs() -> BasketPrefs:
    return await prefs.get(PREFS_SECTION, BasketPrefs)


async def update_prefs(update: BasketPrefsUpdate) -> BasketPrefs:
    def change(current: BasketPrefs) -> None:
        for name, value in update.model_dump(exclude_none=True).items():
            setattr(current, name, value)

    return await prefs.update(PREFS_SECTION, BasketPrefs, change)


def _retailers(stores: Sequence[str] | None) -> list[str]:
    wanted = list(dict.fromkeys(stores or SCRAPERS))
    return [k for k in wanted if k in SCRAPERS]


async def compare_basket(
    stores: list[str] | None = None,
    refresh: bool = False,
    *,
    cache_only: bool = False,
    on_event: EventHandler | None = None,
) -> BasketComparison:
    """Compare the list at ``stores`` (every retailer by default).

    ``on_event(name, data)`` (function or coroutine function) follows the
    progress: ``start {items, stores, total}``, ``line {store, item_id, line,
    done, total}`` (one per search, the cell may still change in ``done``),
    ``store {store, status, message, retry_after}`` when a retailer is over,
    ``done {comparison}``.
    """
    items = await get_list()
    version = await list_repo.get_version()
    keys = _retailers(stores)
    settings = await load_settings()
    basket_prefs = await get_prefs()
    now = time.time()
    infos = [
        StoreInfo(key=k, label=SCRAPERS[k].label, store_label=SCRAPERS[k].store_label(settings.stores.get(k)))
        for k in keys
    ]
    manual_max_age = basket_prefs.manual_weeks * 7 * 86400
    compared = [i for i in items if i.compare]
    run = _Run(items=compared, stores=infos, results={}, now=now, manual_max_age=manual_max_age)
    run.total = sum(needs_search(i, k, now, manual_max_age) for k in keys for i in compared)
    await _emit(
        on_event,
        "start",
        {
            "items": [{"id": i.id, "query": i.query} for i in compared],
            "stores": [{"store": s.key, "label": s.label} for s in infos],
            "total": run.total,
            "skipped": [i.id for i in items if not i.compare],
        },
    )
    if on_event is not None:  # the lines that need no search, at once
        for info in infos:
            for item in compared:
                if not needs_search(item, info.key, now, manual_max_age):
                    line = choose_line(item, info.key, None, now=now, manual_max_age=manual_max_age)
                    await _emit(
                        on_event,
                        "line",
                        {"store": info.key, "item_id": item.id, "line": line, "done": run.done, "total": run.total},
                    )
    await asyncio.gather(*(_search_retailer(run, info, settings, refresh, cache_only, on_event) for info in infos))
    comparison = build_comparison(
        items, infos, run.results, now=now, manual_max_age=manual_max_age, min_saving=basket_prefs.min_saving
    )
    comparison.search_count = run.done
    comparison.cache_only = cache_only
    comparison.list_version = version
    try:
        await list_repo.save_last_basket(comparison.model_dump(mode="json"), version)
    except Exception:  # noqa: BLE001 (the last basket is a convenience)
        logger.warning("Last basket not saved", exc_info=True)
    await hooks.emit("basket_compared", comparison=comparison)
    await _emit(on_event, "done", {"comparison": comparison})
    return comparison


async def last_comparison() -> BasketComparison | None:
    """The last comparison (shown again without searching), None when there is none."""
    raw = await list_repo.get_last_basket()
    if not raw:
        return None
    try:
        return BasketComparison(**raw)
    except (ValidationError, TypeError):
        logger.info("Last basket unreadable")
        return None


# ---------------------------------------------------------------------------
# « Changer » (B60)
# ---------------------------------------------------------------------------


def sort_candidates(products: Sequence[Product]) -> list[Product]:
    """Suitable products by price per kg/L in the dominant unit, then by price; unavailable last."""
    relevant = [p for p in products if p.relevance >= 1 and p.price is not None]
    unit = dominant_unit(c for p in relevant if (c := contents_of(p)))

    def key(p: Product):
        contents = contents_of(p)
        same_unit = contents is not None and contents[1] == unit
        return (not p.available, not same_unit, unit_price_of(p, contents) if same_unit else math.inf, p.price)

    return sorted(relevant, key=key)


async def candidates(item_id: int, store: str, refresh: bool = False) -> Candidates | None:
    """Products of ``store`` that suit the item (from the cache when it is fresh)."""
    item = await get_item(item_id)
    if item is None:
        return None
    result = await search_store(store, item.query, refresh, priority="interactive")
    basket_prefs = await get_prefs()
    line = choose_line(
        item,
        store,
        result,
        reference=reference_for(item, [result.products]),
        manual_max_age=basket_prefs.manual_weeks * 7 * 86400,
    )
    auto = choose_auto(
        result.products, item.quantity, parse_target(item.target), reference_for(item, [result.products])
    )
    return Candidates(
        item_id=item.id,
        store=store,
        label=result.label,
        query=item.query,
        status=result.status,
        message=result.message,
        products=sort_candidates(result.products),
        current_url=line.product.product_url if line.product is not None else None,
        basis=line.basis,
        auto_url=auto[0].product_url if auto else None,
        fetched_at=result.fetched_at,
        stale=result.stale,
    )
