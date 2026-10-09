"""Pure text helpers: prices, pack sizes and prices per kg / litre."""

import re

from backend.models import Product


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ").replace(" ", " ")
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


# --- Pack sizes -------------------------------------------------------------

_UNITS = {
    "kg": ("kg", 1.0),
    "g": ("kg", 0.001),
    "gr": ("kg", 0.001),
    "mg": ("kg", 0.000001),
    "l": ("L", 1.0),
    "litre": ("L", 1.0),
    "litres": ("L", 1.0),
    "dl": ("L", 0.1),
    "cl": ("L", 0.01),
    "ml": ("L", 0.001),
}
_UNIT_RE = r"(kg|gr|g|mg|litres?|l|dl|cl|ml)"
_NUM_RE = r"(\d+(?:[.,]\d+)?)"
_MULTI_BEFORE = re.compile(rf"(\d+)\s*[x×*]\s*{_NUM_RE}\s*{_UNIT_RE}(?![a-z])", re.I)
_MULTI_AFTER = re.compile(rf"{_NUM_RE}\s*{_UNIT_RE}\s*[x×*]\s*(\d+)(?!\d)", re.I)
_SINGLE = re.compile(rf"(?<![\w.,]){_NUM_RE}\s*{_UNIT_RE}(?![a-z'’])", re.I)


def _to_float(text: str) -> float:
    return float(text.replace(",", "."))


def parse_quantity(text: str | None) -> tuple[float, str] | None:
    """Return the pack size in kg or L: '6x1,5L' -> (9.0, 'L'), '500 g' -> (0.5, 'kg')."""
    text = clean_text(text)
    if not text:
        return None
    m = _MULTI_BEFORE.search(text)
    if m:
        count, amount, unit = int(m.group(1)), _to_float(m.group(2)), m.group(3)
    else:
        m = _MULTI_AFTER.search(text)
        if m:
            amount, unit, count = _to_float(m.group(1)), m.group(2), int(m.group(3))
        else:
            m = _SINGLE.search(text)
            if not m:
                return None
            count, amount, unit = 1, _to_float(m.group(1)), m.group(2)
    base, factor = _UNITS[unit.lower()]
    total = count * amount * factor
    return (total, base) if total > 0 else None


# --- Prices per unit --------------------------------------------------------

# Fragments such as "0,69 €/kg", "KG = 0.69", "1 kg = 2,49 €", "Prix au litre : 1,20 €"
UNIT_PRICE_FRAGMENT = re.compile(
    r"\d+\s*[.,]\s*\d{1,2}\s*€?\s*(?:/|par|le|la|au)\s*(?:100\s*)?"
    r"(?:kg|kilo|g|litre|l|ml|cl|pi[eè]ce|unit[eé])(?![a-z])"
    r"|(?:1\s*)?(?:kg|l|litre|100\s*g|100\s*ml)\s*[=:]\s*\d+\s*[.,]\s*\d{1,2}\s*€?"
    r"|prix\s+(?:au|du|par)\s+(?:kg|kilo|litre|l)\s*:?\s*\d+\s*[.,]\s*\d{1,2}\s*€?",
    re.I,
)

_PER_UNIT = [
    (re.compile(r"100\s*g(?![a-z])"), "kg", 10.0),
    (re.compile(r"100\s*ml(?![a-z])"), "L", 10.0),
    (re.compile(r"(?<![a-z])(kg|kilo)"), "kg", 1.0),
    (re.compile(r"(?<![a-z])(l|litre|liter)(?![a-z])"), "L", 1.0),
    (re.compile(r"(?<![a-z])cl(?![a-z])"), "L", 100.0),
    (re.compile(r"(?<![a-z])ml(?![a-z])"), "L", 1000.0),
    (re.compile(r"(?<![a-z])g(?![a-z])"), "kg", 1000.0),
    (re.compile(r"pi[eè]ce|unit[eé]|(?<![a-z])(u|pce)(?![a-z])"), "unité", 1.0),
]


def parse_unit_price(label: str | None) -> tuple[float, str] | None:
    """Parse '3,45 € / KG', 'KG = 0.69', '0,35 €/100 g' into (price per kg|L|unité, unit)."""
    text = clean_text(label).lower()
    if not text:
        return None
    value = parse_price(text)
    if value is None:
        return None
    for pattern, unit, factor in _PER_UNIT:
        if pattern.search(text):
            return round(value * factor, 2), unit
    return None


def finalize_product(product: Product) -> Product:
    """Fill the normalised price per unit from the label or the pack size."""
    if product.unit_price is None and product.unit_price_label:
        parsed = parse_unit_price(product.unit_price_label)
        if parsed:
            product.unit_price, product.unit = parsed
    if product.unit_price is None and product.price is not None:
        quantity = parse_quantity(product.quantity_label) or parse_quantity(product.name)
        if quantity:
            amount, unit = quantity
            product.unit_price = round(product.price / amount, 2)
            product.unit = unit
    return product
