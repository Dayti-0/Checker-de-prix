"""Site-independent extraction of products from HTML cards, JSON-LD and JSON.

Retailers change their CSS classes often. These extractors rely on what every
product listing has in common (a link to the product page, a name, a price in
euros) so that a scraper keeps working when its specific selectors break.

Also here: the reading of a second page of results (``PageBudget``,
``read_more``, ``merge_pages``), shared by the scrapers.
"""

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Iterator
from typing import Any
from urllib.parse import urljoin

from backend import config
from backend.models import Product
from backend.scrapers.parsing import UNIT_PRICE_FRAGMENT, clean_text, parse_price, valid_ean

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
    const titles = 'h2, h3, h4, [itemprop="name"], [class*="title" i], [class*="name" i]';
    for (const el of card.querySelectorAll(titles)) push(el.textContent);
    for (const l of links) push(l.textContent);
    const img = card.querySelector('img');
    if (img) push(img.getAttribute('alt'));

    let image = null;
    if (img) {
      // A light thumbnail: the smallest candidate of at least 200 px of the srcset
      const sources = (img.getAttribute('srcset') || img.getAttribute('data-srcset') || '').split(',')
        .map((c) => c.trim().split(/\s+/)).filter((c) => c[0])
        .map(([u, w]) => [u, parseInt(w, 10) || 0]).sort((a, b) => a[1] - b[1]);
      const srcset = (sources.find((c) => c[1] >= 200) || sources[sources.length - 1] || [''])[0];
      const candidates = [img.currentSrc, img.getAttribute('src'), img.getAttribute('data-src'),
        img.getAttribute('data-lazy-src'), srcset];
      const found = candidates.find((u) => u && !u.startsWith('data:'));
      if (found) { try { image = new URL(found, location.href).href; } catch (e) { image = found; } }
    }
    const attrOf = (names) => {
      for (const n of names) {
        const el = card.matches(`[${n}]`) ? card : card.querySelector(`[${n}]`);
        const v = el ? clean(el.getAttribute(n)) : '';
        if (v) return v;
      }
      return null;
    };
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
      ean: attrOf(['data-ean', 'data-ean13', 'data-gtin', 'data-gtin13', 'data-barcode'])
        || textOf(card, '[itemprop^="gtin"]'),
      sku: attrOf(['data-sku', 'data-pid', 'data-product-id', 'data-productid', 'data-article-id',
        'data-articleid', 'data-item-id']),
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
    sku = clean_text(card.get("sku")) or None
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
        old_price=old_price if promo else None,
        ean=valid_ean(card.get("ean")) or valid_ean(sku),
        sku=sku,
    )


async def extract_cards(page, store: str, base_url: str, **options: Any) -> list[Product]:
    raw = await page.evaluate(CARDS_JS, {k: v for k, v in options.items() if v})
    products = [card_to_product(card, store, base_url) for card in raw]
    return [p for p in products if p is not None]


# --- Several pages of results -----------------------------------------------

logger = logging.getLogger("prixmalin.extract")

# Another page is read only before this share of the time of a search
PAGE_BUDGET_SHARE = 0.5
# Pause before another page, as a person who scrolls
PAGE_PAUSE_MS = 800


class PageBudget:
    """Time of a search: another page of results only in its first half (B39)."""

    def __init__(self, key: str, timeout: float | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.timeout = config.scraper_timeout(key) if timeout is None else timeout
        self.clock = clock
        self.start = clock()

    def elapsed(self) -> float:
        return self.clock() - self.start

    def allows_more(self) -> bool:
        return self.elapsed() < PAGE_BUDGET_SHARE * self.timeout

    def wait_ms(self, longest: float = 8000) -> float:
        """Longest wait for another page that keeps the search within its time."""
        return max(500.0, min(longest, (self.timeout * 0.9 - self.elapsed()) * 1000))


def merge_pages(*pages: list[Product]) -> list[Product]:
    """The products of several pages, each once (same barcode, or same page, name and price)."""
    seen: set[tuple] = set()
    merged: list[Product] = []
    for products in pages:
        for product in products:
            key = ("ean", product.ean) if product.ean else (product.product_url, product.name.lower(), product.price)
            if key not in seen:
                seen.add(key)
                merged.append(product)
    return merged


async def pause_between_pages(page) -> None:
    """Wait a little before another page of results, as a person who scrolls."""
    await page.wait_for_timeout(PAGE_PAUSE_MS)


def json_of(result) -> dict | None:
    """The JSON object of a ``page_fetch`` answer, None when it failed or is not JSON."""
    if not (result.ok and result.is_json):
        return None
    try:
        data = result.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


# Finds the way to more results: a link to the next page, or a « Voir plus » button
MORE_JS = r"""
(opts) => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const what = '(?:produits|résultats|articles)';
  // « Voir plus », « Afficher plus de produits », « Charger la suite »... (buttons and links)
  const more = new RegExp('^(?:(?:voir|afficher|charger|montrer)(?: les)? (?:plus|la suite)(?: de ' + what
    + ')?|plus de ' + what + ')$', 'i');
  // « Page suivante », « Suivant » (links only: carousels have « Suivant » buttons)
  const nextPage = /^(?:page suivante|suivante?|›|»)$/i;
  const usable = (el) => !el.disabled && el.getAttribute('aria-disabled') !== 'true'
    && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
    && !(opts.cardSelector && el.closest(opts.cardSelector));
  const here = location.href.split('#')[0];
  const linkTo = (el) => {
    const href = el.tagName === 'A' ? el.href : '';
    return href && !href.startsWith('javascript') && href.split('#')[0] !== here ? href : null;
  };
  const rel = document.querySelector('a[rel="next"][href], link[rel="next"][href]');
  if (rel && rel.href && rel.href.split('#')[0] !== here) return {next: rel.href};
  for (const el of document.querySelectorAll('button, a[href], [role="button"]')) {
    const text = clean(el.innerText || el.textContent) || clean(el.getAttribute('aria-label'));
    if (text.length > 60 || !usable(el)) continue;
    const href = linkTo(el);
    if (more.test(text)) {
      if (href) return {next: href};
      const count = opts.cardSelector ? document.querySelectorAll(opts.cardSelector).length : 0;
      el.click();
      return {clicked: true, count};
    }
    if (href && nextPage.test(text)) return {next: href};
  }
  return null;
}
"""

_MORE_LOADED_JS = "([selector, count]) => document.querySelectorAll(selector).length > count"


async def read_more(
    page,
    extract: Callable[[], Awaitable[list[Product]]],
    budget: PageBudget,
    card_selector: str | None = None,
) -> list[Product]:
    """Products of the next page of results (« Voir plus » or a link to page 2), [] when there is none.

    Only within the first half of the time of the search (``budget``).
    """
    if not budget.allows_more():
        return []
    await pause_between_pages(page)
    action = await page.evaluate(MORE_JS, {"cardSelector": card_selector})
    if not action:
        return []
    timeout = budget.wait_ms()
    try:
        if action.get("next"):
            await page.goto(action["next"], wait_until="domcontentloaded", timeout=timeout)
            if card_selector:
                await page.wait_for_selector(card_selector, timeout=timeout)
        elif card_selector:
            count = action.get("count", 0)
            await page.wait_for_function(_MORE_LOADED_JS, arg=[card_selector, count], timeout=min(timeout, 5000))
        else:
            await page.wait_for_timeout(min(timeout, 2000))
    except Exception as e:  # noqa: BLE001 (the first page is enough)
        logger.info("No second page of results: %s", str(e).splitlines()[0] if str(e) else type(e).__name__)
        return []
    return await extract()


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
            image = first_url(obj.get("image"))
            products.append(
                Product(
                    store=store,
                    name=name,
                    brand=clean_text(brand) if isinstance(brand, str) else None,
                    price=price,
                    image_url=urljoin(base_url, image) if image else None,
                    product_url=urljoin(base_url, obj.get("url") or "") or base_url,
                    available=_available(offers),
                    ean=barcode_of(obj),
                    sku=identifier_of(obj),
                )
            )
    return products


def _available(offers: object) -> bool:
    """False when a JSON-LD offer says the product is out of stock."""
    availability = offers.get("availability") if isinstance(offers, dict) else None
    return not (isinstance(availability, str) and re.search(r"OutOfStock|SoldOut|Discontinued", availability))


async def extract_json_ld(page, store: str, base_url: str) -> list[Product]:
    return products_from_json_ld(await page.evaluate(JSON_LD_JS), store, base_url)


# --- Generic JSON (API responses) -------------------------------------------

_NAME_KEYS = ("name", "title", "fullTitle", "libelle", "label", "productName", "designation", "displayName")
_PRICE_KEYS = ("price", "prix", "currentPrice", "salePrice", "sellingPrice", "finalPrice")
_URL_KEYS = ("canonicalUrl", "url", "productUrl", "link", "href", "slug")
_IMAGE_KEYS = ("thumbnail", "image", "imageUrl", "images", "media", "picture")
# Barcode and identifier of a product in JSON-LD and in the APIs of the sites
_EAN_KEYS = ("ean", "ean13", "gtin", "gtin13", "gtin8", "gtin12", "barcode", "codeEan", "produitEan13", "ians")
_SKU_KEYS = ("sku", "productId", "productID", "product_id", "articleId", "articleNumber", "erpNumber", "idProduit")


def barcode_of(node: dict) -> str | None:
    """First valid EAN-8 / EAN-13 of a JSON object (keys ``ean``, ``gtin13``, ``barcode``...)."""
    for key in _EAN_KEYS:
        values = node.get(key)
        for value in values if isinstance(values, list) else [values]:
            ean = valid_ean(value.strip() if isinstance(value, str) else value)
            if ean:
                return ean
    return None


def identifier_of(node: dict) -> str | None:
    """Identifier of the product on the retailer site (``sku``, ``productId``...)."""
    for key in _SKU_KEYS:
        value = node.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
            return str(value).strip()
    return None


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


# Sizes of an image, the lightest first (thumbnails of 56 px, 112 px on a phone)
_IMAGE_SIZE_KEYS = ("medium", "small", "thumbnail", "thumb", "url", "src", "href", "main", "image", "large")


def first_url(value: Any) -> str | None:
    """The first image address of ``value``, the medium or small size when there are several."""
    if isinstance(value, str):
        return value or None
    if isinstance(value, list):
        for item in value:
            url = first_url(item)
            if url:
                return url
    if isinstance(value, dict):
        for key in _IMAGE_SIZE_KEYS:
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
                        ean=barcode_of(node),
                        sku=identifier_of(node),
                    )
                )
            return
        for value in node.values():
            visit(value, depth + 1)

    visit(data, 0)
    return products
