"""Site-independent extraction of products from HTML cards, JSON-LD and JSON.

Retailers change their CSS classes often. These extractors rely on what every
product listing has in common (a link to the product page, a name, a price in
euros) so that a scraper keeps working when its specific selectors break.
"""

import json
import re
from typing import Any, Iterator
from urllib.parse import urljoin

from backend.models import Product
from backend.scrapers.parsing import UNIT_PRICE_FRAGMENT, clean_text, parse_price

# Runs in the page. Finds product cards and returns their raw texts; all the
# parsing happens in Python (see card_to_product) so it can be unit tested.
CARDS_JS = r"""
(opts) => {
  const clean = (s) => (s || '').replace(/[  ]/g, ' ').replace(/\s+/g, ' ').trim();
  const linkRe = opts.linkPattern ? new RegExp(opts.linkPattern, 'i') : null;
  const isProductLink = (a) => {
    const h = a.getAttribute('href') || '';
    return h && !h.startsWith('#') && !h.startsWith('javascript') && (!linkRe || linkRe.test(h));
  };
  const priceLike = /\d\s*[.,]\s*\d{2}\s*€|\d\s*€\s*\d{2}|€\s*\d|\d\s*€/;
  const hrefKey = (a) => a.href.split('#')[0];

  let cards = [];
  if (opts.cardSelector) {
    const all = [...document.querySelectorAll(opts.cardSelector)];
    cards = all.filter((el) => !all.some((other) => other !== el && other.contains(el)));
  } else {
    // Climb from each product link to the smallest block that shows a price
    // and does not contain another product.
    const seen = new Set();
    for (const a of document.querySelectorAll('a[href]')) {
      if (!isProductLink(a) || seen.has(hrefKey(a))) continue;
      let node = a, card = null;
      for (let depth = 0; depth < 8; depth++) {
        node = node.parentElement;
        if (!node || node === document.body) break;
        const hrefs = new Set([...node.querySelectorAll('a[href]')].filter(isProductLink).map(hrefKey));
        if (hrefs.size > 1) break;
        if (priceLike.test(node.textContent || '')) { card = node; break; }
      }
      if (card && !cards.includes(card)) { seen.add(hrefKey(a)); cards.push(card); }
    }
  }

  const textOf = (root, sel) => {
    if (!sel) return null;
    const el = root.querySelector(sel);
    return el ? clean(el.getAttribute('content') || el.textContent) || null : null;
  };
  const strikeSel = 'del, s, strike, [class*="old-price" i], [class*="oldprice" i], [class*="price-old" i], '
    + '[class*="price--old" i], [class*="strike" i], [class*="barre" i], [class*="crossed" i], [class*="was-price" i]';

  const out = [];
  for (const card of cards.slice(0, opts.limit || 60)) {
    const links = [...card.querySelectorAll('a[href]')].filter(isProductLink);
    if (card.matches('a[href]') && isProductLink(card)) links.unshift(card);
    const names = [];
    const push = (v) => { v = clean(v); if (v && !names.includes(v)) names.push(v); };
    if (opts.nameSelector) push(textOf(card, opts.nameSelector));
    for (const l of links) { push(l.getAttribute('title')); push(l.getAttribute('aria-label')); }
    for (const el of card.querySelectorAll('h2, h3, h4, [itemprop="name"], [class*="title" i], [class*="name" i]')) push(el.textContent);
    for (const l of links) push(l.textContent);
    const img = card.querySelector('img');
    if (img) push(img.getAttribute('alt'));

    let image = null;
    if (img) {
      const srcset = (img.getAttribute('srcset') || img.getAttribute('data-srcset') || '').split(',').pop().trim().split(' ')[0];
      const candidates = [img.currentSrc, img.getAttribute('src'), img.getAttribute('data-src'), img.getAttribute('data-lazy-src'), srcset];
      const found = candidates.find((u) => u && !u.startsWith('data:'));
      if (found) { try { image = new URL(found, location.href).href; } catch (e) { image = found; } }
    }
    const priceTexts = [];
    if (opts.priceSelector) {
      for (const el of card.querySelectorAll(opts.priceSelector)) {
        if (el.closest(strikeSel)) continue;
        priceTexts.push(clean(el.getAttribute('content') || el.textContent));
      }
    }
    out.push({
      url: links.length ? links[0].href : null,
      names,
      brand: textOf(card, opts.brandSelector),
      priceTexts,
      unitText: textOf(card, opts.unitSelector),
      quantityText: textOf(card, opts.quantitySelector),
      strike: [...card.querySelectorAll(strikeSel)].map((e) => clean(e.textContent)).filter(Boolean),
      text: clean(card.innerText || card.textContent).slice(0, 800),
      image,
    });
  }
  return out;
}
"""

JSON_LD_JS = """
() => [...document.querySelectorAll('script[type="application/ld+json"]')].map((s) => s.textContent)
"""

_JUNK_NAME = re.compile(
    r"^(ajouter|voir\b|acheter|d[ée]couvrir|en savoir|plus d|(produit )?sponsoris[ée]|"
    r"(promo|nouveau|nouveaut[ée]|offre|best-?seller)$|[\d\s.,€%-]+$)",
    re.I,
)


def _pick_name(names: list[str]) -> str | None:
    for name in names:
        name = clean_text(name)
        if len(name) < 3 or len(name) > 200 or _JUNK_NAME.match(name):
            continue
        if parse_price(name) is not None and "€" in name and len(name) < 15:
            continue
        return name
    return None


def card_to_product(card: dict, store: str, base_url: str) -> Product | None:
    """Turn a raw card returned by CARDS_JS into a Product."""
    name = _pick_name(card.get("names") or [])
    if not name:
        return None

    strike = [clean_text(s) for s in card.get("strike") or []]
    price = None
    for text in card.get("priceTexts") or []:
        if not text or text in strike or UNIT_PRICE_FRAGMENT.search(text):
            continue
        price = parse_price(text)
        if price is not None:
            break

    text = clean_text(card.get("text"))
    unit_label = clean_text(card.get("unitText")) or None
    if unit_label is None:
        m = UNIT_PRICE_FRAGMENT.search(text)
        unit_label = m.group(0) if m else None
    if price is None and text:
        remaining = UNIT_PRICE_FRAGMENT.sub(" ", text)
        for s in strike:
            remaining = remaining.replace(s, " ")
        # Only consider amounts written as prices (with € or cents)
        m = re.search(r"\d+\s*[.,]\s*\d{2}\s*€|\d+\s*€\s*\d{2}|€\s*\d+(?:[.,]\d{2})?|\d+\s*€", remaining)
        if m:
            price = parse_price(m.group(0))

    old_price = next((p for p in (parse_price(s) for s in strike) if p), None)
    promo = None
    if price is not None and old_price is not None and old_price > price:
        promo = f"Au lieu de {old_price:.2f} €".replace(".", ",")

    url = card.get("url")
    return Product(
        store=store,
        name=name,
        brand=clean_text(card.get("brand")) or None,
        price=price,
        unit_price_label=unit_label,
        quantity_label=clean_text(card.get("quantityText")) or None,
        image_url=urljoin(base_url, card["image"]) if card.get("image") else None,
        product_url=urljoin(base_url, url) if url else base_url,
        promo=promo,
    )


async def extract_cards(page, store: str, base_url: str, **options: Any) -> list[Product]:
    raw = await page.evaluate(CARDS_JS, {k: v for k, v in options.items() if v})
    products = [card_to_product(card, store, base_url) for card in raw]
    return [p for p in products if p is not None]


# --- JSON-LD ----------------------------------------------------------------


def products_from_json_ld(texts: list[str], store: str, base_url: str) -> list[Product]:
    products: list[Product] = []
    for text in texts:
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            continue
        for obj in _walk(data):
            types = obj.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Product" not in types:
                continue
            offers = obj.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            price = None
            if isinstance(offers, dict):
                price = parse_price(offers.get("price") or offers.get("lowPrice"))
            name = clean_text(obj.get("name"))
            if not name:
                continue
            brand = obj.get("brand")
            if isinstance(brand, dict):
                brand = brand.get("name")
            products.append(
                Product(
                    store=store,
                    name=name,
                    brand=clean_text(brand) if isinstance(brand, str) else None,
                    price=price,
                    image_url=first_url(obj.get("image")),
                    product_url=urljoin(base_url, obj.get("url") or "") or base_url,
                )
            )
    return products


async def extract_json_ld(page, store: str, base_url: str) -> list[Product]:
    return products_from_json_ld(await page.evaluate(JSON_LD_JS), store, base_url)


# --- Generic JSON (API responses) -------------------------------------------

_NAME_KEYS = ("name", "title", "fullTitle", "libelle", "label", "productName", "designation", "displayName")
_PRICE_KEYS = ("price", "prix", "currentPrice", "salePrice", "sellingPrice", "finalPrice")
_URL_KEYS = ("canonicalUrl", "url", "productUrl", "link", "href", "slug")
_IMAGE_KEYS = ("image", "imageUrl", "images", "thumbnail", "media", "picture")


def _walk(data: Any, depth: int = 0) -> Iterator[dict]:
    if depth > 10:
        return
    if isinstance(data, dict):
        yield data
        for value in data.values():
            yield from _walk(value, depth + 1)
    elif isinstance(data, list):
        for value in data:
            yield from _walk(value, depth + 1)


def _price_value(value: Any) -> float | None:
    if isinstance(value, dict):
        for key in ("value", "amount", "price", "current", "centAmount"):
            if key in value:
                price = _price_value(value[key])
                if key == "centAmount" and price is not None:
                    price = round(price / 100, 2)
                if price is not None:
                    return price
        return None
    return parse_price(value)


def first_url(value: Any) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, list):
        for item in value:
            url = first_url(item)
            if url:
                return url
    if isinstance(value, dict):
        for key in ("url", "src", "href", "large", "medium", "main", "image"):
            url = first_url(value.get(key))
            if url:
                return url
    return None


def products_from_json(data: Any, store: str, base_url: str) -> list[Product]:
    """Find product-like objects (a name and a price) anywhere in a JSON document."""
    products: list[Product] = []
    seen: set[tuple[str, float | None]] = set()

    def visit(node: Any, depth: int) -> None:
        if depth > 10:
            return
        if isinstance(node, list):
            for item in node:
                visit(item, depth + 1)
            return
        if not isinstance(node, dict):
            return
        name = next((clean_text(node[k]) for k in _NAME_KEYS if isinstance(node.get(k), str) and node[k].strip()), None)
        price = next((p for p in (_price_value(node.get(k)) for k in _PRICE_KEYS if k in node) if p is not None), None)
        if name and price is not None:
            if (name, price) not in seen:
                seen.add((name, price))
                url = next((node[k] for k in _URL_KEYS if isinstance(node.get(k), str) and node[k]), "")
                image = next((u for u in (first_url(node.get(k)) for k in _IMAGE_KEYS) if u), None)
                brand = node.get("brand") or node.get("marque")
                if isinstance(brand, dict):
                    brand = brand.get("name") or brand.get("label")
                products.append(
                    Product(
                        store=store,
                        name=name,
                        brand=clean_text(brand) if isinstance(brand, str) else None,
                        price=price,
                        image_url=urljoin(base_url, image) if image else None,
                        product_url=urljoin(base_url, url) if url else base_url,
                    )
                )
            return
        for value in node.values():
            visit(value, depth + 1)

    visit(data, 0)
    return products
