"""Intermarché: the site's own JSON API, called from inside an intermarche.com tab.

The API is protected by DataDome, which only lets real browser sessions through,
hence the in-page fetch(). Endpoints and fields as used by the site in 2026.

The tab belongs to a dedicated real Chrome window (backend/real_chrome.py): no
cookie banner clicked by script, a pause after the site loaded, a challenge
shown in the tab is reported without loading the site again, and a refused
connection (hard block) is never retried.
"""

import json
import logging
import re
import secrets
import unicodedata
from urllib.parse import quote

from backend import config
from backend.models import Product, StoreOption, StoreSelection
from backend.scrapers.base import BaseScraper, BlockedError, HardBlockError, ScraperError, StoreRequiredError
from backend.scrapers.common import (
    FetchResult,
    classify_datadome,
    ensure_origin,
    hard_block_message,
    page_fetch,
    save_debug_text,
)
from backend.scrapers.extract import products_from_json
from backend.scrapers.parsing import clean_text, parse_price

logger = logging.getLogger(__name__)

BASE_URL = "https://www.intermarche.com"
SEARCH_API = BASE_URL + "/api/service/produits/v4/pdvs/{pdv}/products/byKeywordAndCategory"
STORES_API = BASE_URL + "/api/service/pdvs/v4/pdvs/zone?lat={lat}&lon={lon}&min=10&r=15000"
# Results asked per search (one request: the site itself asks for 20 to 40)
PAGE_SIZE = 40

LABEL = "Intermarché"
CAPTCHA_MESSAGE = (
    "Intermarché demande une vérification : appuyez sur « Ouvrir le site », validez-la dans la "
    "fenêtre Chrome d'Intermarché ouverte par PrixMalin, puis appuyez sur « J'ai terminé »."
)
# A refusal of the API that is not DataDome: nothing to validate in the window
REFUSED_MESSAGE = (
    "Intermarché a refusé la recherche. Réessayez dans un moment ; si cela se répète, "
    "téléchargez le diagnostic depuis « État des enseignes » et envoyez-le."
)

# Identifiers the site sends with each API call (taken from its own cookies)
_IDENTIFIERS_JS = r"""
() => {
  const pick = (n) => {
    const c = document.cookie.split('; ').find((v) => v.startsWith(n + '='));
    return c ? decodeURIComponent(c.slice(n.length + 1)) : '';
  };
  let device = '';
  try { device = String(JSON.parse(pick('itm_device_id')).id || ''); } catch (e) {}
  if (!device) device = crypto.randomUUID();
  return {device, session: pick('itm_usid') || device, ua: navigator.userAgent};
}
"""

# Store chosen directly on the website (when the user did it in the browser)
_STORAGE_JS = r"""
() => ({
  store: sessionStorage.getItem('itm-store') || localStorage.getItem('itm-store') || '',
  analytic: localStorage.getItem('persist:analytic') || '',
})
"""


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _find_key(value: object, pattern: re.Pattern, depth: int = 0) -> str | None:
    if isinstance(value, str) and value[:1] in "{[":
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if depth > 6:
        return None
    if isinstance(value, dict):
        for key, nested in value.items():
            if pattern.match(key) and isinstance(nested, (str, int)) and str(nested).strip():
                return str(nested).strip().strip('"')
            found = _find_key(nested, pattern, depth + 1)
            if found:
                return found
    if isinstance(value, list):
        for nested in value:
            found = _find_key(nested, pattern, depth + 1)
            if found:
                return found
    return None


def store_from_storage(storage: dict) -> str | None:
    raw = (storage.get("store") or "").strip().strip('"')
    if re.fullmatch(r"\d{3,}", raw):
        return raw
    pattern = re.compile(r"^(pdvRef|pdvReference|storeRef|storeCode|reference|ref)$", re.I)
    return _find_key(raw, pattern) or _find_key(storage.get("analytic") or "", re.compile(r"^(pdvRef|storeRef)$", re.I))


def parse_search_json(data: object) -> list[Product]:
    if not isinstance(data, dict):
        return []
    items = data.get("produits") or data.get("products")
    if items is None and isinstance(data.get("data"), dict):
        items = data["data"].get("produits") or data["data"].get("products")
    if not isinstance(items, list):
        return []

    products = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = clean_text(item.get("libelle") or item.get("label") or item.get("name"))
        if not name:
            continue
        price = parse_price(item.get("prix") if item.get("prix") is not None else item.get("unitPrice"))
        old_price = parse_price(item.get("prixBarre"))

        unit_label = None
        per_kg = parse_price(item.get("prixKg"))
        if per_kg is not None:
            unit = item.get("unitePrixVente")
            unit_text = unit.get("value") if isinstance(unit, dict) else unit
            unit_label = f"{per_kg:.2f} {unit_text or '€/kg'}".replace(".", ",")

        images = item.get("images")
        image = images[0] if isinstance(images, list) and images and isinstance(images[0], str) else None
        ean13 = str(item.get("produitEan13") or "").strip()
        product_id = str(item.get("idProduit") or "").strip()
        ean = ean13 or product_id
        stock = item.get("stock")

        products.append(
            Product(
                store="intermarche",
                name=name,
                brand=clean_text(item.get("marque")) or None,
                price=price,
                unit_price_label=unit_label,
                quantity_label=clean_text(item.get("conditionnement")) or None,
                image_url=image,
                product_url=f"{BASE_URL}/produit/{_slugify(name)}/{ean}" if ean else BASE_URL,
                promo=f"Au lieu de {old_price:.2f} €".replace(".", ",")
                if old_price and price and old_price > price
                else None,
                available=item.get("dispoCataloguePdv") is not False and stock != 0,
                ean=ean13 if re.fullmatch(r"\d{8,14}", ean13) else None,
                sku=product_id or str(item.get("itemId") or "").strip() or None,
            )
        )
    return products


def has_products_list(data: object) -> bool:
    """The answer has the expected shape (a list of products, maybe empty)."""
    if not isinstance(data, dict):
        return False
    if isinstance(data.get("produits"), list) or isinstance(data.get("products"), list):
        return True
    nested = data.get("data")
    return isinstance(nested, dict) and any(isinstance(nested.get(k), list) for k in ("produits", "products"))


def check_answer(status: int, text: str) -> None:
    """Turn an API answer of the site into the right error (pure function).

    DataDome answers 403 with ``{"url": "https://geo.captcha-delivery.com/..."}``:
    ``t=bv`` (or « Accès temporairement restreint ») is a hard block, any other
    captcha URL a check the user can validate in the window. 429 (too many
    requests) is treated like a hard block: PrixMalin backs off. A refusal
    (401, 403, 405) without any DataDome mark is not a check: there is nothing
    to validate in the window (seen in October 2026), so it is an error.
    """
    head = (text or "")[:5000]
    if status in (401, 403, 405, 429) or "captcha-delivery.com" in head:
        kind = classify_datadome(None, head)
        if kind == "hard_block" or status == 429:
            raise HardBlockError(hard_block_message(LABEL), label=LABEL)
        if kind == "captcha":
            raise BlockedError(CAPTCHA_MESSAGE)
        logger.warning("Intermarché refused the search (HTTP %s): %s", status, head[:200])
        raise ScraperError(REFUSED_MESSAGE)
    if status == 0:
        logger.warning("Intermarché unreachable: %s", head[:200])
        raise ScraperError("Intermarché est injoignable. Vérifiez votre connexion Internet.")
    if not 200 <= status < 300:
        logger.warning("Intermarché answered HTTP %s: %s", status, head[:200])
        raise ScraperError("Intermarché a renvoyé une erreur. Réessayez plus tard.")


def refusal_record(result: FetchResult) -> str:
    """JSON kept in data/debug when the API does not answer 2xx: status, type and start of the body.

    Neither the URL (it holds the store) nor the request headers.
    """
    return json.dumps(
        {"status": result.status, "content_type": result.content_type, "body": (result.text or "")[:20000]},
        ensure_ascii=False,
        indent=1,
    )


def parse_stores(data: object) -> list[StoreOption]:
    results = data.get("resultats") if isinstance(data, dict) else data
    if not isinstance(results, list):
        return []
    stores = []
    for r in results:
        if not isinstance(r, dict) or not r.get("storeCode"):
            continue
        name = clean_text(r.get("entityLabel")) or "Intermarché"
        banner = clean_text(r.get("tradeNameLabel"))
        if banner and banner.lower() not in name.lower():
            name = f"{banner} {name}"
        addresses = r.get("addresses") or [{}]
        a = addresses[0] if isinstance(addresses[0], dict) else {}
        address = ", ".join(
            part
            for part in (clean_text(a.get("address")), f"{a.get('postCode') or ''} {a.get('townLabel') or ''}".strip())
            if part
        )
        distance = r.get("distance")
        stores.append(
            StoreOption(
                id=str(r["storeCode"]),
                name=name,
                address=address or None,
                distance_km=round(distance / 1000, 1) if isinstance(distance, (int, float)) else None,
            )
        )
    return sorted(stores, key=lambda s: s.distance_km if s.distance_km is not None else 1e9)


class IntermarcheScraper(BaseScraper):
    key = "intermarche"
    label = "Intermarché"
    home_url = BASE_URL + "/"
    needs_store = True
    store_hint = "Les prix dépendent du magasin : choisissez le vôtre dans la liste (code postal requis)."

    def setup_url(self, store: StoreSelection | None) -> str:
        return self.home_url

    async def _headers(self, page, service: str | None) -> dict:
        ids = await page.evaluate(_IDENTIFIERS_JS)
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "x-itm-device-fp": ids["device"],
            "x-itm-session-id": ids["session"],
            "x-itm-user-agent": ids["ua"],
            "x-red-version": "3",
            "x-red-device": "red_fo_desktop",
            "x-is-server": "false",
            "x-call-trace": "web",
            "x-b3-traceid": secrets.token_hex(16),
            "x-b3-spanid": secrets.token_hex(8),
            "x-b3-sampled": "1",
        }
        if service:
            headers["x-service-name"] = service
        if service == "produits":
            headers.update(
                {
                    "x-optional-oauth": "true",
                    "x-itm-navigation-personalization-optout": "false",
                    "x-itm-sponsored-page": "true",
                }
            )
        return headers

    def _check(self, result: FetchResult) -> None:
        check_answer(result.status, result.text)

    async def _open_site(self, page) -> None:
        """Park the tab on intermarche.com (pause after a load, no script click on the cookie banner)."""
        await ensure_origin(
            page,
            self.home_url,
            self.label,
            settle=config.REAL_CHROME_SETTLE_SECONDS,
            accept=False,
            reload_on_block=False,
            captcha_message=CAPTCHA_MESSAGE,
        )

    def _json(self, result: FetchResult) -> object:
        try:
            return result.json()
        except ValueError as e:
            save_debug_text(self.key, "error", result.text[:200000], ".txt")
            raise ScraperError("Intermarché a renvoyé une réponse illisible. Réessayez plus tard.") from e

    async def search(self, page, query: str, store: StoreSelection | None) -> list[Product]:
        self.last_source = None
        await self._open_site(page)
        pdv = store.id if store and store.id else store_from_storage(await page.evaluate(_STORAGE_JS))
        if not pdv:
            raise StoreRequiredError("Choisissez votre magasin Intermarché dans les réglages pour voir les prix.")

        body = {
            "keyword": query,
            "page": 1,
            "size": PAGE_SIZE,
            "filtres": [],
            "tri": "pertinence",
            "ordreTri": None,
            "catalog": ["PDV"],
        }
        result = await page_fetch(
            page, SEARCH_API.format(pdv=quote(str(pdv), safe="")), "POST", await self._headers(page, "produits"), body
        )
        if not result.ok:
            # The exact answer of a refusal: what to fix (in the diagnostic of « État des enseignes »)
            save_debug_text(self.key, "refused", refusal_record(result))
        self._check(result)
        data = self._json(result)
        if not has_products_list(data):
            # The site changed its answer: keep it to update the scraper
            save_debug_text(self.key, "json", result.text[:500000])
        products = self.found(parse_search_json(data), "api")
        if not products:
            products = self.found(products_from_json(data, self.key, BASE_URL), "generic")
        return products

    async def find_stores(self, page, lat: float, lon: float) -> list[StoreOption]:
        await self._open_site(page)
        result = await page_fetch(page, STORES_API.format(lat=lat, lon=lon), headers=await self._headers(page, None))
        self._check(result)
        data = self._json(result)
        if not isinstance(data, dict) or not isinstance(data.get("resultats"), list):
            save_debug_text(self.key, "json", result.text[:500000])
        return parse_stores(data)
