"""E.Leclerc Drive: the search page of the chosen drive, read in a dedicated Chrome window (area of P8).

The site (ASP.NET, fdN-courses.leclercdrive.fr) is protected by DataDome: like
Intermarché it is only opened in the dedicated real Chrome window of
backend/real_chrome.py (profile data/chrome-leclerc), never in the shared
browser. No cookie banner clicked by script, no captcha solved, a refusal of
the site (hard block) never retried.

**Search** (``LeclercScraper.search``):

1. the page of the drive (``{base}.aspx``) is visited (a navigation: it ties the
   session to the drive) when needed: first search, other drive, tab
   elsewhere, or after ``REVISIT_SECONDS`` (``needs_store_visit``); the address
   the site ends on is kept (``fd1-courses`` → ``fd10-courses``);
2. ``fetch()`` in the page, same origin, of
   ``{base}/recherche.aspx?TexteRecherche={q}`` (``search_url``): HTML made by
   the server;
3. the products are the JSON of the widget
   ``Utilitaires.widget.initOptions('…pnlElementProduit', {objContenu, objContenuMDD})``
   read by ``parse_search_html`` (pure). ``fetch`` refused (status 0,
   « Failed to fetch ») or « session expirée »: the drive is visited again and
   the search page loaded as a real page, once (its rendered tiles
   ``li.liWCRS310_Product`` are the last fallback). A ``fetch`` that took too
   long is a timeout, without a new visit; a page that is no page of the drive
   (error page of the site) is an error, never « Aucun produit ».

**Prices** (``element_to_product``, checked on real pages of 2025): ``nrPVUnitaireTTC``
is the price; an immediate discount (« BRII », ``neTypeLotBrii`` 0) lowers it
to ``nrPVBRIIDeduit`` (old price struck out, price per kg / L of the discount);
a mixed lot (« Le 2ème à -60 % », ``neTypeLotBrii`` 2) leaves it unchanged with
its text; « Recevez 20 % en Ticket E.Leclerc » (loyalty card) is no discount.

**Stores** (``find_stores``): the store finder of the site
(``api-recherchemagasins.leclercdrive.fr`` ``MapPoint/nearby``), called with
``fetch()`` from a leclercdrive.fr page of the dedicated window.
"""

import asyncio
import html as html_lib
import json
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlsplit

from backend import config
from backend.models import Product, StoreOption, StoreSelection
from backend.scrapers.base import BaseScraper, BlockedError, HardBlockError, ScraperError, StoreRequiredError
from backend.scrapers.common import (
    REFUSAL_STATUSES,
    classify_refusal,
    ensure_origin,
    hard_block_message,
    is_datadome_answer,
    page_fetch,
    refusal_record,
    refused_message,
    save_debug_text,
    wait_for_clearance,
)
from backend.scrapers.extract import products_from_json
from backend.scrapers.parsing import clean_text, parse_price, quantity_spans

logger = logging.getLogger("prixmalin.leclerc")

LABEL = "E.Leclerc"
PORTAL_URL = "https://www.leclercdrive.fr/"
LOCATOR_API = "https://api-recherchemagasins.leclercdrive.fr/API_RechercheMagasins/api/v1"
NEARBY_URL = LOCATOR_API + "/MapPoint/nearby?latitude={lat}&longitude={lon}&postalCode={cp}"
AUTOCOMPLETE_URL = LOCATOR_API + "/autocomplete?search={q}&provider=Woosmap"
COORDINATES_URL = LOCATOR_API + "/autocomplete/coordinates?id={id}&provider=Woosmap"
# Generic host of the drives: answers with a redirection to the right one
GENERIC_HOST = "fd1-courses.leclercdrive.fr"

# The search field of the site takes 40 characters at most
QUERY_MAX = 40
# The page of the drive is visited again after this time (the site sends an
# idle session elsewhere after about 16 minutes)
REVISIT_SECONDS = 15 * 60
# Time limit of the fetch() of a search page (the search has 60 s in all)
FETCH_TIMEOUT_MS = 30000
# Pause between two calls of the store finder
LOCATOR_PAUSE_SECONDS = 1.2
# Longest address accepted for a drive (as StoreChoice)
URL_MAX = 300

STORE_URL_EXAMPLE = "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges.aspx"
URL_HINT = f"Adresse invalide. Exemple : {STORE_URL_EXAMPLE}"
STORE_MISSING = "Choisissez votre drive E.Leclerc dans les réglages pour voir les prix."
STORE_GONE = "Ce drive n'existe plus sur E.Leclerc Drive : choisissez-en un autre."
OTHER_DRIVE = "E.Leclerc affiche un autre drive que celui choisi : choisissez de nouveau votre drive dans les réglages."
NOT_A_DRIVE = "E.Leclerc n'a pas affiché la page du drive. Réessayez plus tard."
SITE_ERROR = "E.Leclerc a renvoyé une erreur. Réessayez plus tard."
SEARCH_FAILED = "E.Leclerc n'a pas affiché la recherche. Réessayez dans un instant."
# A refusal (401, 403, 405) without any DataDome mark: nothing to validate in the window
REFUSED_MESSAGE = refused_message(LABEL)
CAPTCHA_MESSAGE = (
    "E.Leclerc demande une vérification : appuyez sur « Ouvrir le site », validez-la dans la "
    "fenêtre Chrome d'E.Leclerc ouverte par PrixMalin, puis appuyez sur « J'ai terminé »."
)
LOCATOR_FAILED = "La liste des drives E.Leclerc est indisponible pour le moment. Réessayez plus tard."

# Own brands of E.Leclerc (services/products.py STORE_BRANDS["leclerc"] is this
# list); « Jean's » is the cola of the « objContenuMDD » list of a real page
OWN_BRANDS = (
    "Marque Repère",
    "Eco+",
    "Bio Village",
    "Nos Régions ont du Talent",
    "NRT",
    "Les Croisés",
    "Notre Jardin",
    "Épi d'Or",
    "Ronde des Mers",
    "Turini",
    "Tables du Monde",
    "Jean's",
)

_COURSES_HOST = re.compile(r"^fd\d{1,2}-courses\.leclercdrive\.fr$")
_SEGMENT = re.compile(r"^magasin-(\d{6})(?:-(\d{6}))?(?:-[\w%.'’-]*)?$")
_WIDGET = re.compile(r"Utilitaires\.widget\.initOptions\(\s*'([^']+)'\s*,\s*")
_CAPTCHA_URL = re.compile(r"https?://[\w.-]*captcha-delivery\.com/captcha/?\?[^\"'\s<>]*", re.I)
# fetch() stopped by its own time limit (page_fetch: « AbortError: signal is aborted… »)
_ABORTED = re.compile(r"AbortError|aborted", re.I)
_SESSION = re.compile(r"session a expir|sessionexpiree|session expir[ée]e", re.I)
_LOT_END = re.compile(r"\s*,?\s*profitez[- ]en\s*!?\s*$", re.I)
_TICKET = re.compile(r"\bticket\b|\bcarte\b", re.I)
# Words of « Bouteille - 1,75L » or « La bouteille de 1.75L » that say nothing of the product
_PACKAGING = frozenset(
    "bouteille bouteilles pack packs brique briques boite boites bocal bocaux pot pots sachet sachets "
    "barquette barquettes paquet paquets canette canettes flacon flacons lot lots etui etuis carton "
    "cartons bidon bidons tube tubes filet sac poche la le les l de des du d en un une".split()
)
# Quantity units of nrContenanceTotale (sUniteMesureTotale)
_TOTAL_UNITS = {"kg": "kg", "l": "L"}


def _ascii(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c))


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+]+", _ascii(text).lower())


_OWN_BRAND_WORDS = {" ".join(_words(b)): b for b in OWN_BRANDS}


# ---------------------------------------------------------------- addresses of the drives


@dataclass(frozen=True)
class StoreRef:
    """A drive: ``https://fd12-courses.leclercdrive.fr`` + ``magasin-173301-173301-Bruges``."""

    origin: str
    segment: str
    no_pl: str
    no_pr: str | None = None

    @property
    def base(self) -> str:
        return f"{self.origin}/{self.segment}"


def parse_store_url(url: str | None) -> StoreRef | None:
    """The drive of an address copied from any page of it, or None (pure).

    ``https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges.aspx``,
    ``…/magasin-173301-173301-Bruges/recherche.aspx?TexteRecherche=riz``,
    ``…/magasin-010901-saint-jean-du-falga.aspx`` are accepted (« .aspx », the
    rest of the path, the query and the fragment are dropped); http, another
    domain, the catering or mobile sites, the regional pages of
    www.leclercdrive.fr are not.
    """
    text = (url or "").strip()
    if not text or len(text) > URL_MAX:
        return None
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() != "https" or port is not None or parts.netloc.lower() != host:
        return None
    if not _COURSES_HOST.match(host):
        return None
    first = parts.path.lstrip("/").split("/", 1)[0]
    if first.lower().endswith(".aspx"):
        first = first[:-5]
    first = first.rstrip(".")
    match = _SEGMENT.match(first)
    if not match:
        return None
    return StoreRef(origin=f"https://{host}", segment=first, no_pl=match.group(1), no_pr=match.group(2))


def store_name_of(ref: StoreRef, known: str | None = None) -> str:
    """« E.Leclerc Drive Bruges »: ``known`` (name given by the site), else from the address."""
    name = clean_text(known)
    if not name:
        rest = ref.segment[len(f"magasin-{ref.no_pl}") :]
        if ref.no_pr and rest.startswith(f"-{ref.no_pr}"):
            rest = rest[len(ref.no_pr) + 1 :]
        words = [w for w in re.split(r"[-_\s]+", unquote(rest)) if w]
        name = " ".join(w[:1].upper() + w[1:] for w in words) or f"n° {ref.no_pl}"
    return name if name.lower().startswith(("e.leclerc", "leclerc")) else f"E.Leclerc Drive {name}"


def search_url(base: str, query: str) -> str:
    """Search page of the drive ``base`` (40 characters at most, encoded like the site: %20)."""
    text = clean_text(query)[:QUERY_MAX].strip()
    return f"{base}/recherche.aspx?TexteRecherche={quote(text, safe='')}"


def slug_of(name: str | None) -> str:
    """'La Ville-aux-Dames' -> 'La-Ville-aux-Dames' (decorative part of the address of a drive)."""
    return re.sub(r"[^A-Za-z0-9]+", "-", _ascii(name or "")).strip("-")


def _digits6(value: object) -> str | None:
    text = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    if not text.isascii() or not text.isdigit() or len(text) > 6:
        return None
    return text.zfill(6)


def store_base_from_point(point: dict) -> str | None:
    """Address of the drive of a point of the store finder (pure).

    ``urlSiteCourse`` / ``urlBase`` may be the host alone, its root or the whole
    address of the drive; without them the generic host (which redirects) is used.
    """
    no_pl = _digits6(point.get("noPL"))
    if not no_pl:
        return None
    no_pr = _digits6(point.get("noPR")) or no_pl
    host = None
    for key in ("urlSiteCourse", "urlBase", "urlSiteCourses"):
        value = point.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        if "://" not in value:
            value = "https://" + value
        ref = parse_store_url(value)
        if ref and ref.no_pl == no_pl:
            return ref.base
        try:
            candidate = (urlsplit(value).hostname or "").lower()
        except ValueError:
            continue
        if _COURSES_HOST.match(candidate) and host is None:
            host = candidate
    slug = slug_of(point.get("name"))
    segment = f"magasin-{no_pl}-{no_pr}" + (f"-{slug}" if slug else "")
    return f"https://{host or GENERIC_HOST}/{segment}"


# ---------------------------------------------------------------- products: pure parsing


def page_widgets(text: str) -> dict[str, object]:
    """``{id: options}`` of every ``Utilitaires.widget.initOptions('<id>', {...})`` of a page."""
    decoder = json.JSONDecoder()
    widgets: dict[str, object] = {}
    for match in _WIDGET.finditer(text or ""):
        try:
            value, _ = decoder.raw_decode(text, match.end())
        except ValueError:
            continue
        widgets.setdefault(match.group(1), value)
    return widgets


def widget(widgets: dict[str, object], suffix: str) -> object | None:
    """The widget whose id ends with ``suffix`` (``pnlElementProduit``): the start of the id changes."""
    return next((value for wid, value in widgets.items() if wid.endswith(suffix)), None)


def _is_product(element: object) -> bool:
    if not isinstance(element, dict) or element.get("iIdProduit") in (None, ""):
        return False
    kind = element.get("sType")
    return not isinstance(kind, str) or not kind or kind.lower() == "produit"


def _container_elements(container: object) -> list[dict]:
    """``objElement`` of ``container.lstElements`` and the products of their ``lstEnfants``."""
    items = container.get("lstElements") if isinstance(container, dict) else None
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        out.append(item.get("objElement"))
        for child in item.get("lstEnfants") or []:
            if isinstance(child, dict):
                out.append(child.get("objElement") if isinstance(child.get("objElement"), dict) else child)
    return [e for e in out if _is_product(e)]


def product_elements(options: object) -> list[tuple[dict, bool]]:
    """``(objElement, own brand)`` of the widget ``pnlElementProduit``: ``objContenu``, then
    ``objContenuMDD`` (the own brands, a separate list), then ``objContenuGroupeVariantes``."""
    if not isinstance(options, dict):
        return []
    out = [(e, False) for e in _container_elements(options.get("objContenu"))]
    out += [(e, True) for e in _container_elements(options.get("objContenuMDD"))]
    out += [(e, False) for e in _container_elements(options.get("objContenuGroupeVariantes"))]
    return out


def _walk_containers(value: object, depth: int = 0):
    if depth > 8:
        return
    if isinstance(value, dict):
        if isinstance(value.get("lstElements"), list):
            yield value
        for nested in value.values():
            yield from _walk_containers(nested, depth + 1)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_containers(nested, depth + 1)


def _records(value: object, depth: int = 0):
    """The objects holding an ``iIdProduit`` key in a JSON value (the outermost ones)."""
    if depth > 12:
        return
    if isinstance(value, dict):
        if "iIdProduit" in value:
            yield value
            return
        for nested in value.values():
            yield from _records(nested, depth + 1)
    elif isinstance(value, list):
        for nested in value:
            yield from _records(nested, depth + 1)


def scan_product_records(text: str) -> list[dict]:
    """Every JSON object of ``text`` holding an ``iIdProduit`` key (the smallest one around it)."""
    decoder = json.JSONDecoder()
    records = []
    position = 0
    for match in re.finditer(r'"iIdProduit"\s*:', text or ""):
        if match.start() < position:
            continue
        start, depth = match.start(), 0
        found = None
        for _ in range(4):  # the object around, else the one around it
            i = start - 1
            while i >= 0:
                c = text[i]
                if c == "}":
                    depth += 1
                elif c == "{":
                    if depth == 0:
                        break
                    depth -= 1
                i -= 1
            if i < 0:
                break
            try:
                value, end = decoder.raw_decode(text, i)
            except ValueError:
                start, depth = i, 0
                continue
            if isinstance(value, dict) and "iIdProduit" in value:
                found = (value, end)
            break
        if found:
            records.append(found[0])
            position = found[1]
    return records


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2) if value > 0 else None
    return parse_price(value) if isinstance(value, str) else None


def _text(value: object) -> str:
    return clean_text(html_lib.unescape(value)) if isinstance(value, str) else ""


def _decimal(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def _own_brand(text: str) -> str | None:
    return _OWN_BRAND_WORDS.get(" ".join(_words(text)))


def split_line2(text: str) -> tuple[str | None, str | None, str]:
    """``(quantity, own brand, words for the name)`` of the 2nd line of a product (pure).

    « Bouteille - 1,75L » → (« 1,75L », None, ""); « Bio Village - 1kg » →
    (« 1kg », « Bio Village », ""); « L'original Bio - 500g » → (« 500g », None,
    « L'original Bio »). Packaging words (bouteille, pack, lot…) are dropped.
    Every quantity of the line is kept, as the site shows them: « x8 - 320g »
    (``parsing.parse_pack`` reads the weight first: 320 g, not 8 pieces).
    """
    brand = None
    quantities: list[str] = []
    rest: list[str] = []
    for piece in re.split(r"\s+-\s+|\s+-$|^-\s+", _text(text)):
        piece = piece.strip(" -")
        if not piece:
            continue
        spans = quantity_spans(piece)
        if spans:
            for start, end in spans:
                found = piece[start:end].strip()
                if found and found not in quantities:
                    quantities.append(found)
            for start, end in reversed(spans):
                piece = piece[:start] + " " + piece[end:]
            piece = clean_text(piece)
            if all(w in _PACKAGING for w in _words(piece)):
                continue
        elif all(w in _PACKAGING for w in _words(piece)):
            continue
        own = _own_brand(piece)
        if own and brand is None:
            brand = own  # « Bio village » → « Bio Village »
            continue
        rest.append(piece)
    return " - ".join(quantities) or None, brand, " ".join(rest)


def _total_quantity(element: dict) -> str | None:
    """« 1,5 kg », « 500 g », « 1,75 L » from ``nrContenanceTotale`` and ``sUniteMesureTotale``."""
    total = element.get("nrContenanceTotale")
    unit = _TOTAL_UNITS.get(str(element.get("sUniteMesureTotale") or "").lower())
    if not unit or isinstance(total, bool) or not isinstance(total, (int, float)) or total <= 0:
        return None
    if unit == "kg" and total < 1:
        return f"{_decimal(total * 1000)} g"
    return f"{_decimal(total)} {unit}"


def _unit_label(value: object, unit_total: object) -> str | None:
    number = _number(value)
    unit = str(unit_total or "").lower()
    if number is None or unit not in _TOTAL_UNITS:
        return None
    return f"{number:.2f} € / {unit}".replace(".", ",")


def _product_url(value: object, base: str) -> str:
    text = value.strip() if isinstance(value, str) else ""
    try:
        parts = urlsplit(text)
    except ValueError:
        return base
    if parts.scheme == "https" and _COURSES_HOST.match((parts.hostname or "").lower()):
        return text
    return base


def element_to_product(element: dict, base: str, own_brand: bool = False) -> Product | None:
    """Product of an ``objElement`` of the search page (pure; rules of the module docstring)."""
    if not _is_product(element):
        return None
    line1 = _text(element.get("sLibelleLigne1")).rstrip(" -")
    quantity, brand, extra = split_line2(element.get("sLibelleLigne2") or "")
    name = clean_text(f"{line1} {extra}")
    if not name:
        return None
    brand = _text(element.get("sLibelleMarque")) or brand

    price = _number(element.get("nrPVUnitaireTTC")) or parse_price(element.get("sPrixUnitaire"))
    discounted = _number(element.get("nrPVBRIIDeduit")) or parse_price(element.get("sPrixPromo"))
    lot_type = element.get("neTypeLotBrii") or 0
    incentive = element.get("eIncitationLot") or 0
    tooltip = _text(element.get("sTexteTooltipLot"))
    immediate = (
        lot_type == 0
        and element.get("fEstBRIIActifEtDisponible") is not False
        and price is not None
        and discounted is not None
        and 0 < discounted < price
    )
    old_price = promo = None
    unit_label = _text(element.get("sPrixParUniteDeMesure")) or _unit_label(
        element.get("nrPVParUniteDeMesureTTC"), element.get("sUniteMesureTotale")
    )
    if immediate:
        old_price, price = price, discounted
        unit_label = _text(element.get("sPrixPromoParUniteDeMesure")) or _unit_label(
            element.get("nrPVMesureBRIIDeduit"), element.get("sUniteMesureTotale")
        )
        promo = tooltip if tooltip and not _TICKET.search(tooltip) else None
        promo = promo or f"Au lieu de {old_price:.2f} €".replace(".", ",")
    elif (lot_type or incentive) and tooltip and not _TICKET.search(tooltip):
        promo = _LOT_END.sub("", tooltip) or None

    stock = element.get("iQteDisponible")
    available = (
        element.get("eDisponibilite") in (0, None)
        and not (isinstance(stock, (int, float)) and not isinstance(stock, bool) and stock <= 0)
        and element.get("fProduitEpuise") is not True
    )
    image = element.get("sUrlVignetteProduit")
    ean = str(element.get("sCodeEAN") or "").strip() or None
    return Product(
        store="leclerc",
        name=name,
        brand=brand or None,
        price=price,
        old_price=old_price,
        unit_price_label=unit_label or None,
        quantity_label=quantity or _total_quantity(element),
        image_url=image if isinstance(image, str) else None,
        product_url=_product_url(element.get("sUrlPageProduit"), base),
        promo=promo,
        available=available,
        ean=ean,
        sku=str(element["iIdProduit"]).strip() or None,
        store_brand=True if own_brand else None,
    )


@dataclass
class LeclercPage:
    """What a page of the site gave (``parse_search_html``)."""

    products: list[Product] = field(default_factory=list)
    # « api » (JSON of the site), « generic » (backend/scrapers/extract.py) or None
    source: str | None = None
    # Products the site counts (pnlBlocsFiltres.iNbTotalProduits) and read here
    total: int | None = None
    listed: int = 0
    # A page of a drive (its banner, its cart or its products are there)
    store_page: bool = False
    # Drive shown by the banner of the page (BandeauMultiUnivers)
    store_no: str | None = None
    store_url: str | None = None
    store_name: str | None = None

    @property
    def truncated(self) -> bool:
        return self.total is not None and self.total > self.listed


def _products(elements: list[tuple[dict, bool]], base: str) -> list[Product]:
    seen: set[str] = set()
    products = []
    for element, own in elements:
        key = str(element.get("iIdProduit"))
        if key in seen:
            continue
        seen.add(key)
        product = element_to_product(element, base, own)
        if product is not None:
            products.append(product)
    return products


# Widgets that list other things than the results (carousels of the home page, cart, stock)
_NOT_RESULTS = re.compile(r"Carrousel|Panier|GestionStock|Upselling|Popin", re.I)


def parse_search_html(text: str, base: str, *, search_page: bool = True) -> LeclercPage:
    """Products of a page of a drive (pure).

    1. the widget ``…pnlElementProduit`` (``product_elements``); then, on a
       search page only (``search_page``):
    2. any widget listing ``objElement`` with an ``iIdProduit`` (its id changed),
       then any object of a widget holding ``iIdProduit`` (any JSON object of
       the page, ``scan_product_records``, when there is no widget at all);
    3. ``extract.products_from_json`` on the widgets (source « generic »).

    The widgets of carousels, cart and pop-ups (``_NOT_RESULTS``) never give results.
    """
    text = text or ""
    widgets = page_widgets(text)
    page = LeclercPage()
    banner = widget(widgets, "BandeauMultiUnivers")
    if isinstance(banner, dict):
        page.store_no = _digits6(banner.get("sNoPointLivraison"))
        page.store_url = banner.get("urlCourses") if isinstance(banner.get("urlCourses"), str) else None
        page.store_name = _text(banner.get("nomPL")) or None
    filters = widget(widgets, "pnlBlocsFiltres")
    if isinstance(filters, dict) and isinstance(filters.get("iNbTotalProduits"), int):
        page.total = filters["iNbTotalProduits"]
    results = widget(widgets, "pnlElementProduit")
    page.store_page = banner is not None or results is not None or "lstProduitsLight" in text

    elements = product_elements(results)
    # Widgets that may hold the results (not the carousels, the cart...)
    others = {wid: value for wid, value in widgets.items() if not _NOT_RESULTS.search(wid)}
    if not elements and search_page and results is None:
        for value in others.values():
            for container in _walk_containers(value):
                elements += [(e, False) for e in _container_elements(container)]
        if not elements:
            if widgets:
                records = [r for value in others.values() for r in _records(value)]
            else:
                records = scan_product_records(text)
            elements = [(e, False) for e in records if _is_product(e)]
    # The own brands are a list of their own, not counted by iNbTotalProduits
    page.listed = len({str(e.get("iIdProduit")) for e, own in elements if not own})
    page.products = _products(elements, base)
    if page.products:
        page.source = "api"
    elif search_page and results is None:
        found: list[Product] = []
        for value in others.values():
            found += products_from_json(value, "leclerc", base)
        page.products = found
        page.source = "generic" if found else None
    return page


# ---------------------------------------------------------------- tiles of the page (last fallback)

# Collect only: the rendered tiles of a search page loaded as a page
_TILES_JS = r"""
() => [...document.querySelectorAll('li.liWCRS310_Product')].map((li) => {
  const text = (sel) => { const el = li.querySelector(sel); return el ? el.innerText || el.textContent || '' : ''; };
  const name = li.querySelector('.aWCRS310_Product');
  const img = li.querySelector('img[src*="image.ashx"]');
  return {
    name: name ? (name.innerText || name.textContent || '') : '',
    whole: text('.pWCRS310_PrixUnitairePartieEntiere'),
    cents: text('.pWCRS310_PrixUnitairePartieDecimale'),
    unit: text('.pWCRS310_PrixUniteMesure'),
    unavailable: li.classList.contains('liWCRS310_Unavailable') || li.dataset.vignette === 'bientotDisponible',
    image: img ? img.src : null,
  };
})
"""

_UNIT_IN_TILE = re.compile(r"(\d+(?:[.,]\d{1,2})?)\s*€\s*/\s*(kg|l|litre|p|pièce)\b", re.I)
_OLD_IN_TILE = re.compile(r"au lieu de\s*(\d+(?:[.,]\d{1,2})?)\s*€", re.I)


def tiles_to_products(tiles: list[dict], base: str) -> list[Product]:
    """Products of the rendered tiles collected by ``_TILES_JS`` (pure)."""
    products = []
    for tile in tiles or []:
        if not isinstance(tile, dict):
            continue
        lines = [clean_text(line) for line in str(tile.get("name") or "").splitlines()]
        lines = [line for line in lines if line]
        if not lines:
            continue
        quantity, brand, extra = split_line2(" - ".join(lines[1:]))
        name = clean_text(f"{lines[0].rstrip(' -')} {extra}")
        whole = re.sub(r"\D", "", str(tile.get("whole") or ""))
        cents = re.sub(r"\D", "", str(tile.get("cents") or ""))
        price = parse_price(f"{whole},{cents or '00'}") if whole else None
        unit_text = clean_text(str(tile.get("unit") or "").replace("\xa0", " "))
        units = _UNIT_IN_TILE.findall(unit_text)
        unit_label = f"{units[-1][0]} € / {units[-1][1].lower()}" if units else None
        old = _OLD_IN_TILE.search(unit_text)
        old_price = parse_price(old.group(1)) if old else None
        if not (old_price and price and old_price > price):
            old_price = None
        image = tile.get("image")
        products.append(
            Product(
                store="leclerc",
                name=name,
                brand=brand,
                price=price,
                old_price=old_price,
                promo=f"Au lieu de {old_price:.2f} €".replace(".", ",") if old_price else None,
                unit_price_label=unit_label,
                quantity_label=quantity,
                image_url=image if isinstance(image, str) else None,
                product_url=base,
                available=not tile.get("unavailable"),
            )
        )
    return products


# ---------------------------------------------------------------- answers of the site


def captcha_url(text: str) -> str | None:
    """Address of the DataDome captcha of a page (iframe or script), ``&amp;`` decoded."""
    match = _CAPTCHA_URL.search(text or "")
    return html_lib.unescape(match.group(0)) if match else None


def is_portal(url: str | None) -> bool:
    """The address is the national portal (www.leclercdrive.fr), not a drive."""
    try:
        host = (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return False
    return host in ("www.leclercdrive.fr", "leclercdrive.fr")


def classify_answer(status: int, final_url: str | None, text: str | None) -> str:
    """What an answer of the site means (pure).

    ``"ok"`` (an answer of the site, 2xx), ``"retry"`` (fetch refused, status 0
    « Failed to fetch », or session expired: visit the drive again and load the
    page), ``"timeout"`` (fetch stopped by its time limit), ``"portal"`` (sent
    back to www.leclercdrive.fr: the drive is closed), ``"captcha"`` (DataDome
    check to validate in the window), ``"hard_block"`` (refused for a while:
    « Access blocked », « Accès temporairement restreint », ``t=bv``, HTTP
    429), ``"refused"`` (401, 403, 405 without any DataDome mark: nothing to
    validate) or ``"error"``.
    """
    text = text or ""
    head = text[:60000]
    if status == 429:
        return "hard_block"
    if status == 0:
        return "timeout" if _ABORTED.search(text[:300]) else "retry"
    drive = "pnlElementProduit" in text or "lstProduitsLight" in text or "BandeauMultiUnivers" in text
    if status in REFUSAL_STATUSES or (not drive and is_datadome_answer(head)):
        # Same reading as Intermarché (common.classify_refusal)
        return classify_refusal(status, head, captcha_url(head))
    if is_portal(final_url):
        return "portal"
    if not 200 <= status < 300:
        return "error"
    if not drive and _SESSION.search(head):
        return "retry"
    return "ok"


def check_answer(status: int, final_url: str | None, text: str | None) -> str:
    """``"ok"`` or ``"retry"``; any other kind of answer raises the matching error (pure)."""
    kind = classify_answer(status, final_url, text)
    if kind == "hard_block":
        raise HardBlockError(hard_block_message(LABEL), label=LABEL)
    if kind == "captcha":
        raise BlockedError(CAPTCHA_MESSAGE)
    if kind == "timeout":
        raise TimeoutError("E.Leclerc: fetch stopped by its time limit")
    if kind == "refused":
        logger.warning("E.Leclerc refused the request (HTTP %s): %s", status, (text or "")[:200])
        raise ScraperError(REFUSED_MESSAGE)
    if kind == "portal":
        raise StoreRequiredError(STORE_GONE)
    if kind == "error":
        logger.warning("E.Leclerc answered HTTP %s: %s", status, (text or "")[:200])
        raise ScraperError(SITE_ERROR)
    return kind


# ---------------------------------------------------------------- stores: pure parsing


def _raw_distance(point: dict) -> float | None:
    value = point.get("distance")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return float(value)


# Points listed by ``MapPoint/nearby`` are a few dozen km away at most: a
# distance beyond this is in metres, and so are the others of the answer
_METRES_BEYOND = 1000


def _coordinates(point: dict) -> tuple[float | None, float | None]:
    coords = point.get("coordinates") if isinstance(point.get("coordinates"), dict) else point
    lat = coords.get("latitude", coords.get("lat"))
    lon = coords.get("longitude", coords.get("lng", coords.get("lon")))
    ok = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon))
    return (float(lat), float(lon)) if ok else (None, None)


def nearby_points(data: object) -> list | None:
    """The ``points`` of a ``MapPoint/nearby`` answer, None when the answer has another shape."""
    if isinstance(data, dict) and isinstance(data.get("points"), list):
        return data["points"]
    return data if isinstance(data, list) else None


def parse_nearby(data: object) -> list[StoreOption]:
    """Drives and pedestrian pick-up points of a ``MapPoint/nearby`` answer (pure).

    Home deliveries and points abroad (postal code of another shape) are left
    out; ``url`` is the address of the drive (``store_base_from_point``). The
    distance given by the site is kept (km; metres when one of them is beyond
    1000); services/stores.py computes it from the coordinates when it can.
    """
    stores: list[StoreOption] = []
    seen: set[str] = set()
    points = [p for p in nearby_points(data) or [] if isinstance(p, dict)]
    distances = [d for d in map(_raw_distance, points) if d is not None]
    scale = 1000 if distances and max(distances) > _METRES_BEYOND else 1
    for point in points:
        kind = str(point.get("serviceType") or point.get("type") or "drive").strip().lower()
        if kind not in ("drive", "relais"):
            continue
        postal_code = str(point.get("postalCode") or point.get("codePostal") or "").strip()
        if postal_code and not re.fullmatch(r"\d{5}", postal_code):
            continue
        no_pl = _digits6(point.get("noPL"))
        url = store_base_from_point(point)
        if not no_pl or not url or url in seen:
            continue
        seen.add(url)
        city = _text(point.get("city") or point.get("ville")) or None
        street = _text(point.get("address") or point.get("adresse")) or None
        place = " ".join(p for p in (postal_code, city) if p)
        address = ", ".join(p for p in (street, place) if p) or None
        lat, lon = _coordinates(point)
        name = _text(point.get("name")) or f"n° {no_pl}"
        stores.append(
            StoreOption(
                id=no_pl,
                name=name if name.lower().startswith(("e.leclerc", "leclerc")) else f"E.Leclerc Drive {name}",
                address=address,
                url=url,
                services=["Drive"] if kind == "drive" else ["Retrait piéton"],
                postal_code=postal_code or None,
                city=city,
                lat=lat,
                lon=lon,
                distance_km=round(raw / scale, 1) if (raw := _raw_distance(point)) is not None else None,
            )
        )
    return stores


def place_of(data: object) -> dict | None:
    """First postal code of an ``autocomplete`` answer: ``{id, postalCode, city}``."""
    places = data.get("postalCodes") if isinstance(data, dict) else None
    first = places[0] if isinstance(places, list) and places else None
    return first if isinstance(first, dict) and first.get("id") else None


def coordinates_of(data: object) -> tuple[float, float] | None:
    """``(lat, lon)`` of an ``autocomplete/coordinates`` answer."""
    if not isinstance(data, dict):
        return None
    lat, lon = _coordinates(data)
    return (lat, lon) if lat is not None else None


_CONTEXT_COOKIE = re.compile(r"\|\s*(\d{6})\b")


def site_store_selection(
    url: str | None, html: str | None, cookie: str | None, known: list[StoreOption] | None = None
) -> StoreSelection | None:
    """Drive chosen on the site, read without any request (pure), or None.

    In order: the address of the tab, the banner of its page
    (``BandeauMultiUnivers.urlCourses``), the cookie ``clsWCSD107:ContexteMU``
    (« @d=2|173301 ») matched with the drives of the last list (``known``).
    """
    banner = widget(page_widgets(html or ""), "BandeauMultiUnivers")
    banner = banner if isinstance(banner, dict) else {}
    banner_no = _digits6(banner.get("sNoPointLivraison"))
    banner_name = _text(banner.get("nomPL")) or None
    listed = [(s, parse_store_url(s.url)) for s in known or [] if s.url]
    # A drive of the list by its numbers (its host may differ: fd1 redirects), a
    # pick-up point by its own number; by the number of the drive alone, the drive
    by_ref = {(r.no_pl, r.no_pr or r.no_pl): s for s, r in listed if r}
    by_id = {s.id: s for s, _ in reversed(listed) if "Drive" in s.services or not s.services}
    for address in (url, banner.get("urlCourses")):
        ref = parse_store_url(address if isinstance(address, str) else None)
        if ref is None:
            continue
        option = by_ref.get((ref.no_pl, ref.no_pr or ref.no_pl)) or by_id.get(ref.no_pl)
        known_name = banner_name if banner_no == ref.no_pl else None
        name = store_name_of(ref, known_name) if known_name or option is None else option.name
        return StoreSelection(
            id=ref.no_pl,
            name=name,
            url=ref.base,
            address=option.address if option else None,
        )
    match = _CONTEXT_COOKIE.search(unquote(cookie or ""))
    option = by_id.get(match.group(1)) if match else None
    if option is not None:
        return StoreSelection(id=option.id, name=option.name, url=option.url, address=option.address)
    return None


@dataclass
class DriveVisit:
    """Last visit of the page of a drive: its number, the address the site ended on, when."""

    no_pl: str
    base: str
    at: float


def _under(url: str, base: str) -> bool:
    url, base = (url or "").lower(), base.lower()
    return url == base or (url.startswith(base) and url[len(base)] in "/.?#")


def needs_store_visit(visit: DriveVisit | None, ref: StoreRef, page_url: str | None, now: float) -> bool:
    """The page of the drive must be visited (again) before searching (pure)."""
    return (
        visit is None
        or visit.no_pl != ref.no_pl
        or not _under(page_url or "", visit.base)
        or now - visit.at > REVISIT_SECONDS
    )


def debug_samples() -> bool:
    """PRIXMALIN_DEBUG_LECLERC=1: every search page is kept in data/debug (5 at most)."""
    return os.environ.get("PRIXMALIN_DEBUG_LECLERC", "") not in ("", "0")


# ---------------------------------------------------------------- scraper


class LeclercScraper(BaseScraper):
    key = "leclerc"
    label = LABEL
    home_url = PORTAL_URL
    needs_store = True
    primary_source = "api"
    store_url_example = STORE_URL_EXAMPLE
    captcha_message = CAPTCHA_MESSAGE
    store_hint = (
        "Les prix dépendent du drive. PrixMalin choisit le plus proche de votre code postal ; "
        "vous pouvez en prendre un autre dans la liste, sur le site (« Ouvrir le site ») "
        "ou en collant l'adresse de sa page."
    )

    def __init__(self) -> None:
        # Last visit of the page of the drive (it ties the session to the drive)
        self._visit: DriveVisit | None = None
        # When the site was opened with « Ouvrir le site » (the drive chosen
        # there is read back after « J'ai terminé »), None once read back
        self.site_opened_at: float | None = None
        # Last answer of the store finder (kept in data/debug when it gave no drive)
        self._last_locator_text = ""

    def setup_url(self, store: StoreSelection | None) -> str:
        """Page shown by « Ouvrir le site » (called by POST /api/browser/setup)."""
        self.site_opened_at = time.time()
        self._visit = None  # the user may go anywhere: visit the drive again before searching
        ref = parse_store_url(store.url) if store and store.url else None
        return ref.base + ".aspx" if ref else self.home_url

    # ------------------------------------------------------------ search

    async def search(self, page, query: str, store: StoreSelection | None) -> list[Product]:
        self.last_source = None
        if store is None or not store.url:
            raise StoreRequiredError(STORE_MISSING)
        ref = parse_store_url(store.url)
        if ref is None:
            raise StoreRequiredError(STORE_GONE)
        visit = await self._ensure_visit(page, ref)
        url = search_url(visit.base, query)
        result = await page_fetch(page, url, headers={"accept": "text/html"}, timeout_ms=FETCH_TIMEOUT_MS)
        text = result.text
        loaded = False
        self._keep_answer(result.status, result.content_type, text)
        if check_answer(result.status, result.url, text) == "retry":
            # fetch refused (redirection elsewhere) or session expired: visit the
            # drive again, then load the search as a page (once)
            logger.info("E.Leclerc: %s for '%s', loading the search page", result.status or "fetch refused", query)
            self._visit = None
            visit = await self._ensure_visit(page, ref)
            response = await page.goto(search_url(visit.base, query), wait_until="domcontentloaded", timeout=30000)
            await wait_for_clearance(page, self.label, CAPTCHA_MESSAGE)
            text = await page.content()
            status = response.status if response is not None else 200
            self._keep_answer(status, "text/html", text)
            if check_answer(status, page.url, text) == "retry":
                raise ScraperError(SEARCH_FAILED)
            loaded = True
        parsed = parse_search_html(text, visit.base)
        if parsed.truncated:
            logger.info("E.Leclerc: %d products of %d read for '%s' (truncated)", parsed.listed, parsed.total, query)
        products = self.found(parsed.products, parsed.source or "api")
        if not products and loaded:
            tiles = await page.evaluate(_TILES_JS)
            products = self.found(tiles_to_products(tiles, visit.base), "html")
        if debug_samples():
            save_debug_text(self.key, "sample", text, ".html")
        if not products and not parsed.store_page:
            # No page of the drive (error page of the site, maintenance...): not « Aucun produit »
            logger.warning("E.Leclerc: the search '%s' gave no page of the drive", query)
            save_debug_text(self.key, "error", text[:3_000_000], ".html")
            self.last_source = None
            raise ScraperError(SEARCH_FAILED)
        if not products:
            save_debug_text(self.key, "empty", text[:3_000_000], ".html")
        return products

    def _keep_answer(self, status: int, content_type: str, text: str | None) -> None:
        """Keep an answer that is not 2xx in data/debug (the diagnostic of « État des enseignes »)."""
        if not status or 200 <= status < 300:
            return
        if classify_answer(status, None, text) == "error":
            save_debug_text(self.key, "error", (text or "")[:500_000], ".txt")
        else:
            save_debug_text(self.key, "refused", refusal_record(status, content_type, text))

    async def _ensure_visit(self, page, ref: StoreRef) -> DriveVisit:
        if not needs_store_visit(self._visit, ref, page.url, time.monotonic()):
            return self._visit
        self._visit = None
        response = await page.goto(ref.base + ".aspx", wait_until="domcontentloaded", timeout=30000)
        if response is not None and response.status == 404:
            raise StoreRequiredError(STORE_GONE)
        await wait_for_clearance(page, self.label, CAPTCHA_MESSAGE)
        try:
            await page.wait_for_load_state("load", timeout=10000)
        except Exception as e:  # noqa: BLE001 (slow third-party resources: go on)
            logger.debug("E.Leclerc load: %s", e)
        await asyncio.sleep(config.REAL_CHROME_SETTLE_SECONDS)
        await wait_for_clearance(page, self.label, CAPTCHA_MESSAGE)
        landed = page.url
        if is_portal(landed):
            raise StoreRequiredError(STORE_GONE)
        shown = parse_store_url(landed)
        if shown is None:
            logger.warning("E.Leclerc: the drive %s led to %s", ref.base, landed)
            raise ScraperError(NOT_A_DRIVE)
        if shown.no_pl != ref.no_pl:
            logger.warning("E.Leclerc shows the drive %s instead of %s", shown.no_pl, ref.no_pl)
            raise StoreRequiredError(OTHER_DRIVE)
        self._visit = DriveVisit(ref.no_pl, shown.base, time.monotonic())
        return self._visit

    # ------------------------------------------------------------ stores

    async def _open_portal(self, page) -> None:
        """Park the tab on www.leclercdrive.fr (pause after the load, no click on the cookie banner)."""
        self._visit = None  # the tab leaves the drive: visit it again before searching
        await ensure_origin(
            page,
            self.home_url,
            self.label,
            settle=config.REAL_CHROME_SETTLE_SECONDS,
            accept=False,
            reload_on_block=False,
            captcha_message=CAPTCHA_MESSAGE,
        )

    async def _locator(self, page, url: str) -> object | None:
        """JSON of the store finder, called from a leclercdrive.fr page; None for an answer
        of another shape (DataDome raises)."""
        result = await page_fetch(page, url, headers={"accept": "application/json"}, timeout_ms=20000)
        kind = classify_answer(result.status, result.url, result.text)
        if kind == "retry" and not is_portal(page.url):
            # Not allowed from this page: from the portal, as the site itself
            await self._open_portal(page)
            result = await page_fetch(page, url, headers={"accept": "application/json"}, timeout_ms=20000)
            kind = classify_answer(result.status, result.url, result.text)
        if result.status and not result.ok:
            # The exact answer of a refusal (without the address: it holds the postal code)
            save_debug_text(self.key, "refused", refusal_record(result.status, result.content_type, result.text))
        if kind == "hard_block":
            raise HardBlockError(hard_block_message(LABEL), label=LABEL)
        if kind == "captcha":
            raise BlockedError(CAPTCHA_MESSAGE)
        if kind == "timeout":
            raise TimeoutError("E.Leclerc: store finder stopped by its time limit")
        if kind == "refused" or result.status == 0:
            logger.warning("E.Leclerc store finder refused (HTTP %s): %s", result.status, (result.text or "")[:200])
            raise ScraperError(LOCATOR_FAILED)
        if not result.ok:
            logger.info("E.Leclerc store finder answered HTTP %s for %s", result.status, url)
            self._last_locator_text = result.text
            return None
        self._last_locator_text = result.text
        try:
            return result.json()
        except ValueError:
            return None

    async def find_stores(self, page, lat: float | None, lon: float | None, postal_code: str) -> list[StoreOption]:
        """Drives near the user from the store finder of the site (in the dedicated window).

        ``MapPoint/nearby`` with the coordinates saved by PrixMalin; without
        them, or for an answer of another shape, the postal code is looked up
        first (``autocomplete`` then ``autocomplete/coordinates``).
        """
        self._last_locator_text = ""
        url = page.url or ""
        if not re.match(r"^https://[\w.-]*leclercdrive\.fr/", url):
            await self._open_portal(page)
        data = None
        if lat is not None and lon is not None:
            data = await self._locator(page, NEARBY_URL.format(lat=lat, lon=lon, cp=quote(postal_code or "")))
        if nearby_points(data) is None:
            if data is not None or lat is not None:
                await asyncio.sleep(LOCATOR_PAUSE_SECONDS)
            place = place_of(await self._locator(page, AUTOCOMPLETE_URL.format(q=quote(postal_code or ""))))
            coords = None
            if place is not None:
                await asyncio.sleep(LOCATOR_PAUSE_SECONDS)
                coords = coordinates_of(
                    await self._locator(page, COORDINATES_URL.format(id=quote(str(place["id"]), safe="")))
                )
            if coords is not None:
                await asyncio.sleep(LOCATOR_PAUSE_SECONDS)
                cp = str(place.get("postalCode") or postal_code or "")
                data = await self._locator(page, NEARBY_URL.format(lat=coords[0], lon=coords[1], cp=quote(cp)))
        stores = parse_nearby(data)
        if not stores:
            # The answer may have changed: keep it to update the reader
            save_debug_text(self.key, "stores", (self._last_locator_text or "")[:500000], ".json")
        return stores

    async def read_site_store(self, page) -> dict:
        """What the tab shows of the drive chosen on the site, without any request:
        ``{url, html, cookie}`` (``site_store_selection`` turns it into a drive)."""
        url = page.url or ""
        text = ""
        cookie = None
        if url not in ("", "about:blank"):
            try:
                text = await page.content()
            except Exception as e:  # noqa: BLE001 (page navigating: the address is enough)
                logger.debug("E.Leclerc read-back content: %s", e)
            try:
                cookies = await page.context.cookies(PORTAL_URL)
                cookie = next((c["value"] for c in cookies if c.get("name") == "clsWCSD107:ContexteMU"), None)
            except Exception as e:  # noqa: BLE001 (best effort)
                logger.debug("E.Leclerc read-back cookie: %s", e)
        return {"url": url, "html": text, "cookie": cookie}
