"""Courses U: search page of the chosen store, and the national directory of stores (area of P4).

Prices depend on the store: visiting its page (``https://www.coursesu.com/drive-superu-roujan``)
sets the store cookies, then ``/recherche?q=`` shows its prices. The page is
visited again when the browser context changes or after ``REVISIT_SECONDS``.

The stores come from the national directory ``/drive-france`` (about 1,100
drives), read from inside the Courses U tab (``fetch_store_directory``):

1. ``fetch('/drive-france')`` in the page; a challenge page makes it load as a
   real page instead (and ``BlockedError`` when the check does not pass);
2. ``parse_store_directory(html)`` (one block per store); when it finds fewer
   than ``MIN_DIRECTORY_STORES``, the link-based reader (``_DIRECTORY_LINKS_JS`` +
   ``cards_to_stores``) is tried and the HTML is saved in
   ``data/debug/coursesu-stores.html``;
3. nothing at all: the page of the department (``/drive-herault``).

The markup of the directory was not seen live (research of 2026, mcp-superU):
the fixtures of tests/fixtures/coursesu.py are synthetic.
"""

import html as html_lib
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote

from backend import config
from backend.browser import browser
from backend.models import Product, StoreOption, StoreSelection
from backend.scrapers.base import BaseScraper, BlockedError, StoreRequiredError
from backend.scrapers.common import (
    accept_cookies,
    ensure_origin,
    page_fetch,
    save_debug_snapshot,
    wait_for_clearance,
)
from backend.scrapers.extract import extract_cards, extract_json_ld

logger = logging.getLogger("prixmalin.coursesu")

BASE_URL = "https://www.coursesu.com"
SEARCH_URL = BASE_URL + "/recherche?q={query}"
DIRECTORY_URL = BASE_URL + "/drive-france"

# The store page is visited again after this time (the site forgets the store)
REVISIT_SECONDS = 20 * 60
# Fewer stores than this in /drive-france: the reader is probably outdated
MIN_DIRECTORY_STORES = 50
# Directory page kept when it gave few stores (data/debug/coursesu-stores.html)
DIRECTORY_SNAPSHOT = "coursesu-stores.html"

STORE_GONE = "Ce magasin n'existe plus sur Courses U, choisissez-en un autre."
DIRECTORY_BLOCKED = (
    "Courses U bloque la recherche : cliquez sur « Ouvrir le site », validez la vérification, puis réessayez."
)

TILE_OPTIONS = {
    "cardSelector": "[data-pid], .product-tile, .product-item",
    "nameSelector": ".product-tile__name, .product-name, .pdp-link a, .tile-body a, [itemprop='name']",
    "priceSelector": ".sales .value, [itemprop='price'], .product-price, .price-sales, [class*='price__value' i]",
    "unitSelector": (
        "[class*='unit-price' i], [class*='price-per' i], [class*='unitPrice' i], [class*='pricePerUnit' i]"
    ),
    "brandSelector": ".product-brand, [class*='brand' i]",
}

_STORE_URL = re.compile(r"^https://www\.coursesu\.com/[\w-]+/?$")

# Banners of the drive pages: /drive-superu-roujan, /drive-uexpress-lyon3bonnel...
# (not /drive-herault, /drive-dept-paris, /drive-pieton-paris: lists of stores)
BANNERS = ("superu", "hyperu", "uexpress", "marcheu", "marcheru", "marketu", "utile", "u")
_BANNER = "(?:" + "|".join(BANNERS) + ")"
_STORE_LINK = re.compile(
    r"""href=["'](?:https?://www\.coursesu\.com)?/drive-(""" + _BANNER + r"""-[\w-]+?)/?["']""", re.I
)
_STORE_PATH = re.compile(r"^(?:https?://www\.coursesu\.com)?/drive-(" + _BANNER + r"-[\w-]+?)/?$", re.I)
_ADDRESS = re.compile(r"<(\w+)[^>]*class=[\"'][^\"']*\bstores-text-address\b[^\"']*[\"'][^>]*>(.*?)</\1>", re.I | re.S)
_POSTAL_TOWN = re.compile(r"\b(\d{5})\s+([^,\d][^,]*)$")
_POSTAL = re.compile(r"\b\d{5}\b")
_TAG = re.compile(r"<[^>]+>")
_SERVICES = (("Drive", r"\bdrive\b"), ("Livraison", r"\blivraison\b"), ("Retrait", r"\bretrait\b"))

# Pages of anti-robot checks (Cloudflare, DataDome)
_CHALLENGE_MARKERS = ("captcha-delivery.com", "cf-chl", "challenge-platform")


def store_name_from_url(url: str) -> str:
    """'https://www.coursesu.com/drive-superu-roujan' -> 'Super U Roujan'."""
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"^(drive|magasin|livraison)-", "", slug)
    banners = {
        "superu": "Super U",
        "hyperu": "Hyper U",
        "uexpress": "U Express",
        "marcheu": "Marché U",
        "marcheru": "Marché U",
        "marketu": "Market U",
        "utile": "Utile",
    }
    words = slug.split("-")
    first = banners.get(words[0], words[0].capitalize()) if words else ""
    return " ".join([first] + [w.capitalize() for w in words[1:]]).strip()


def is_store_url(url: str) -> bool:
    return bool(_STORE_URL.match(url.strip()))


def store_url_from_href(href: str) -> str | None:
    """Canonical page of a store from a link of the site, or None for another page."""
    match = _STORE_PATH.match((href or "").strip())
    return f"{BASE_URL}/drive-{match.group(1).lower()}" if match else None


# ---------------------------------------------------------------- directory: pure parsing


def _clean_text(fragment: str) -> str:
    """Text of an HTML fragment: <br> become « , », tags removed, entities decoded."""
    text = re.sub(r"<br\s*/?>", ", ", fragment, flags=re.I)
    text = html_lib.unescape(_TAG.sub(" ", text))
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*,\s*(,\s*)*", ", ", text)
    return text.strip(" ,")


def _first(pattern: str, text: str, flags: int = re.I | re.S) -> str | None:
    match = re.search(pattern, text, flags)
    return match.group(1) if match else None


def _postal_town(address: str | None) -> tuple[str | None, str | None]:
    match = _POSTAL_TOWN.search(address or "")
    return (match.group(1), match.group(2).strip()) if match else (None, None)


def _services(text: str) -> list[str]:
    return [label for label, pattern in _SERVICES if re.search(pattern, text, re.I)]


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _dedupe(stores: list[StoreOption]) -> list[StoreOption]:
    seen: set[str] = set()
    unique = []
    for store in stores:
        key = store.id or store.url or ""
        if key in seen or (store.url and store.url in seen):
            continue
        seen.update(k for k in (store.id, store.url) if k)
        unique.append(store)
    return unique


def parse_store_directory(html: str) -> list[StoreOption]:
    """Stores of a directory page (/drive-france, /drive-herault...), one block per store.

    A block starts with the element carrying ``data-wrapper-store-details``;
    entries without a link to a store page are skipped, duplicates removed.
    """
    html = html or ""
    starts = []
    for marker in re.finditer(r"data-wrapper-store-details", html):
        tag_start = html.rfind("<", 0, marker.start())
        starts.append(tag_start if tag_start >= 0 else marker.start())
    stores = []
    for start, end in zip(starts, [*starts[1:], len(html)], strict=False):
        block = html[start:end]
        link = _STORE_LINK.search(block)
        if not link:
            continue
        url = f"{BASE_URL}/drive-{link.group(1).lower()}"
        name = (
            _first(r"data-store-name[^>]*>\s*([^<]+?)\s*<", block)
            or _first(r'data-store-name="([^"]+)"', block)
            or _first(r"data-store-name='([^']+)'", block)
        )
        name = html_lib.unescape(name).strip() if name else store_name_from_url(url)
        address_match = _ADDRESS.search(block)
        address = _clean_text(address_match.group(2)) if address_match else None
        postal_code, city = _postal_town(address)
        stores.append(
            StoreOption(
                id=_first(r"""data-store-id=["']?(\d+)""", block) or "",
                name=name,
                address=address or None,
                url=url,
                services=_services(_clean_text(block)),
                postal_code=postal_code,
                city=city,
                lat=_float(_first(r"""data-(?:store-)?lat(?:itude)?=["']?(-?\d+(?:\.\d+)?)""", block)),
                lon=_float(_first(r"""data-(?:store-)?(?:lng|lon|longitude)=["']?(-?\d+(?:\.\d+)?)""", block)),
            )
        )
    return _dedupe(stores)


def cards_to_stores(cards: list[dict]) -> list[StoreOption]:
    """Stores of the link-based reader: ``[{href, text, id}]`` collected by _DIRECTORY_LINKS_JS.

    The address is the line holding the postal code (with the line before it
    when it starts with the postal code); the name comes from the address of
    the page of the store.
    """
    stores = []
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        url = store_url_from_href(str(card.get("href") or ""))
        if not url:
            continue
        text = str(card.get("text") or "")[:300]
        lines = [re.sub(r"\s+", " ", line).strip(" ,") for line in text.splitlines()]
        lines = [line for line in lines if line]
        address = None
        for i, line in enumerate(lines):
            if _POSTAL.search(line):
                before = lines[i - 1] if i and re.match(r"^\d{5}\b", line) else None
                address = f"{before}, {line}" if before else line
                break
        postal_code, city = _postal_town(address)
        store_id = str(card.get("id") or "")
        stores.append(
            StoreOption(
                id=store_id if store_id.isdigit() else "",
                name=store_name_from_url(url),
                address=address,
                url=url,
                services=_services(text),
                postal_code=postal_code,
                city=city,
            )
        )
    return _dedupe(stores)


def is_challenge_response(status: int, text: str) -> bool:
    """The answer of a fetch() is an anti-robot check, not the directory.

    Cloudflare also adds its scripts to normal pages: the markers only count
    when the page holds no store.
    """
    if status in (403, 429, 503):
        return True
    has_marker = any(marker in (text or "") for marker in _CHALLENGE_MARKERS)
    return has_marker and "data-wrapper-store-details" not in text and not _STORE_LINK.search(text or "")


def department_slug(name: str) -> str:
    """'Côtes-d'Armor' -> 'cotes-darmor' (/drive-cotes-darmor); Paris -> 'dept-paris'."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"['’]", "", text)
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return "dept-paris" if slug == "paris" else slug


def site_store_selection(info: dict | None, directory: list[StoreOption] | None = None) -> StoreSelection | None:
    """Store chosen on the site, from what ``_SITE_STORE_JS`` read in its pages, or None.

    ``info``: ``{link, id, name}`` (``window.storeLink``, store id of the page
    or of the ``storeId`` cookie). Without a link, the id is looked up in the
    ``directory`` (the stores read in /drive-france).
    """
    if not isinstance(info, dict):
        return None
    store_id = str(info.get("id") or "").strip()
    store_id = store_id if store_id.isascii() and store_id.isdigit() and 2 <= len(store_id) <= 8 else None
    url = store_url_from_href(str(info.get("link") or ""))
    if url and is_store_url(url):
        return StoreSelection(id=store_id, name=store_name_from_url(url), url=url)
    if store_id:
        for option in directory or []:
            if option.id == store_id and option.url:
                return StoreSelection(id=store_id, name=option.name, url=option.url, address=option.address)
    return None


@dataclass
class StoreVisit:
    url: str
    generation: int
    at: float


def needs_store_visit(visit: StoreVisit | None, url: str, generation: int, now: float) -> bool:
    """The store page must be visited (again) before searching."""
    return visit is None or visit.url != url or visit.generation != generation or now - visit.at > REVISIT_SECONDS


# ---------------------------------------------------------------- JS run in the page (collect only)

# Store links of a directory page and the text around each of them: climb from
# the link while the parent holds no other store, stop at the first element
# whose text holds a postal code
_DIRECTORY_LINKS_JS = r"""
(html) => {
  const pattern = /^\/drive-(?:superu|hyperu|uexpress|marcheu|marcheru|marketu|utile|u)-[\w-]+?\/?$/i;
  const base = "https://www.coursesu.com";
  const pathOf = (a) => {
    try { return new URL(a.getAttribute("href") || "", base).pathname.replace(/\/$/, ""); }
    catch (e) { return ""; }
  };
  const storePaths = (el) => new Set([...el.querySelectorAll('a[href*="/drive-"]')]
    .map(pathOf).filter((p) => pattern.test(p)));
  const lines = (el) => {
    const out = [];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const t = walker.currentNode.textContent.replace(/\s+/g, " ").trim();
      if (t) out.push(t);
    }
    return out.join("\n").slice(0, 300);
  };
  const doc = new DOMParser().parseFromString(html, "text/html");
  const cards = [];
  for (const a of doc.querySelectorAll('a[href*="/drive-"]')) {
    if (!pattern.test(pathOf(a))) continue;
    let box = a;
    while (box.parentElement && storePaths(box.parentElement).size <= 1) {
      box = box.parentElement;
      if (/\b\d{5}\b/.test(box.textContent || "")) break;
    }
    const holder = a.closest("[data-store-id]") || box.querySelector("[data-store-id]");
    const id = holder ? holder.getAttribute("data-store-id") : null;
    cards.push({href: a.getAttribute("href"), text: lines(box), id});
  }
  return cards;
}
"""

# Store chosen on the site, from the globals of its pages (Nov 2025 capture)
_SITE_STORE_JS = r"""
() => {
  const pick = (...values) => values.find((v) => v !== undefined && v !== null && v !== "") ?? null;
  const dl = window.dataLayerNC || {};
  const tc = window.tc_vars || {};
  const user = window.User || {};
  const cookie = (document.cookie.match(/(?:^|;\s*)storeId=([^;]+)/) || [])[1];
  return {
    link: typeof window.storeLink === "string" ? window.storeLink : null,
    id: pick(dl.store_id, tc.store_id, user.storeId, cookie),
    name: pick(dl.store_name, tc.store_name),
  };
}
"""


class CoursesUScraper(BaseScraper):
    key = "coursesu"
    label = "Courses U"
    home_url = BASE_URL + "/"
    needs_store = True
    store_hint = (
        "Les prix ne s'affichent qu'une fois un magasin choisi. PrixMalin choisit le plus proche "
        "de votre code postal ; vous pouvez en prendre un autre dans la liste, sur le site "
        "(« Ouvrir le site ») ou en collant l'adresse de sa page."
    )

    def __init__(self) -> None:
        # Store page visited last (it sets the store cookies): url, browser context, time
        self._visit: StoreVisit | None = None

    # ------------------------------------------------------------ search

    async def search(self, page, query: str, store: StoreSelection | None) -> list[Product]:
        self.last_source = None
        if store and store.url:
            await self._visit_store(page, store)
        products = await self._read_results(page, query)
        if store and store.url and products and all(p.price is None for p in products):
            # The site forgot the store: visit its page again and search once more
            logger.info("Courses U: no price for '%s', visiting the store page again", query)
            self._visit = None
            await self._visit_store(page, store)
            products = await self._read_results(page, query)
        if not products:
            await save_debug_snapshot(page, self.key)
        return products

    async def _visit_store(self, page, store: StoreSelection) -> None:
        if not needs_store_visit(self._visit, store.url, browser.context_generation, time.monotonic()):
            return
        response = await page.goto(store.url, wait_until="domcontentloaded", timeout=30000)
        if response is not None and response.status == 404:
            self._visit = None
            raise StoreRequiredError(STORE_GONE)
        await wait_for_clearance(page, self.label)
        await accept_cookies(page)
        self._visit = StoreVisit(store.url, browser.context_generation, time.monotonic())
        await self._check_store(page, store)

    async def _check_store(self, page, store: StoreSelection) -> None:
        """Log (never fail) when the page shows another store than the one chosen."""
        try:
            shown = await page.evaluate(_SITE_STORE_JS)
        except Exception as e:  # noqa: BLE001 (a check only)
            logger.debug("Courses U store check: %s", e)
            return
        shown_url = store_url_from_href(str((shown or {}).get("link") or ""))
        shown_id = str((shown or {}).get("id") or "")
        if (store.id and shown_id and shown_id != store.id) or (shown_url and shown_url != store.url.rstrip("/")):
            logger.warning("Courses U shows the store %s (%s) instead of %s", shown_id, shown_url, store.url)

    async def _read_results(self, page, query: str) -> list[Product]:
        await page.goto(SEARCH_URL.format(query=quote(query)), wait_until="domcontentloaded", timeout=30000)
        await wait_for_clearance(page, self.label)
        await accept_cookies(page)
        try:
            await page.wait_for_selector(
                "[data-pid], .product-tile, .product-item, [class*='no-result' i], [class*='noresult' i]",
                timeout=12000,
            )
        except Exception:  # noqa: BLE001 (timeout: the page is read anyway)
            logger.info("Courses U: no product tile for '%s'", query)
        await page.wait_for_timeout(500)

        products = self.found(await extract_cards(page, self.key, BASE_URL, **TILE_OPTIONS), "html")
        if not products:
            cards = await extract_cards(page, self.key, BASE_URL, linkPattern=r"/p/|\.html")
            products = self.found(cards, "generic")
        if not products:
            products = self.found(await extract_json_ld(page, self.key, BASE_URL), "json-ld")
        return products

    # ------------------------------------------------------------ stores

    async def fetch_store_directory(self, page, department_name: str | None = None) -> dict:
        """Every Courses U store: ``{"stores": [StoreOption...], "method": ...}``.

        ``method``: "blocs" (parse_store_directory), "liens" (link-based reader)
        or "département" (page of ``department_name``). Raises BlockedError when
        the anti-robot check does not pass.
        """
        try:
            await ensure_origin(page, self.home_url, self.label)
        except BlockedError as e:
            if type(e) is not BlockedError:  # another kind of block keeps its message
                raise
            raise BlockedError(DIRECTORY_BLOCKED) from e
        stores, method = await self._read_directory(page, DIRECTORY_URL)
        if not stores and department_name:
            stores, _ = await self._read_directory(page, f"{BASE_URL}/drive-{department_slug(department_name)}")
            method = "département"
        logger.info("Courses U : %d magasins (méthode=%s)", len(stores), method)
        return {"stores": stores, "method": method}

    async def _read_directory(self, page, url: str) -> tuple[list[StoreOption], str]:
        html = await self._directory_html(page, url)
        stores, method = parse_store_directory(html), "blocs"
        if len(stores) < MIN_DIRECTORY_STORES:
            try:
                cards = await page.evaluate(_DIRECTORY_LINKS_JS, html)
            except Exception as e:  # noqa: BLE001 (fallback reader only)
                logger.info("Courses U: link-based reader failed: %s", e)
                cards = []
            by_links = cards_to_stores(cards)
            if len(by_links) > len(stores):
                stores, method = by_links, "liens"
            self._save_directory(html)
        return stores, method

    async def _directory_html(self, page, url: str) -> str:
        result = await page_fetch(page, url, headers={"accept": "text/html"}, timeout_ms=30000)
        if result.ok and not is_challenge_response(result.status, result.text):
            return result.text
        if result.status == 404:
            return ""
        # Anti-robot check (or fetch refused): load the page itself and let the check pass
        logger.info("Courses U: %s answered %s to fetch(), loading the page", url, result.status)
        self._visit = None  # the tab leaves the store page: visit it again before searching
        response = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        try:
            await wait_for_clearance(page, self.label)
        except BlockedError as e:
            if type(e) is not BlockedError:  # another kind of block keeps its message
                raise
            raise BlockedError(DIRECTORY_BLOCKED) from e
        if response is not None and response.status == 404:
            return ""
        await accept_cookies(page)
        return await page.content()

    def _save_directory(self, html: str) -> None:
        """Keep the directory page that gave few stores, to fix the reader."""
        try:
            path = config.DEBUG_DIR / DIRECTORY_SNAPSHOT
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html or "", encoding="utf-8")
            logger.info("Courses U: directory page saved in %s", path)
        except OSError as e:
            logger.debug("Courses U directory snapshot: %s", e)

    async def read_site_store(self, page) -> dict | None:
        """What the pages of the site say about the store chosen there (``_SITE_STORE_JS``).

        Read after « Ouvrir le site » + « J'ai terminé »; ``site_store_selection``
        turns it into a store.
        """
        await ensure_origin(page, self.home_url, self.label)
        return await page.evaluate(_SITE_STORE_JS)
