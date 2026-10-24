"""Where to buy the basket: one retailer, or two (area of P5, B61). Pure functions.

``optimize(baskets)`` looks at every plan of one and two retailers (among the
retailers of a basket comparison), buys each item at the cheapest retailer of
the plan, and estimates the items that no retailer of the plan has as the basket
does (the median price of the retailers that have it). It returns the plans to
show: the best single retailer, then the best pair when it is worth the trip
(it saves at least ``min_saving`` euros, or it has more items).

Order of the plans: complete plans first (at equal cost, an incomplete plan is
always below a complete one), then the estimated total, then fewer missing
items, then fewer retailers, then the order of the baskets given (the ranking
of the comparison: at equal price, the better ranked retailer wins, and an item
of a pair goes to the first retailer of the pair).
"""

import itertools
import statistics
from collections.abc import Sequence

from backend.models import Plan, PlanStore, StoreBasket

# A plan must have at least this share of the items (as a ranked basket)
MIN_COVERAGE = 0.5


def found_prices(basket: StoreBasket) -> dict[int, float]:
    """{item id: amount} of the lines counted in ``basket``."""
    return {
        line.item_id: line.line_total for line in basket.lines if line.status == "found" and line.line_total is not None
    }


def median_prices(baskets: Sequence[StoreBasket]) -> dict[int, float]:
    """{item id: median amount among the retailers that have it}."""
    amounts: dict[int, list[float]] = {}
    for basket in baskets:
        for item_id, amount in found_prices(basket).items():
            amounts.setdefault(item_id, []).append(amount)
    return {item_id: round(statistics.median(values), 2) for item_id, values in amounts.items()}


def item_ids_of(baskets: Sequence[StoreBasket]) -> list[int]:
    seen: dict[int, None] = {}
    for basket in baskets:
        for line in basket.lines:
            seen.setdefault(line.item_id, None)
    return list(seen)


def evaluate(
    combo: Sequence[StoreBasket],
    item_ids: Sequence[int],
    prices: dict[str, dict[int, float]],
    medians: dict[int, float],
) -> Plan:
    """The plan « buy each item at the cheapest retailer of ``combo`` »."""
    parts = {basket.store: PlanStore(store=basket.store, label=basket.label) for basket in combo}
    missing: list[int] = []
    estimate = 0.0
    for item_id in item_ids:
        options = [
            (prices[basket.store][item_id], index, basket.store)
            for index, basket in enumerate(combo)
            if item_id in prices[basket.store]
        ]
        if not options:
            missing.append(item_id)
            estimate += medians.get(item_id, 0.0)
            continue
        amount, _, store = min(options)
        parts[store].item_ids.append(item_id)
        parts[store].total = round(parts[store].total + amount, 2)
    order = {basket.store: index for index, basket in enumerate(combo)}
    stores = sorted(parts.values(), key=lambda p: (-len(p.item_ids), order[p.store]))
    total = round(sum(p.total for p in stores), 2)
    return Plan(
        kind={1: "single", 2: "pair"}.get(len(combo), "multi"),
        stores=stores,
        total=total,
        estimated_total=round(total + estimate, 2),
        estimated=any(item_id in medians for item_id in missing),
        missing=len(missing),
        missing_item_ids=missing,
        complete=not missing,
    )


def plan_key(plan: Plan, order: dict[str, int]) -> tuple:
    """Sort key of the plans (see the module docstring)."""
    return (
        not plan.complete,
        round(plan.estimated_total, 2),
        plan.missing,
        len(plan.stores),
        tuple(sorted(order[p.store] for p in plan.stores)),
    )


def all_plans(baskets: Sequence[StoreBasket], max_stores: int = 2) -> list[Plan]:
    """Every useful plan of 1 to ``max_stores`` retailers, best first.

    A single retailer must be ranked by the comparison (complete or at least
    half of the items); a plan of several retailers must have at least half of
    the items, and each of its retailers must sell at least one of them.
    """
    usable = [b for b in baskets if b.status == "ok" and found_prices(b)]
    item_ids = item_ids_of(baskets)
    if not usable or not item_ids:
        return []
    prices = {b.store: found_prices(b) for b in usable}
    medians = median_prices(usable)
    order = {b.store: index for index, b in enumerate(usable)}
    plans = []
    for size in range(1, max(1, max_stores) + 1):
        for combo in itertools.combinations(usable, size):
            if size == 1 and not combo[0].ranked:
                continue
            plan = evaluate(combo, item_ids, prices, medians)
            if size > 1 and any(not part.item_ids for part in plan.stores):
                continue  # the same as a smaller plan
            if (len(item_ids) - plan.missing) / len(item_ids) < MIN_COVERAGE:
                continue
            plans.append(plan)
    return sorted(plans, key=lambda p: plan_key(p, order))


def worth_it(plan: Plan, single: Plan | None, min_saving: float) -> bool:
    """A plan of several retailers is worth the trip: more items, or ``min_saving`` euros less."""
    if single is None:
        return True
    if plan.missing < single.missing:
        return True
    return plan.missing == single.missing and single.estimated_total - plan.estimated_total >= min_saving - 1e-9


def optimize(baskets: Sequence[StoreBasket], max_stores: int = 2, min_saving: float = 3.0) -> list[Plan]:
    """The plans to show: the best single retailer, then the best pair when it is worth it."""
    plans = all_plans(baskets, max_stores)
    single = next((p for p in plans if p.kind == "single"), None)
    shown = [single] if single else []
    for plan in plans:
        if plan.kind == "single":
            continue
        if single is not None:
            plan.saving = round(single.estimated_total - plan.estimated_total, 2)
        plan.worth_it = worth_it(plan, single, min_saving)
        if plan.worth_it:
            shown.append(plan)  # the best plan of several retailers worth the trip
            break
    return shown
