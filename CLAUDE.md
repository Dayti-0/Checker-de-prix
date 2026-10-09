# PrixMalin - Comparateur de prix supermarchés français

## Objectif

Application web personnelle qui compare les prix de produits alimentaires courants entre supermarchés français. L'utilisateur tape un nom de produit (ex : "Huile de tournesol", "Farine", "Eau", "Vinaigre") et l'app affiche les prix trouvés chez chaque enseigne, du moins cher au plus cher. Une liste de courses permet de comparer le total d'un panier entre enseignes.

## Enseignes

| Enseigne | Clé | Méthode | Magasin |
|----------|-----|---------|---------|
| **Aldi** | `aldi` | Page `https://www.aldi.fr/recherche.html?query=` (tuiles `.product-tile`), secours : réponses Algolia interceptées, extracteur générique, JSON-LD | Prix nationaux |
| **Lidl** | `lidl` | API `GET /q/api/search?q=&assortment=FR&locale=fr_FR&version=v2.0.0` (items → `gridbox.data` : `fullTitle`, `price.price`, `price.basePrice.text`), secours : page `/q/search?q=` | Prix nationaux |
| **Carrefour** | `carrefour` | `GET /s?q=&page=1` avec en-têtes `accept: application/json` + `x-requested-with: XMLHttpRequest` → JSON (`data[].attributes` : `title`, `brand`, `ean`, `slug`, `offers[ean][offerId].attributes.price.{price,perUnitLabel}`), URL produit `/p/{slug}-{ean}`. Secours : page `/s?q=&noRedirect=1` | Prix en ligne par défaut, magasin choisissable à la main sur le site |
| **Intermarché** | `intermarche` | API `POST /api/service/produits/v4/pdvs/{pdvRef}/products/byKeywordAndCategory` (réponse `produits[]` : `libelle`, `marque`, `prix`, `prixKg`, `unitePrixVente`, `images`). Magasins : `GET /api/service/pdvs/v4/pdvs/zone?lat=&lon=&min=10&r=` (`resultats[]` : `storeCode`, `entityLabel`...). En-têtes `x-itm-*`, `x-red-*` copiés du site | **Obligatoire** : `pdvRef` choisi dans les réglages, ou lu dans le `localStorage` (`itm-store`) si choisi sur le site |
| **Courses U** | `coursesu` | Page `https://www.coursesu.com/recherche?q=` (tuiles SFCC `[data-pid]`), extracteur générique en secours | **Obligatoire** : l'utilisateur donne l'URL de son magasin (ex : `https://www.coursesu.com/drive-superu-roujan`), visitée avant la recherche pour poser le contexte magasin |

Ces sites changent sans prévenir : les structures ci-dessus datent de 2026. Carrefour (Cloudflare) et Intermarché (DataDome) refusent tout client qui n'est pas un vrai navigateur : les appels API se font donc **depuis une page du site** (`fetch()` dans la page, voir `page_fetch`).

## Architecture

- **Backend** : Python 3.11+, FastAPI, Playwright (async), SQLite (aiosqlite)
- **Frontend** : HTML/CSS/JS sans build (`frontend/`), mobile-first
- **Navigateur** (`backend/browser.py`) : un seul navigateur persistant pour toute l'app
  - tourne sur **son propre thread et sa propre boucle asyncio** (boucle Proactor sous Windows, indépendante d'uvicorn) ; on l'appelle avec `await browser.run(key, fn, *args, timeout=)` qui exécute `fn(page, *args)` dans l'onglet de l'enseigne `key`
  - profil persistant `data/browser-profile` : cookies, passage anti-bot et magasins choisis sur les sites survivent aux redémarrages
  - canal auto : Chrome installé, puis Edge, puis Chromium de Playwright (`PRIXMALIN_BROWSER` pour forcer)
  - headless « nouveau » avec user-agent sans `HeadlessChrome` + `playwright-stealth` ; mode visible à la demande (« Ouvrir le site ») pour que l'utilisateur valide un captcha ou choisisse son magasin
  - un onglet par enseigne, appels sérialisés par enseigne et espacés d'au moins 1 s
- **Recherche** (`backend/services/search.py`) : cache SQLite 6 h (clé = enseigne + magasin + requête normalisée), une relance en cas d'erreur de navigation, statuts `ok | empty | store_required | blocked | timeout | error` avec message en français, pertinence (`services/matching.py` : part des mots de la requête présents dans le nom, accents/pluriels ignorés), prix au kg/L normalisé (`scrapers/parsing.py`)
- **Extraction générique** (`backend/scrapers/extract.py`) : cartes produit repérées par lien produit + prix en €, JSON-LD, recherche de produits dans n'importe quel JSON. Sert de secours quand les sélecteurs spécifiques cassent
- **Débogage** : quand un scraper ne trouve rien, la page est sauvée dans `data/debug/{enseigne}.html|png`

### Structure

```
backend/
  main.py              # FastAPI : routes API + fichiers statiques ; python -m backend.main
  config.py            # chemins (data/), port, timeouts, variables PRIXMALIN_*
  browser.py           # BrowserManager (thread dédié, profil persistant, mode visible)
  database.py          # SQLite : cache, réglages, liste de courses
  models.py            # modèles Pydantic
  scrapers/
    base.py            # BaseScraper, ScraperError / BlockedError / StoreRequiredError
    common.py          # helpers de page : cookies, détection anti-bot, fetch dans la page
    extract.py         # extracteurs génériques (cartes HTML, JSON-LD, JSON)
    parsing.py         # prix, contenances, prix au kg/L
    aldi.py lidl.py carrefour.py intermarche.py coursesu.py
    __init__.py        # registre SCRAPERS (ordre d'affichage)
  services/
    search.py          # orchestration, cache, statuts, tri
    matching.py        # pertinence
    settings.py        # réglages, géocodage du code postal (geo.api.gouv.fr)
    basket.py          # liste de courses et comparaison de panier
frontend/              # index.html, style.css, app.js
tests/                 # pytest (dont scénarios Chromium avec sites simulés)
lancer.bat             # lanceur Windows
```

## API

```
GET    /api/search?q=&stores=aldi,lidl&refresh=true   → toutes les enseignes (SearchResponse)
GET    /api/search/{enseigne}?q=&refresh=true         → une enseigne (StoreResult) ; le front appelle
                                                        celle-ci pour afficher chaque enseigne dès qu'elle répond
GET    /api/retailers                                 → enseignes + magasin choisi
GET    /api/retailers/intermarche/stores              → magasins proches (code postal requis)
PUT    /api/retailers/{intermarche|coursesu}/store    → choisir un magasin ({id,name,address} ou {url})
DELETE /api/retailers/{enseigne}/store
GET    /api/settings | PATCH /api/settings {show_browser}
POST   /api/settings/location {postal_code, city?}
GET    /api/browser | POST /api/browser/setup {store} | POST /api/browser/setup/done
GET    /api/list | POST /api/list {query, quantity, product?} | PATCH /api/list/{id} | DELETE /api/list[/{id}]
POST   /api/basket/compare {stores?, refresh?}
```

## Lancement et tests

```bash
pip install -r requirements.txt
python -m playwright install chromium
python -m backend.main          # http://localhost:8000 (pas d'auto-reload : il casserait Playwright sous Windows)

pip install pytest
python -m pytest                # les tests navigateur sont ignorés si Chromium est absent
```

Variables utiles : `PRIXMALIN_PORT`, `PRIXMALIN_HOST`, `PRIXMALIN_DATA_DIR`, `PRIXMALIN_BROWSER` (chrome|msedge|chromium), `PRIXMALIN_TIMEOUT` (s, défaut 40), `PRIXMALIN_WARMUP=0` (pas d'ouverture des sites au démarrage), `PRIXMALIN_STEALTH=0`.

## Bonnes pratiques

- Préférer les API JSON internes des sites (plus stables que le HTML), appelées depuis la page du site.
- Tout ce qui est analyse de texte/JSON doit être une fonction pure testée (`parse_search_json`, `card_to_product`...) ; le JS injecté se contente de collecter.
- Quand un site change : regarder `data/debug/{enseigne}.html`, mettre à jour le scraper et les fixtures de `tests/fixtures.py`.
- Ne pas contourner les captchas : en cas de blocage, l'utilisateur ouvre le site dans le navigateur PrixMalin et valide lui-même.

## Notes

- **Légalité** : usage personnel uniquement. Le scraping peut violer les CGU des sites. Ne pas distribuer ni commercialiser.
- **Lidl** ne publie en ligne qu'une partie de son assortiment alimentaire.
- Idées V2 : historique des prix, alertes de baisse, suggestions de produits équivalents moins chers.
