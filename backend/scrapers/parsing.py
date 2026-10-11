"""Pure text helpers: prices, pack sizes, prices per kg / litre / piece, barcodes (area of P2)."""

import logging
import re
from dataclasses import dataclass

from backend.models import Product

logger = logging.getLogger("prixmalin.parsing")


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


# "2€49" style (euro sign between euros and cents)
_EURO_MIDDLE = re.compile(r"(?<![\d.,])(\d{1,5})\s*€\s*(\d{2})(?!\d)")
_DECIMAL = re.compile(r"(?<![\d.,])(\d{1,5})\s*[.,]\s*(\d{1,2})(?![\d.,])")
_INTEGER = re.compile(r"(?<![\d.,])(\d{1,5})(?![\d.,])")


def parse_price(value: object) -> float | None:
    """Parse '2,49 €', '2€49', '0.69', 3 ... into a float (None if no price)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2) if value > 0 else None
    text = clean_text(str(value))
    candidates = []
    for pattern in (_EURO_MIDDLE, _DECIMAL):
        m = pattern.search(text)
        if m:
            cents = m.group(2).ljust(2, "0")
            candidates.append((m.start(), float(f"{m.group(1)}.{cents}")))
    if not candidates:
        m = _INTEGER.search(text)
        if m:
            candidates.append((m.start(), float(m.group(1))))
    if not candidates:
        return None
    price = min(candidates)[1]
    return price if price > 0 else None


# --- Barcodes ----------------------------------------------------------------


def valid_ean(value: object) -> str | None:
    """``value`` as an EAN-8 or EAN-13 string when its check digit is right, else None.

    A 12-digit UPC-A code is returned as the EAN-13 it is (leading zero).
    """
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return None
    digits = value.strip()
    if len(digits) == 12 and digits.isdigit():
        digits = "0" + digits
    if len(digits) not in (8, 13) or not digits.isdigit() or set(digits) == {"0"}:
        return None
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return digits if (10 - total % 10) % 10 == check else None


# --- Pack sizes -------------------------------------------------------------

_UNITS = {
    "kg": ("kg", 1.0),
    "kgs": ("kg", 1.0),
    "kilo": ("kg", 1.0),
    "kilos": ("kg", 1.0),
    "g": ("kg", 0.001),
    "gr": ("kg", 0.001),
    "grs": ("kg", 0.001),
    "mg": ("kg", 0.000001),
    "l": ("L", 1.0),
    "litre": ("L", 1.0),
    "litres": ("L", 1.0),
    "liter": ("L", 1.0),
    "dl": ("L", 0.1),
    "cl": ("L", 0.01),
    "ml": ("L", 0.001),
}
PIECE = "pièce"
_UNIT_RE = r"(kgs?|kilos?|grs?|g|mg|litres?|l|dl|cl|ml)"
_NUM_RE = r"(\d+(?:[.,]\d+)?)"
_END = r"(?![a-zà-ÿ'’])"
# Things sold several at once: "6 bouteilles de 1,5 L", "Pack 6 bouteilles 1,5 L"
_CONTAINER_RE = (
    r"(?:bouteilles?|pots?|sachets?|briques?|briquettes?|canettes?|cannettes?|bo[iî]tes?|bocaux|bocal|"
    r"flacons?|berlingots?|barquettes?|sticks?|tubes?|dosettes?|capsules?|portions?|paquets?|packs?|"
    r"bidons?|verrines?|tablettes?|tranches?|rouleaux|rouleau|gourdes?|yaourts?|minis?)"
)
_MULTI_BEFORE = re.compile(rf"(?<![\d.,])(\d+)\s*[x×*]\s*{_NUM_RE}\s*{_UNIT_RE}{_END}", re.I)
_MULTI_AFTER = re.compile(rf"(?<![\d.,]){_NUM_RE}\s*{_UNIT_RE}\s*[x×*]\s*(\d+)(?![\d.,])", re.I)
_CONTAINER = re.compile(
    rf"(?<![\d.,])(\d+)\s+{_CONTAINER_RE}\s+(?:de\s+|d'|x\s*)?{_NUM_RE}\s*{_UNIT_RE}{_END}",
    re.I,
)
_PACK = re.compile(rf"\b(?:pack|lot)\s+(?:de\s+)?(\d+)(?![\d.,])\D{{0,40}}?{_NUM_RE}\s*{_UNIT_RE}{_END}", re.I)
_SINGLE = re.compile(rf"(?<![\w.,]){_NUM_RE}\s*{_UNIT_RE}{_END}", re.I)
# 1L5, 1L50 = 1,5 L
_LITRE_SPLIT = re.compile(r"(?<![\d.,])(\d+)\s?l(\d{1,2})(?![\w.,])", re.I)
# "+ 1 offert", "+ 2 offertes" (more items) and "+ 20 % gratuit" (more contents)
_FREE_ITEMS = re.compile(r"\+\s*(\d+)\s*(?:offert|gratuit)(?:e|s|es)?\b(?!\s*%)", re.I)
_FREE_SHARE = re.compile(r"\+\s*(\d+(?:[.,]\d+)?)\s*%", re.I)
# Sold by weight or by piece: "le kg", "au kg", "la pièce"
_PER_KG = re.compile(r"(?<![a-z])(?:le|au|par|du)\s+(?:kg|kilo)(?![a-z])", re.I)
_PER_PIECE = re.compile(r"(?<![a-z])(?:la|à la|a la|par)\s+pi[eè]ce(?![a-z])", re.I)

# Counted items: "x12", "12 œufs", "lot de 6 rouleaux"
_COUNT_NOUNS = {
    "oeuf": "œuf",
    "oeufs": "œuf",
    "œuf": "œuf",
    "œufs": "œuf",
    "rouleau": "rouleau",
    "rouleaux": "rouleau",
    "lavage": "lavage",
    "lavages": "lavage",
    "couche": "couche",
    "couches": "couche",
    "capsule": "capsule",
    "capsules": "capsule",
    "dosette": "dosette",
    "dosettes": "dosette",
    "sachet": "sachet",
    "sachets": "sachet",
    "pastille": "pastille",
    "pastilles": "pastille",
    "tablette": "tablette",
    "tablettes": "tablette",
    "lingette": "lingette",
    "lingettes": "lingette",
    "portion": "portion",
    "portions": "portion",
    "tranche": "tranche",
    "tranches": "tranche",
    "pot": "pot",
    "pots": "pot",
    "yaourt": "yaourt",
    "yaourts": "yaourt",
    "pièce": PIECE,
    "pièces": PIECE,
    "piece": PIECE,
    "pieces": PIECE,
    "unité": PIECE,
    "unités": PIECE,
    "unite": PIECE,
    "unites": PIECE,
}
_COUNT_NOUN_RE = "(" + "|".join(sorted(map(re.escape, _COUNT_NOUNS), key=len, reverse=True)) + ")"
_COUNT_WITH_NOUN = re.compile(rf"(?<![\w.,])(\d+)\s*{_COUNT_NOUN_RE}(?![\wà-ÿ])", re.I)
# "3 x 4 yaourts", "2 x 6 œufs"
_COUNT_TIMES_NOUN = re.compile(rf"(?<![\w.,])(\d+)\s*[x×]\s*(\d+)\s*{_COUNT_NOUN_RE}(?![\wà-ÿ])", re.I)
# "Lot de 6", "pack de 4" without any contents
_LOT_OF = re.compile(r"\b(?:lot|pack)\s+(?:de\s+)?(\d+)(?![\d.,])", re.I)
_COUNT_X = re.compile(r"(?<![\w.,])[x×]\s*(\d+)(?![\d.,])|(?<![\w.,])(\d+)\s*[x×](?![\w\d])", re.I)
_ANY_COUNT_NOUN = re.compile(rf"(?<![\wà-ÿ]){_COUNT_NOUN_RE}(?![\wà-ÿ])", re.I)


def _to_float(text: str) -> float:
    return float(text.replace(",", "."))


@dataclass(frozen=True)
class Pack:
    """Contents of a product: ``count`` items of ``size`` ``unit`` ("kg", "L" or "pièce")."""

    count: int
    size: float
    unit: str
    # What one piece is ("œuf", "rouleau"...) when the product is sold by the piece
    count_label: str | None = None

    @property
    def total(self) -> float:
        return round(self.count * self.size, 6)


def _measured(count: str | int, amount: str, unit: str) -> Pack:
    base, factor = _UNITS[unit.lower()]
    return Pack(int(count), _to_float(amount) * factor, base)


def _measured_pack(text: str) -> Pack | None:
    m = _MULTI_BEFORE.search(text)
    if m:
        return _measured(m.group(1), m.group(2), m.group(3))
    m = _MULTI_AFTER.search(text)
    if m:
        return _measured(m.group(3), m.group(1), m.group(2))
    m = _CONTAINER.search(text) or _PACK.search(text)
    if m:
        return _measured(m.group(1), m.group(2), m.group(3))
    m = _SINGLE.search(text)
    if m:
        return _measured(1, m.group(1), m.group(2))
    if _PER_KG.search(text):
        return Pack(1, 1.0, "kg")
    return None


def _count_label(text: str) -> str | None:
    """What is counted in ``text`` ("œuf" in "Oeufs frais x12"), None when it does not say."""
    noun = _ANY_COUNT_NOUN.search(text)
    label = _COUNT_NOUNS[noun.group(1).lower()] if noun else None
    return None if label == PIECE else label


def _counted_pack(text: str) -> Pack | None:
    m = _COUNT_TIMES_NOUN.search(text)
    if m:
        return Pack(int(m.group(1)) * int(m.group(2)), 1.0, PIECE, _count_label(m.group(3)))
    m = _COUNT_WITH_NOUN.search(text)
    if m:
        return Pack(int(m.group(1)), 1.0, PIECE, _count_label(m.group(2)))
    m = _COUNT_X.search(text) or _LOT_OF.search(text)
    if m:
        return Pack(int(next(g for g in m.groups() if g)), 1.0, PIECE, _count_label(text))
    if _PER_PIECE.search(text):
        return Pack(1, 1.0, PIECE)
    return None


def parse_pack(text: str | None) -> Pack | None:
    """Contents of a product from its label or its name.

    '6x1L5' -> 6 x 1,5 L ; 'Lot de 3 bouteilles de 1L' -> 3 x 1 L ; '2 x 1 L + 1 offert'
    -> 3 x 1 L ; '1L + 20% gratuit' -> 1 x 1,2 L ; 'Oeufs x12' -> 12 pièces (œuf).
    """
    text = clean_text(text)
    if not text:
        return None
    text = _LITRE_SPLIT.sub(r"\1,\2 l", text)
    pack = _measured_pack(text) or _counted_pack(text)
    if pack is None or pack.count <= 0 or pack.size <= 0:
        return None
    free = _FREE_ITEMS.search(text)
    if free:
        pack = Pack(pack.count + int(free.group(1)), pack.size, pack.unit, pack.count_label)
    share = _FREE_SHARE.search(text)
    if share and pack.unit != PIECE:
        pack = Pack(pack.count, pack.size * (1 + _to_float(share.group(1)) / 100), pack.unit, pack.count_label)
    return pack


def parse_quantity(text: str | None) -> tuple[float, str] | None:
    """Total contents in kg, L or pièces: '6x1,5L' -> (9.0, 'L'), '500 g' -> (0.5, 'kg')."""
    pack = parse_pack(text)
    return (round(pack.total, 6), pack.unit) if pack else None


_QUANTITY_PATTERNS = (
    _MULTI_BEFORE,
    _MULTI_AFTER,
    _CONTAINER,
    _LITRE_SPLIT,
    _SINGLE,
    _COUNT_TIMES_NOUN,
    _COUNT_WITH_NOUN,
    _COUNT_X,
)


def quantity_spans(text: str) -> list[tuple[int, int]]:
    """Where the quantities are in ``text`` ('eau 1,5 l', '6x1,5L', '1kg'), to remove them."""
    spans: list[tuple[int, int]] = []
    for pattern in _QUANTITY_PATTERNS:
        for m in pattern.finditer(text):
            if not any(start <= m.start() < end or m.start() <= start < m.end() for start, end in spans):
                spans.append((m.start(), m.end()))
    return sorted(spans)


# --- Prices per unit --------------------------------------------------------

# Fragments such as "0,69 €/kg", "KG = 0.69", "1 kg = 2,49 €", "Prix au litre : 1,20 €"
UNIT_PRICE_FRAGMENT = re.compile(
    r"\d+\s*[.,]\s*\d{1,2}\s*€?\s*(?:/|par|le|la|au)\s*(?:\d+\s*)?"
    r"(?:kg|kilo|grs?|g|litre|l|ml|cl|pi[eè]ce|unit[eé])(?![a-z])"
    r"|(?:1\s*)?(?:kg|l|litre|100\s*g|100\s*ml)\s*[=:]\s*\d+(?:\s*[.,]\s*\d{1,2})?\s*€?"
    r"|prix\s+(?:au|du|par)\s+(?:kg|kilo|litre|l)\s*:?\s*\d+\s*[.,]\s*\d{1,2}\s*€?",
    re.I,
)

# Denominator of a price per unit: "/ 500 g", "le kg", "au litre", "100 g", "la pièce"
_DENOMINATOR = re.compile(
    r"(?<![\w.,])(?:(\d+(?:[.,]\d+)?)\s*)?"
    rf"(kgs?|kilos?|grs?|g|litres?|liter|l|cl|ml|pi[eè]ces?|unit[eé]s?|pce|u|{_COUNT_NOUN_RE[1:-1]})(?![a-zà-ÿ])",
    re.I,
)
_PIECE_WORDS = {"pièce", "pièces", "piece", "pieces", "unité", "unités", "unite", "unites", "pce", "u"} | set(
    _COUNT_NOUNS
)
# A price written as such: with € or with cents
_PRICE_IN_TEXT = re.compile(
    r"(?<![\d.,])\d{1,5}(?:\s*[.,]\s*\d{1,2})?\s*€|(?<![\d.,])\d{1,5}\s*[.,]\s*\d{1,2}(?![\d.,])|€\s*\d{1,5}(?:[.,]\d{1,2})?"
)


def _denominator(text: str, skip: tuple[int, int] | None = None, last: bool = False) -> tuple[float, str] | None:
    """(amount, unit) of the first (or ``last``) unit of ``text`` outside ``skip``: '/ 500 g' -> (0.5, 'kg').

    A weight or a volume wins over a piece: « le sachet de 500 g » is per kg.
    """
    matches = list(_DENOMINATOR.finditer(text))
    pieces = []
    for m in reversed(matches) if last else matches:
        if skip and skip[0] <= m.start() < skip[1]:
            continue
        word = m.group(2).lower()
        amount = _to_float(m.group(1)) if m.group(1) else 1.0
        if amount <= 0:
            continue
        if word in _PIECE_WORDS:
            pieces.append((amount, PIECE))
            continue
        base, factor = _UNITS[word]
        return amount * factor, base
    return pieces[0] if pieces else None


def parse_unit_price(label: str | None) -> tuple[float, str] | None:
    """Parse a price per unit into (€ per kg | L | pièce, unit).

    '3,45 € / KG', 'KG = 0.69', '1 kg = 12 €', '0,35 €/100 gr' (3,50 €/kg),
    '2,49 € / 500 g' (4,98 €/kg), '1,99 € / 75 cl' (2,65 €/L), '1,23 € la pièce'.
    """
    text = clean_text(label).lower()
    if not text:
        return None
    if "=" in text:
        # "1 kg = 2,49 €": the price is after the sign, what it is for before
        left, right = text.split("=", 1)
        price = _PRICE_IN_TEXT.search(right)
        value = parse_price(price.group(0) if price else right)
        denominator = _denominator(left, last=True) or _denominator(right, price.span() if price else (0, len(right)))
    else:
        price = _PRICE_IN_TEXT.search(text)
        if not price:
            return None
        value = parse_price(price.group(0))
        denominator = _denominator(text, price.span())
    if value is None or denominator is None:
        return None
    amount, unit = denominator
    return round(value / amount, 2), unit


# --- Normalised product -----------------------------------------------------

# Above this ratio between the price per unit shown by the site and the one
# computed from the price and the contents, the site's value is not trusted
UNIT_PRICE_GUARD = 3.0
_UNIT_NAMES = {
    "unité": PIECE,
    "unite": PIECE,
    "u": PIECE,
    "pce": PIECE,
    "piece": PIECE,
    "pièce": PIECE,
    "l": "L",
    "litre": "L",
    "kg": "kg",
    "kilo": "kg",
}


def finalize_product(product: Product) -> Product:
    """Fill the normalised price per unit (€/kg, €/L or €/pièce) from the label or the contents.

    A price per unit shown by the site that is more than 3 times off the one
    computed from the price and the contents is replaced by the computed one.
    """
    if product.unit:
        product.unit = _UNIT_NAMES.get(product.unit.lower(), product.unit)
    if product.unit_price is None and product.unit_price_label:
        parsed = parse_unit_price(product.unit_price_label)
        if parsed:
            product.unit_price, product.unit = parsed
    if product.unit == PIECE and product.count_label is None and product.unit_price_label:
        product.count_label = _count_label(product.unit_price_label)  # "0,25 €/œuf"
    pack = parse_pack(product.quantity_label) or parse_pack(product.name)
    if pack is None:
        return product
    if pack.unit == PIECE and product.count_label is None and product.unit in (None, PIECE):
        product.count_label = pack.count_label
    if product.price is None:
        return product
    computed = round(product.price / pack.total, 2)
    if computed <= 0:
        return product
    if product.unit_price is None or product.unit is None:
        product.unit_price, product.unit = computed, pack.unit
    elif product.unit == pack.unit and product.unit_price > 0:
        ratio = product.unit_price / computed
        if ratio > UNIT_PRICE_GUARD or ratio < 1 / UNIT_PRICE_GUARD:
            logger.warning(
                "%s « %s » : prix au %s du site (%.2f) écarté, %.2f calculé",
                product.store,
                product.name,
                product.unit,
                product.unit_price,
                computed,
            )
            product.unit_price = computed
    return product
