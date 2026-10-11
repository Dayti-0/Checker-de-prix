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
    "Plan",
    "PlanStore",
    "StoreBasket",
    "Template",
    "TemplateApply",
    "TemplateCreate",
    "UsualItem",
]

QUERY_MAX = 120
TARGET_MAX = 40
NOTE_MAX = 200

# found: a product is counted; not_found: the retailer answered but has nothing
# suitable; unchecked: the retailer could not be searched (store to choose,
# anti-robot check, timeout, error); excluded: « pas disponible ici »
LineStatus = Literal["found", "not_found", "unchecked", "excluded"]
# pick: product chosen by the user; ean: same barcode as a product chosen at
# another retailer; auto: chosen by the basket; manual: price seen in the store
LineBasis = Literal["pick", "auto", "ean", "manual"]


def _known_store(store: str | None) -> str | None:
    from backend.scrapers import SCRAPERS  # the scrapers import the models

    if store is not None and store not in SCRAPERS:
        raise ValueError("enseigne inconnue")
    return store


class Pick(Product):
    """A product chosen by the user for one retailer (or a price seen in the store)."""

    # When it was chosen (for a manual price: the day it was seen)
    picked_at: float | None = None
    source: Literal["site", "manual"] = "site"
    # False when the server could not read its price again in the search results
    verified: bool = True


class ListItem(BaseModel):
    id: int
    query: str
    quantity: int = 1
    picks: dict[str, Pick] = {}
    # Quantity wanted (« 1 kg », « 6 L », « 12 »): the basket buys enough packs
    target: str | None = None
    # Aisle shown (chosen by the user when category_set, else guessed)
    category: str = ""
    category_set: bool = False
    note: str | None = None
    # False: kept in the list but left out of the basket totals
    compare: bool = True
    # Retailers where the user said « pas disponible ici »
    excluded: list[str] = []
    checked: bool = False
    checked_at: float | None = None


class ListItemCreate(BaseModel):
    query: str = Field(min_length=1, max_length=QUERY_MAX)
    quantity: int = Field(default=1, ge=1, le=99)
    product: Product | None = None
    target: str | None = Field(default=None, max_length=TARGET_MAX)
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    category: str | None = Field(default=None, max_length=60)

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
    seen_at: float | None = None

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
    category: str | None = Field(default=None, max_length=60)
    compare: bool | None = None
    set_pick: Product | None = None
    # Back to the automatic choice (also forgets « pas disponible ici »)
    remove_pick: str | None = None
    exclude_store: str | None = None
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
    query: str
    quantity: int = 1
    target: str | None = None


class BulkRequest(BaseModel):
    items: list[ListItemCreate] = Field(max_length=300)


class FinishRequest(BaseModel):
    # uncheck: everything unticked; remove: the ticked items leave the list
    mode: Literal["uncheck", "remove"] = "uncheck"


class CheckUpdate(BaseModel):
    id: int
    checked: bool
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


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


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
    status: LineStatus = "not_found"
    product: Product | None = None
    # Packs bought: the quantity, or enough packs for the target
    packs: int | None = None
    line_total: float | None = None
    picked: bool = False
    basis: LineBasis | None = None
    # Why the line is unchecked, or a note on its price
    message: str | None = None
    # Chosen product not found in the fresh results: its last known price
    stale: bool = False
    # Price of a chosen product that could not be read again on the site
    verified: bool = True
    manual: bool = False
    # Manual price too old: shown, not counted
    expired: bool = False
    # When the price was read (Unix time)
    fetched_at: float | None = None
    # Missing line: median of the other retailers (estimated_total)
    estimate: float | None = None


class StoreBasket(BaseModel):
    store: str
    label: str
    store_label: str | None = None
    # unchecked: no line could be checked, the retailer is not ranked
    status: Literal["ok", "unchecked"] = "ok"
    # Status of the failed search (store_required, blocked, timeout, error)
    reason: str | None = None
    message: str | None = None
    total: float = 0.0
    found_count: int = 0
    item_count: int = 0
    # Lines not found or unchecked (excluded ones are not missing)
    missing: int = 0
    unchecked_count: int = 0
    excluded_count: int = 0
    # Items found at every ranked retailer
    common_total: float | None = None
    # Total plus, for each missing item, the median of the other retailers
    estimated_total: float | None = None
    estimated: bool = False
    complete: bool = False
    rank: int | None = None
    # Saving against the most expensive complete basket
    saving: float | None = None
    # Oldest price of the basket (Unix time)
    fetched_at: float | None = None
    lines: list[BasketLine] = []


class PlanStore(BaseModel):
    store: str
    label: str
    item_ids: list[int] = []
    total: float = 0.0


class Plan(BaseModel):
    stores: list[PlanStore]
    total: float = 0.0
    estimated_total: float = 0.0
    missing: int = 0
    complete: bool = False
    # Against the best single-retailer plan (positive = cheaper)
    saving: float = 0.0


class BasketComparison(BaseModel):
    stores: list[StoreBasket]
    # Cheapest complete basket (None when no retailer has everything)
    best_store: str | None = None
    # Retailer with the most items found (when no basket is complete)
    most_items_store: str | None = None
    # Ranked retailers, best first
    ranking: list[str] = []
    item_count: int = 0
    # Items found at every ranked retailer
    common_count: int = 0
    # Items of the list left out of the comparison (compare = False)
    skipped_count: int = 0
    # Plans of the optimizer: the best single retailer, then the best pair when it saves enough
    plans: list[Plan] = []
    min_saving: float = 3.0
    # Cheapest total when each item is bought at the cheapest retailer
    split_total: float | None = None
    split_missing: int = 0
    created_at: float | None = None
    # Only prices already read were used (cache_only)
    cache_only: bool = False


class Candidates(BaseModel):
    """Products of a retailer that suit a list item (sheet « Changer »)."""

    item_id: int
    store: str
    label: str
    query: str
    status: str
    message: str | None = None
    products: list[Product] = []
    current_url: str | None = None
    basis: LineBasis | None = None
    fetched_at: float | None = None


class BasketPrefs(BaseModel):
    """Settings of the basket (prefs section ``p5.basket``)."""

    # « Ça vaut le détour à partir de 3 € »
    min_saving: float = Field(default=3.0, ge=0, le=100)
    # Weeks a price typed by hand is counted
    manual_weeks: int = Field(default=6, ge=1, le=52)


class BasketPrefsUpdate(BaseModel):
    min_saving: float | None = Field(default=None, ge=0, le=100)
    manual_weeks: int | None = Field(default=None, ge=1, le=52)
