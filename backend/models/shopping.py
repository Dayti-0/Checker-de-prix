"""Shopping list and basket comparison (area of P5)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backend.models.products import Product

__all__ = [
    "BasketComparison",
    "BasketLine",
    "BasketPrefs",
    "BasketPrefsUpdate",
    "BasketRequest",
    "BulkRequest",
    "Candidates",
    "CheckUpdate",
    "ChecksRequest",
    "FinishRequest",
    "LineBasis",
    "LineStatus",
    "ListItem",
    "ListItemCreate",
    "ListItemUpdate",
    "ListVersion",
    "ManualPrice",
    "ParseRequest",
    "ParsedLine",
    "Pick",
    "PickIssue",
    "Plan",
    "PlanStore",
    "RestoreRequest",
    "StoreAction",
    "StoreBasket",
    "Template",
    "TemplateApply",
    "TemplateCreate",
    "TemplateDetail",
    "Trip",
    "TripAisle",
    "TripItem",
    "TripStore",
    "UsualItem",
]

QUERY_MAX = 120
TARGET_MAX = 40
NOTE_MAX = 200
CATEGORY_MAX = 60
TEMPLATE_NAME_MAX = 60
# Longest shopping list (services/shopping_list.MAX_ITEMS)
MAX_ITEMS = 300

# found: a product is counted; not_found: the retailer answered but has nothing
# suitable; unchecked: the retailer could not be searched (store to choose,
# anti-robot check, timeout, error), its message says why; excluded: the user
# said « pas disponible ici » (not counted as missing)
LineStatus = Literal["found", "not_found", "unchecked", "excluded"]
# pick: product chosen by the user; ean: same barcode as a product chosen at
# another retailer; auto: chosen by the basket; manual: price seen in the store
LineBasis = Literal["pick", "auto", "ean", "manual"]
# Why the product chosen by the user is not the one counted: unavailable on the
# site, not found in the results (and too old to be counted), price typed by
# hand too old (expired), price never read by PrixMalin (unverified)
PickIssue = Literal["unavailable", "not_found", "expired", "unverified"]
# What the card of a retailer that could not be searched offers:
# « Choisir mon magasin », « Débloquer » (open the site), « Réessayer »
StoreAction = Literal["choose_store", "unblock", "retry"]


def _known_store(store: str | None) -> str | None:
    from backend.scrapers import SCRAPERS  # the scrapers import the models

    if store is not None and store not in SCRAPERS:
        raise ValueError("enseigne inconnue")
    return store


class Pick(Product):
    """A product chosen by the user for one retailer (or a price seen in the store)."""

    # When it was chosen (for a price typed by hand: the day it was seen)
    picked_at: float | None = None
    # When its price was read on the site (the search cache), None when unknown
    price_at: float | None = None
    source: Literal["site", "manual"] = "site"
    # False when the server could not read its price in the search results
    # (the price sent by the page is kept but marked « prix non vérifié »)
    verified: bool = True


class ListItem(BaseModel):
    id: int
    query: str
    # Normalised query (matching.query_key): one line per key
    key: str = ""
    quantity: int = 1
    picks: dict[str, Pick] = {}
    # Quantity wanted (« 1 kg », « 6 L », « 12 »): the basket buys enough packs
    # (the quantity is then ignored); None: ``quantity`` packs
    target: str | None = None
    # Aisle shown (chosen by the user when category_set, else guessed)
    category: str = ""
    category_set: bool = False
    note: str | None = None
    # False: kept in the list but left out of the basket (no search, no total)
    compare: bool = True
    # Retailers where the user said « pas disponible ici »
    excluded: list[str] = []
    checked: bool = False
    checked_at: float | None = None
    created_at: float | None = None


class ListItemCreate(BaseModel):
    query: str = Field(min_length=1, max_length=QUERY_MAX)
    quantity: int = Field(default=1, ge=1, le=99)
    product: Product | None = None
    target: str | None = Field(default=None, max_length=TARGET_MAX)
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    category: str | None = Field(default=None, max_length=CATEGORY_MAX)

    @field_validator("product")
    @classmethod
    def _known_retailer(cls, product: Product | None) -> Product | None:
        if product is not None:
            _known_store(product.store)
        return product


class ManualPrice(BaseModel):
    """A price seen in the store, typed by the user (B71)."""

    store: str
    name: str = Field(min_length=1, max_length=QUERY_MAX)
    price: float = Field(gt=0, le=10000)
    quantity_label: str | None = Field(default=None, max_length=TARGET_MAX)
    # Day the price was seen (Unix time); now when missing
    seen_at: float | None = Field(default=None, ge=0)

    @field_validator("store")
    @classmethod
    def _store(cls, value: str) -> str:
        return _known_store(value)


class ListItemUpdate(BaseModel):
    query: str | None = Field(default=None, min_length=1, max_length=QUERY_MAX)
    quantity: int | None = Field(default=None, ge=1, le=99)
    # "" removes the target / the note / the chosen aisle
    target: str | None = Field(default=None, max_length=TARGET_MAX)
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    category: str | None = Field(default=None, max_length=CATEGORY_MAX)
    compare: bool | None = None
    # « Changer » : this product at its retailer (its price is read again by the server)
    set_pick: Product | None = None
    # « Revenir au choix automatique » (also forgets « pas disponible ici »)
    remove_pick: str | None = None
    # « Pas disponible ici »
    exclude_store: str | None = None
    # « Saisir le prix »
    manual_price: ManualPrice | None = None
    checked: bool | None = None
    checked_at: float | None = None

    @field_validator("remove_pick", "exclude_store")
    @classmethod
    def _stores(cls, value: str | None) -> str | None:
        return _known_store(value)

    @field_validator("set_pick")
    @classmethod
    def _pick_store(cls, product: Product | None) -> Product | None:
        if product is not None:
            _known_store(product.store)
        return product


class ParseRequest(BaseModel):
    text: str = Field(max_length=20000)


class ParsedLine(BaseModel):
    """An item read in a pasted list (preview of « Coller une liste »)."""

    query: str
    quantity: int = 1
    target: str | None = None
    # Aisle guessed for the preview
    category: str = ""
    # Already in the list (its quantity will be added)
    existing: bool = False


class BulkRequest(BaseModel):
    items: list[ListItemCreate] = Field(max_length=300)


class RestoreRequest(BaseModel):
    """« Annuler » after a deletion: the ids of the deleted lines (``id`` or ``ids``).

    The server puts back the lines it kept; anything else sent is ignored.
    """

    id: int | None = None
    ids: list[int] = Field(default=[], max_length=MAX_ITEMS)

    def all_ids(self) -> list[int]:
        return ([self.id] if self.id is not None else []) + list(self.ids)


class FinishRequest(BaseModel):
    # uncheck: everything unticked; remove: the ticked items leave the list
    mode: Literal["uncheck", "remove"] = "uncheck"


class CheckUpdate(BaseModel):
    id: int
    checked: bool
    # When the item was ticked on the phone (Unix time): the latest tick wins
    checked_at: float | None = None


class ChecksRequest(BaseModel):
    checks: list[CheckUpdate] = Field(max_length=600)


class ListVersion(BaseModel):
    version: int


class UsualItem(BaseModel):
    query: str
    count: int


class Template(BaseModel):
    id: int
    name: str
    item_count: int = 0
    created_at: float = 0
    updated_at: float = 0


class TemplateDetail(Template):
    # The queries of the saved list, in their order
    queries: list[str] = []


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=TEMPLATE_NAME_MAX)


class TemplateApply(BaseModel):
    # replace: the list becomes the template; merge: its items are added
    mode: Literal["replace", "merge"] = "replace"


# --- Basket -----------------------------------------------------------------


class BasketRequest(BaseModel):
    stores: list[str] | None = None
    refresh: bool = False
    # Only the prices already read (after changing a product): no call to the sites
    cache_only: bool = False


class BasketLine(BaseModel):
    item_id: int
    query: str
    quantity: int
    target: str | None = None
    status: LineStatus = "not_found"
    # The product counted (found lines only)
    product: Product | None = None
    # Packs bought: the quantity, or enough packs for the target
    packs: int | None = None
    # Amount counted in the total (found lines only)
    line_total: float | None = None
    # The product counted is the user's (basis pick or manual): « ★ »
    picked: bool = False
    basis: LineBasis | None = None
    # Why the line is unchecked or not found, or a note on its price
    # (« Prix du 12/09, produit non retrouvé »)
    message: str | None = None
    # The price is not fresh: old prices shown because the site failed, or a
    # chosen product missing from the fresh results (its last known price)
    stale: bool = False
    # False: price of a chosen product that PrixMalin never read (« prix non vérifié »)
    verified: bool = True
    # Price typed by hand (« saisi le 03/10 »)
    manual: bool = False
    # Price typed by hand too old: shown (``pick``), not counted
    expired: bool = False
    # Price typed by hand: when it stops being counted (``manual_weeks`` setting),
    # for the reminder « à mettre à jour avant le 14/11 »
    expires_at: float | None = None
    # When the price was read (Unix time): age of the cell
    fetched_at: float | None = None
    # Missing or excluded line: median of the other retailers (estimated_total)
    estimate: float | None = None
    # The user's choice for this retailer as saved (even when it is not counted)
    pick: Pick | None = None
    pick_issue: PickIssue | None = None
    # Suitable products of the retailer for this item (sheet « Changer »)
    alternatives: int = 0


class StoreBasket(BaseModel):
    store: str
    label: str
    store_label: str | None = None
    # unchecked: no line could be checked, the retailer is not ranked
    status: Literal["ok", "unchecked"] = "ok"
    # Status of the failed search (store_required, blocked, timeout, error)
    # when lines are unchecked; its message and the action of the card
    reason: str | None = None
    message: str | None = None
    action: StoreAction | None = None
    # Hard block: no visit of the site before this time
    retry_after: float | None = None
    # Sum of the found lines
    total: float = 0.0
    found_count: int = 0
    # Items compared (the same for every retailer)
    item_count: int = 0
    # Lines not found or unchecked (excluded ones are not missing)
    missing: int = 0
    not_found_count: int = 0
    unchecked_count: int = 0
    excluded_count: int = 0
    # Found lines whose price is not fresh, or typed by hand
    stale_count: int = 0
    manual_count: int = 0
    # Sum of the items found at every ranked retailer (``common_item_ids``)
    common_total: float | None = None
    # Total plus, for each missing or excluded item, the median of the other
    # retailers (``estimated`` when at least one was added)
    estimated_total: float | None = None
    estimated: bool = False
    # Nothing missing (excluded lines allowed)
    complete: bool = False
    # Ranked: complete, or at least half of the items found
    ranked: bool = False
    rank: int | None = None
    # Complete basket: saving against the most expensive complete basket
    saving: float | None = None
    # Oldest price counted (Unix time)
    fetched_at: float | None = None
    lines: list[BasketLine] = []


class PlanStore(BaseModel):
    store: str
    label: str
    # Items bought there (ids of the list)
    item_ids: list[int] = []
    total: float = 0.0


class Plan(BaseModel):
    """Where to buy each item: one retailer, or two (optimizer, B61)."""

    # single: one retailer; pair: two (multi: more, when max_stores > 2)
    kind: Literal["single", "pair", "multi"] = "single"
    stores: list[PlanStore]
    total: float = 0.0
    # Total plus the median price of each missing item
    estimated_total: float = 0.0
    estimated: bool = False
    missing: int = 0
    missing_item_ids: list[int] = []
    complete: bool = False
    # Against the best single-retailer plan (positive = cheaper)
    saving: float = 0.0
    # Pair: saves at least ``min_saving``, or has more items than the best single plan
    worth_it: bool = False


class BasketComparison(BaseModel):
    # Retailers in the order of ``ranking``, then the unranked ones
    stores: list[StoreBasket]
    # Cheapest complete basket (None when no retailer has everything)
    best_store: str | None = None
    # Retailer with the most items found (when no basket is complete)
    most_items_store: str | None = None
    # Ranked retailers, best first
    ranking: list[str] = []
    complete_count: int = 0
    # Items compared (compare = True)
    item_count: int = 0
    # Items found at every ranked retailer
    common_count: int = 0
    common_item_ids: list[int] = []
    # Items of the list left out of the comparison (compare = False)
    skipped_count: int = 0
    skipped_item_ids: list[int] = []
    # Plans of the optimizer: the best single retailer, then the best pair when
    # it is worth the trip
    plans: list[Plan] = []
    min_saving: float = 3.0
    # Cheapest total when each item is bought at the cheapest retailer (2.x)
    split_total: float | None = None
    split_missing: int = 0
    # Searches (retailer × item) done for this comparison
    search_count: int = 0
    created_at: float | None = None
    # Only prices already read were used (cache_only)
    cache_only: bool = False
    # Version of the list compared (GET /api/list/version; ticks included)
    list_version: int | None = None
    # What the comparison depends on in the list (basket.basket_signature: items,
    # quantities, targets, choices; not the ticks, notes or aisles)
    list_signature: str | None = None
    # GET /api/basket/last: the list changed since (another signature): compare again
    outdated: bool = False


class Candidates(BaseModel):
    """Products of a retailer that suit a list item (sheet « Changer »)."""

    item_id: int
    store: str
    label: str
    query: str
    status: str
    message: str | None = None
    # Suitable products, by price per kg/L in the dominant unit, then by price
    products: list[Product] = []
    # Product counted now (the user's choice, or the automatic one)
    current_url: str | None = None
    basis: LineBasis | None = None
    # What the automatic choice would take
    auto_url: str | None = None
    fetched_at: float | None = None
    stale: bool = False


class TripItem(BaseModel):
    """An item of the list in the mode « En magasin », with what the basket retained."""

    item: ListItem
    # Retailer where it is bought (None: not in the plan, or no basket)
    store: str | None = None
    # Line of the basket at that retailer (None: none)
    status: LineStatus | None = None
    product: Product | None = None
    packs: int | None = None
    line_total: float | None = None
    picked: bool = False
    manual: bool = False
    stale: bool = False
    fetched_at: float | None = None


class TripAisle(BaseModel):
    name: str
    items: list[TripItem] = []


class TripStore(BaseModel):
    """The items bought at one retailer, by aisle (``store`` None: the other items)."""

    store: str | None = None
    label: str
    store_label: str | None = None
    aisles: list[TripAisle] = []
    item_count: int = 0
    checked_count: int = 0
    # Sum of the lines found (``checked_total``: of the ticked items)
    total: float = 0.0
    checked_total: float = 0.0


class Trip(BaseModel):
    """The list in the store (``GET /api/list/trip``): by retailer, then by aisle."""

    # What was asked: one retailer, or a plan of the last basket (index in ``plans``)
    store: str | None = None
    plan: int | None = None
    stores: list[TripStore] = []
    item_count: int = 0
    checked_count: int = 0
    total: float = 0.0
    checked_total: float = 0.0
    # Last basket used for the products and prices (None: no basket yet)
    basket_at: float | None = None
    # The list changed since that basket (its products may be wrong)
    outdated: bool = False
    # The retailer or plan asked is not in the last basket
    unknown: bool = False


class BasketPrefs(BaseModel):
    """Settings of the basket (prefs section ``p5.basket``)."""

    # « Ça vaut le détour à partir de 3 € »
    min_saving: float = Field(default=3.0, ge=0, le=100)
    # Weeks a price typed by hand is counted
    manual_weeks: int = Field(default=6, ge=1, le=52)


class BasketPrefsUpdate(BaseModel):
    min_saving: float | None = Field(default=None, ge=0, le=100)
    manual_weeks: int | None = Field(default=None, ge=1, le=52)
