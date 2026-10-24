"""Optimizer of the basket: one or two retailers (B61), pure functions of services/optimizer.py."""

from backend.models import BasketLine, StoreBasket
from backend.services.optimizer import all_plans, evaluate, median_prices, optimize, worth_it

LABELS = {"aldi": "Aldi", "lidl": "Lidl", "carrefour": "Carrefour", "intermarche": "Intermarché"}
ITEMS = {1: "farine", 2: "sucre", 3: "lait", 4: "beurre"}


def basket(store, prices, *, ranked=True, status="ok"):
    """A basket whose lines are found at ``prices`` ({item id: amount}); the other items are missing."""
    lines = []
    for item_id, query in ITEMS.items():
        amount = prices.get(item_id)
        line = BasketLine(item_id=item_id, query=query, quantity=1)
        if amount is not None:
            line.status, line.line_total = "found", amount
        lines.append(line)
    found = sum(1 for li in lines if li.status == "found")
    return StoreBasket(
        store=store,
        label=LABELS[store],
        status=status,
        lines=lines,
        found_count=found,
        item_count=len(ITEMS),
        missing=len(ITEMS) - found,
        complete=found == len(ITEMS),
        ranked=ranked,
    )


def three_stores():
    return [
        basket("carrefour", {1: 0.85, 2: 1.15, 3: 1.05, 4: 1.90}),  # 4,95 complete
        basket("aldi", {1: 0.79, 2: 1.09, 3: 0.95, 4: 2.50}),  # 5,33 complete
        basket("lidl", {1: 0.75, 2: 0.99, 3: 0.89}),  # no butter
    ]


def names(plan):
    return [part.store for part in plan.stores]


def test_best_pair_of_three_retailers():
    plans = all_plans(three_stores())
    best = plans[0]
    assert (best.kind, names(best), best.total, best.complete) == ("pair", ["lidl", "carrefour"], 4.53, True)
    assert best.stores[0].item_ids == [1, 2, 3] and best.stores[1].item_ids == [4]
    assert (best.stores[0].total, best.stores[1].total) == (2.63, 1.9)
    # Every pair, then the complete singles, then Lidl alone (incomplete)
    assert [(names(p), p.estimated_total) for p in plans] == [
        (["lidl", "carrefour"], 4.53),
        (["aldi", "carrefour"], 4.73),
        (["carrefour"], 4.95),
        (["lidl", "aldi"], 5.13),
        (["aldi"], 5.33),
        (["lidl"], 4.83),
    ]
    lidl = plans[-1]
    assert (lidl.missing, lidl.missing_item_ids, lidl.estimated, lidl.total) == (1, [4], True, 2.63)


def test_pair_shown_only_when_worth_the_trip():
    stores = three_stores()
    shown = optimize(stores, min_saving=3.0)
    assert [names(p) for p in shown] == [["carrefour"]]
    assert shown[0].kind == "single" and shown[0].total == 4.95
    shown = optimize(stores, min_saving=0.4)
    assert [names(p) for p in shown] == [["carrefour"], ["lidl", "carrefour"]]
    assert (shown[1].saving, shown[1].worth_it) == (0.42, True)


def test_pair_with_more_items_is_always_worth_it():
    stores = [
        basket("aldi", {1: 1.0, 2: 1.0, 3: 1.0}),  # no butter
        basket("lidl", {4: 3.0}, ranked=False),  # only butter, dear
    ]
    shown = optimize(stores, min_saving=3.0)
    assert [names(p) for p in shown] == [["aldi"], ["aldi", "lidl"]]
    pair = shown[1]
    assert pair.complete and pair.total == 6.0 and pair.worth_it
    assert pair.saving == 0.0  # 3 + estimated butter 3 = 6 for Aldi alone


def test_at_equal_cost_an_incomplete_plan_is_below_a_complete_one():
    stores = [
        basket("lidl", {1: 1.0, 2: 1.0, 3: 1.0}),  # 3 € + butter estimated 1 € = 4 €
        basket("aldi", {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0}),  # 4 €, complete
    ]
    plans = all_plans(stores)
    singles = [p for p in plans if p.kind == "single"]
    assert [(names(p), p.estimated_total, p.complete) for p in singles] == [
        (["aldi"], 4.0, True),
        (["lidl"], 4.0, False),
    ]
    # Same with cheaper incomplete plans: complete first
    stores[0] = basket("lidl", {1: 0.5, 2: 0.5, 3: 0.5})
    assert names(all_plans(stores)[0]) in (["aldi"], ["lidl", "aldi"])
    assert all_plans(stores)[0].complete


def test_ties_go_to_the_better_ranked_retailer():
    stores = [basket("aldi", {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0}), basket("lidl", {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0})]
    plans = all_plans(stores)
    # Same total: the first retailer given (the first of the ranking) wins; no useless pair
    assert [names(p) for p in plans] == [["aldi"], ["lidl"]]
    # In a pair, an item at the same price goes to the first retailer of the pair
    stores = [basket("aldi", {1: 1.0, 2: 2.0, 3: 1.0, 4: 1.0}), basket("lidl", {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0})]
    prices = {b.store: {li.item_id: li.line_total for li in b.lines} for b in stores}
    pair = evaluate(stores, list(ITEMS), prices, median_prices(stores))
    assert [(p.store, p.item_ids) for p in pair.stores] == [("aldi", [1, 3, 4]), ("lidl", [2])]


def test_useless_pairs_and_small_plans_are_left_out():
    stores = [
        basket("aldi", {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0}),
        basket("carrefour", {1: 2.0, 2: 2.0, 3: 2.0, 4: 2.0}),  # never cheaper than Aldi: no pair with it
        basket("lidl", {1: 0.5}, ranked=False),  # one item: not alone
        basket("intermarche", {}, ranked=False, status="unchecked"),
    ]
    plans = all_plans(stores)
    assert [names(p) for p in plans] == [["aldi", "lidl"], ["aldi"], ["carrefour", "lidl"], ["carrefour"]]
    assert [(p.store, p.item_ids) for p in plans[0].stores] == [("aldi", [2, 3, 4]), ("lidl", [1])]
    assert plans[0].total == 3.5


def test_no_usable_retailer():
    assert optimize([basket("intermarche", {}, ranked=False, status="unchecked")]) == []
    assert optimize([]) == []


def test_worth_it_rule():
    stores = three_stores()
    plans = all_plans(stores)
    single = next(p for p in plans if p.kind == "single")
    pair = plans[0]
    assert worth_it(pair, single, 0.42)
    assert not worth_it(pair, single, 0.43)
    assert worth_it(pair, None, 100)
