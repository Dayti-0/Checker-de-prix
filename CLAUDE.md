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

- **Backend** : Python 3.11+ (testé jusqu'à 3.14), FastAPI, Playwright (async), SQLite (aiosqlite, journal WAL). Version unique : `backend/__init__.__version__`
- **Frontend** : HTML/CSS/JS sans build (`frontend/`), mobile-first, modules ES natifs, routeur par hash (`#/`, `#/recherche?q=farine`, `#/liste`, `#/reglages`) ; les anciens liens `/?q=farine` sont redirigés vers `#/recherche?q=farine`. **CSP stricte** : aucun script, style ou gestionnaire `on*=` en ligne
- **Navigateur** (`backend/browser.py`) : un seul navigateur persistant pour toute l'app
  - tourne sur **son propre thread et sa propre boucle asyncio** (boucle Proactor sous Windows, indépendante d'uvicorn ; ne pas modifier ce code) ; on l'appelle avec `await browser.run(key, fn, *args, timeout=, priority=)` qui exécute `fn(page, *args)` dans l'onglet de l'enseigne `key`
  - profil persistant `data/browser-profile` : cookies, passage anti-bot et magasins choisis sur les sites survivent aux redémarrages
  - canal auto : Chrome installé, puis Edge, puis Chromium de Playwright (`CHANNEL_ORDER` ; `PRIXMALIN_BROWSER` pour forcer)
  - headless « nouveau » avec user-agent sans `HeadlessChrome` + `playwright-stealth` ; mode visible à la demande (« Ouvrir le site ») pour que l'utilisateur valide un captcha ou choisisse son magasin
  - un onglet par enseigne, appels sérialisés par enseigne et espacés d'au moins 1 s
- **Recherche** (`backend/services/search.py`) : cache SQLite 6 h (clé = enseigne + magasin + requête normalisée), une relance en cas d'erreur de navigation, statuts `ok | empty | store_required | blocked | timeout | error` avec message en français, pertinence (`services/matching.py` : `match_score`), prix au kg/L normalisé (`scrapers/parsing.py`)
- **Extraction générique** (`backend/scrapers/extract.py`) : cartes produit repérées par lien produit + prix en €, JSON-LD, recherche de produits dans n'importe quel JSON. Sert de secours quand les sélecteurs spécifiques cassent
- **Débogage** : quand un scraper ne trouve rien, la page est sauvée dans `data/debug/{enseigne}.html|png` (`common.snapshot_path`)

### Structure

```
backend/
  __init__.py          # __version__ (source unique : pyproject, /api/version, liens de index.html)
  main.py              # create_app() (hooks de démarrage, routeurs, erreurs, security, statiques), app, run()
  config.py            # chemins (data/), port, délais, variables PRIXMALIN_* (blocs P3 et P7)
  browser.py           # BrowserManager (thread dédié, profil persistant, mode visible)
  database.py          # connexion SQLite (WAL, busy_timeout), migrations ; réexporte les fonctions de repos/
  errors.py            # AppError (message français + statut HTTP), short_error(e)
  security.py          # install(app) : CSP et en-têtes ; is_local_request(request)
  instance.py          # ensure_single_instance() (sans effet, P7)
  logging_setup.py     # configure() (console, P7)
  migrations/          # pN_NNN_<nom>.py : async def up(db) ; table schema_migrations ; copie prixmalin.db.bak
  repos/               # requêtes SQL : cache.py, settings_store.py, shopping_list.py
  models/              # modèles Pydantic, un fichier par zone, tous réexportés par __init__.py
    products.py search.py browser.py settings.py status.py shopping.py tracking.py
  api/                 # routes HTTP, liste FIXE de routeurs (__init__.ROUTERS), tous sous /api
    errors.py          # gestionnaires d'erreurs centralisés + guard(action)
    common.py          # get_scraper(key) (404 si enseigne inconnue)
    search.py retailers.py settings.py browser.py shopping_list.py basket.py
    system.py          # /api/version ; pages « / » (index.html versionné) et /favicon.ico ; fichiers /static
    status.py tracking.py backup.py updates.py      # vides (P4, P6, P7)
  scrapers/
    base.py            # BaseScraper (last_source, found()), ScraperError / BlockedError / StoreRequiredError
    common.py          # helpers de page : cookies, anti-bot, fetch dans la page, snapshot_path
    extract.py         # extracteurs génériques (cartes HTML, JSON-LD, JSON)
    parsing.py         # prix, contenances, prix au kg/L
    aldi.py lidl.py carrefour.py intermarche.py coursesu.py
    __init__.py        # registre SCRAPERS (ordre d'affichage)
  services/
    hooks.py           # événements, tâches de démarrage, fournisseurs de sauvegarde
    prefs.py           # préférences par section (clé pref:<section>)
    search.py          # orchestration, cache, statuts, tri ; émet search_finished / products_scraped
    products.py        # prepare_products (prix unitaires, doublons, pertinence, tri)
    matching.py        # pertinence : match_score, relevance, query_key
    warmup.py          # préchauffage des sites au démarrage (hook)
    settings.py        # réglages, géocodage du code postal (geo.api.gouv.fr)
    shopping_list.py   # liste de courses (plafond 300 articles)
    basket.py          # comparaison du panier ; émet basket_compared ; réexporte la liste
frontend/              # servi sous /static (no-cache + ETag, gzip), index.html sous « / »
  index.html           # coquille : en-tête, bandeau, nav, formulaire de recherche, filtres, #view, messages
  icons.svg            # sprite d'icônes Lucide (ISC, voir vendor/README.md)
  vendor/              # ressources tierces : version exacte et licence
  css/                 # tokens, base, shell, components, home, search, results, list, basket, shopping,
                       #   print, settings, stores, status, onboarding, tracking, product, system
  js/
    boot.js            # script synchrone du <head> : taille du texte et thème avant le premier rendu
    main.js            # démarrage
    routes.js          # table FIXE des routes
    core/              # api, html, fmt, store, events, ui, icons, router, errors
    shell/             # nav, en-tête, taille du texte, formulaire de recherche et filtres
    components/        # retailer-badge, store-filters
    features/          # index.js (liste fixe) + offline-banner, setup-banner, bell, access-code, update-banner
    ext/               # product-badges.js, product-actions.js (fournisseurs pour la ligne produit)
    views/             # une vue par dossier : home (+ cards/), search, list, settings (+ sections/),
                       #   basket, shopping, tracking (+ history.js), product, status, onboarding
tests/
  fixtures/            # réponses et pages simulées, un fichier par enseigne (réexportées)
  e2e/                 # harnais E2E : fake.py, server.py, conftest.py, axe.py, helpers.py, demo.py
  test_*.py            # tests unitaires et d'API ; test_browser_scrapers.py (Chromium + sites simulés)
.github/workflows/ci.yml   # lint ruff + tests (Python 3.11 et 3.13, Chromium obligatoire)
pyproject.toml         # version, ruff, pytest
requirements.in        # dépendances (bornes) ; requirements.txt figé ; requirements-dev.txt
lancer.bat             # lanceur Windows (CRLF, voir .gitattributes)
```

## Contrats d'extension (posés par P0, stables, à ne pas renommer)

Chaque lot crée ses propres fichiers au lieu d'éditer ceux des autres. Les points d'extension ci-dessous existent déjà, vides ou sans effet quand leur lot n'est pas fait.

### Frontend

- `js/core/api.js` : `api(path, {method, body, signal, timeout})` renvoie le JSON (ou `null` pour 204), sinon lève `ApiError {status, code, message}` (message en français, `code` envoyé par le serveur ou `http_<statut>`, `offline`, `timeout`, `aborted`). Chaque requête porte `X-PrixMalin: 1`. Événements `api:offline`, `api:online`, `api:unauthorized` (401).
- `js/core/html.js` : `html\`\`` (échappement par défaut, tableaux joints, `null`/`false`/`true` n'affichent rien), `raw()`, `safeUrl()` (http/https seulement), `attr({...})`, `setHtml(el, html\`\`)` : **seul accès à `innerHTML`** (refuse une chaîne).
- `js/core/fmt.js` : `euros(v)`, `unitText(p)`, `plural(n, sing, plur = sing + "s")` → « 2 articles », `relativeTime(ts)` (secondes, millisecondes ou Date) → « il y a 2 h ».
- `js/core/store.js` : `state {settings, retailers, browser, list, enabled, search}`, `on(evt, fn)` (renvoie la fonction de désabonnement ; `"*"` = tout), `emit(evt, data)`, chargements (`loadSettings`, `loadList`...) et actions partagées (`addToList`, `openSetup`, `endSetup`, `requestSearch`). Événements : `search:requested|started|result|done|reset`, `list:changed`, `settings:changed`, `browser:changed`, `filters:changed`, `results:stale`, `location:changed`, `route:changed`, `api:*`.
- `js/core/ui.js` : `notify(msg, {type, action: {label, onClick}, duration})` (le « toast »), `announce(text)` (`#live-region`), `confirmDialog({title, message, confirmLabel, danger})` → `Promise<bool>` (boîte du navigateur pour l'instant).
- `js/core/icons.js` : `icon(name, {label})` lit le sprite `/static/icons.svg` (Lucide, ISC).
- `js/core/router.js` + `js/routes.js` : table **fixe** des routes. Chaque module de vue exporte `enabled`, `title` (texte ou `(params) => texte`), `render(el, params)` et éventuellement `update(params)`, `destroy()`, `nav: {id, label, icon, order, badge?, also?}`, `shell: {search, filters}` (affiche le formulaire de recherche et les filtres de la coquille). Les vues vides ont `enabled = false` : leur adresse mène à l'accueil.

  | Route | Lot | Navigation |
  |---|---|---|
  | `#/` (accueil) | P1 | Rechercher |
  | `#/recherche?q=` | P2 | — |
  | `#/liste` | P5 | Ma liste |
  | `#/panier` (vide) | P5 | — |
  | `#/courses` (vide) | P5 | — |
  | `#/suivis` (vide) | P6 | — |
  | `#/historique` (vide) | P6 | — |
  | `#/produit/:store/:key` (vide) | P6 | — |
  | `#/reglages?enseigne=` | P1 | Réglages |
  | `#/etat` (vide) | P4 | — |
  | `#/bienvenue` (vide) | P4 | — |

  Réglages est une **page** (`#/reglages`), pas une boîte de dialogue ; « Choisir mon magasin » mène à `#/reglages?enseigne=<clé>`.
- Cartes d'accueil `js/views/home/cards/{recent,list,alerts,savings,status,setup}.js` : chacune exporte `enabled` et `render(el)` (qui peut renvoyer une fonction de nettoyage). `recent` (suggestions) et `setup` (astuce magasins) sont remplies.
- Sections de Réglages `js/views/settings/sections/{location,stores,display,advanced,security,data,phone,about}.js` : chacune exporte `{id, title, order, enabled, render(el)}` (`render` peut renvoyer une fonction de nettoyage). `location`, `stores` et `advanced` (« Navigateur ») sont remplies.
- Modules transverses `js/features/index.js` (liste fixe) : `offline-banner` (P1), `setup-banner` (P4, rempli), `bell` (P6), `access-code` (P7), `update-banner` (P7). Chacun exporte `init()` (et `enabled = false` tant qu'il est vide).
- Emplacements produit `js/ext/product-badges.js` (`productBadges`) et `js/ext/product-actions.js` (`productActions`) : tableaux de fournisseurs `(product) => html`, appelés par la ligne produit (`views/search/product-row.js`) ; un fournisseur en erreur est ignoré.
- Conteneurs d'`index.html` à conserver : `#view`, `#search-form`, `#q`, `#store-filters`, `#header-extras`, `#setup-banner`, `#toast-region` (contient `#toast`), `#live-region`.
- Fichiers CSS liés par `index.html`, dans cet ordre : `tokens`, `base`, `shell`, `components`, `home`, `search`, `results`, `list`, `basket`, `shopping`, `print`, `settings`, `stores`, `status`, `onboarding`, `tracking`, `product`, `system`. `tokens.css` porte toutes les couleurs, tailles de police (`--text-*`), rayons (`--radius-*`), espacements (`--space-*`), `--control-h`, `--focus-ring`, `--accent-best`, `--bottom-bar-h`, `--ui-scale` ; thème sombre automatique ou forcé par `data-theme` sur `<html>`.
- `/static/js/boot.js` : script synchrone du `<head>` qui applique échelle (`prixmalin.textScale`) et thème (`prixmalin.theme`) avant le premier rendu.
- Fonctions pures JS : on les teste en E2E avec `js_eval(page, "/static/js/…", "fn", *args)` (`tests/e2e/helpers.py`).

### Backend

- `backend.__version__` est la source unique de version. `GET /api/version` renvoie `{version}`.
- `backend/api/__init__.py` déclare la liste **fixe** des routeurs, vides compris : `search`, `retailers`, `settings`, `browser`, `shopping_list`, `basket`, `system`, `status`, `tracking`, `backup`, `updates`. Chaque module définit `router` (sous `/api`) et éventuellement `pages` (à la racine).
- Erreurs centralisées dans `backend/api/errors.py`, réponse `{"detail": message, "code": code}` :

  | Exception | Code HTTP |
  |---|---|
  | `AppError` (`backend/errors.py`) | son `status_code` |
  | `BrowserUnavailable` | 502 |
  | `ScraperError` (et sous-classes) | 502 |
  | `asyncio.TimeoutError` / `TimeoutError` | 504 (message en français) |

  `with guard("Action impossible", timeout_message=...)` transforme toute autre erreur en 502 « Action impossible : … ».
- `backend/services/hooks.py` : `on(event, fn)` (renvoie la fonction de retrait), `await emit(event, **kw)` (chaque écouteur est isolé, ses erreurs sont journalisées), `on_startup(coro_fn)` (lancé en tâche de fond au démarrage, annulé à l'arrêt), `register_backup(name, export_fn, restore_fn)` (fournisseurs `settings` et `shopping_list` déjà enregistrés). Événements émis :
  - `search_finished(result, query, store_ctx, from_cache)`, par `search.py` ;
  - `products_scraped(store, store_ctx, query, products)`, seulement après une vraie lecture du site ;
  - `basket_compared(comparison)`, par `basket.py`.

  `store_ctx` = `scraper.context_key(store)` (id ou adresse du magasin choisi, `""` pour les prix nationaux). P3 et P5 doivent **conserver ces émissions**.
- `backend/services/prefs.py` : `await prefs.get(section, Model)` et `await prefs.update(section, Model, fn)` (`fn` modifie le modèle ou en renvoie un nouveau, peut être async), protégés par un verrou global. Stockage dans la clé `pref:<section>` de la table `settings`.
- `backend/migrations/` : la table `schema_migrations(id TEXT PRIMARY KEY, applied_at)` enregistre les migrations appliquées. Les modules `pN_NNN_<nom>.py` (`async def up(db)`) sont appliqués par ordre alphabétique d'`id`, et `prixmalin.db.bak` est copié avant toute nouvelle migration d'une base existante. Une migration fusionnée ne change plus.
- Champs de contrat (optionnels, nuls par défaut) : `Product.ean`, `Product.sku` ; `StoreResult.fetched_at: float|None` (heure de lecture, aussi pour un résultat en cache), `StoreResult.stale: bool`, `StoreResult.source: str|None` ; `BrowserStatus.is_local: bool` (calculé depuis `request.client`).
- Signatures :
  - `browser.run(key, fn, *args, timeout=None, priority="interactive")`, `priority` parmi `browser.PRIORITIES` = `interactive`, `basket`, `background` (accepté, ignoré tant que P3 n'est pas fusionné ; une valeur inconnue lève `ValueError`) ;
  - `browser.context_generation: int`, incrémenté à chaque nouveau contexte ;
  - `browser.CHANNEL_ORDER` et `browser.PLAYWRIGHT_INSTALL_ARGS` (`python <args>` installe Chromium) ;
  - `search.search_store(key, query, refresh=False, *, settings=None, priority="interactive")` ;
  - `matching.match_score(name, query) -> float`, qui vaut `relevance` dans P0 ;
  - `BaseScraper.last_source` : `"api"`, `"html"`, `"generic"` ou `"json-ld"` (`self.found(products, source)`), posé par chaque scraper ;
  - `common.snapshot_path(key, status)`.
- Points d'entrée sans effet fournis par P0 et remplis par P7 : `backend/security.install(app)` (CSP, `nosniff`, `Referrer-Policy` dans P0), `backend/instance.ensure_single_instance()`, `backend/logging_setup.configure()`.
- Monkeypatch stables pour les tests : `backend.main.browser`, `search._scrape`, `settings.geocode`, fonctions de `basket` (réexportées).

## Règles communes

- **Interface en français**, sans jargon ; pluriels avec `fmt.plural()` (jamais « (s) ») ; prix avec `fmt.euros()` ; dates avec `fmt.relativeTime()`. Glossaire : `blocked` → « Vérification requise », 0 résultat → « Aucun produit », approchants → « Produits proches », cache → « prix d'il y a 2 h », prix nationaux → « Prix identiques partout en France », `store_required` → « Magasin à choisir », panier → « 1 article introuvable » / « 2 articles introuvables ».
- **Frontend** : modules ES, pas de framework ni de build ; une bibliothèque indispensable va dans `frontend/vendor/` avec sa version et sa licence. Tout rendu passe par `html\`\`` + `setHtml`, les URL des sites par `safeUrl()`. Aucun `<script>` en ligne, attribut `on*=` ou `style=` (CSP) : styles dynamiques par classes ou `el.style.x`. Tout `<button>` hors formulaire porte `type="button"`. Uniquement les jetons de `tokens.css` (pas de taille de police ni de rayon bruts).
- **Accessibilité** : noms accessibles uniques, cibles de 44x44 px au doigt, annonces via `ui.announce()`, aucune violation axe *serious* ou *critical* en clair et en sombre (`tests/e2e/axe.py`), pas de défilement horizontal à 360 et 390 px.
- **Backend** : analyse et décisions en fonctions pures testées ; modèles d'un lot dans `backend/models/<zone>.py` (réexporté en une ligne) ; nouvelles tables par migration `backend/migrations/pN_NNN_<nom>.py` ; nouveaux réglages par `prefs` ; variables `PRIXMALIN_*` lues dans son module (sauf P3 et P7 dans `config.py`) ; journaux `logging.getLogger("prixmalin.<zone>")` ; aucun message technique montré à l'utilisateur.
- **Scraping** : tout appel à un site passe par `browser.run(..., priority=...)`, jamais deux appels en parallèle vers la même enseigne, espacement de 1 s conservé, aucune résolution automatique de captcha ; structures de site testées sur fixtures.
- **Tests** : `tests/test_pN_*.py` et `tests/e2e/test_pN_*.py` ; produits simulés supplémentaires dans `tests/e2e/catalog_pN.py` (chargés automatiquement) ; sélecteurs E2E par rôle, texte ou `data-testid`.

## API

Une ligne par routeur (`backend/api/<routeur>.py`), toutes les routes sous `/api` :

```
search          GET    /api/search?q=&stores=aldi,lidl&refresh=true   → toutes les enseignes (SearchResponse)
                GET    /api/search/{enseigne}?q=&refresh=true         → une enseigne (StoreResult) ; le front appelle
                                                                        celle-ci pour afficher chaque enseigne dès qu'elle répond
retailers       GET    /api/retailers                                 → enseignes + magasin choisi
                GET    /api/retailers/intermarche/stores              → magasins proches (code postal requis)
                PUT    /api/retailers/{intermarche|coursesu}/store    → choisir un magasin ({id,name,address} ou {url})
                DELETE /api/retailers/{enseigne}/store
settings        GET    /api/settings | PATCH /api/settings {show_browser}
                POST   /api/settings/location {postal_code, city?}
browser         GET    /api/browser | POST /api/browser/setup {store} | POST /api/browser/setup/done
shopping_list   GET    /api/list | POST /api/list {query, quantity, product?} | PATCH /api/list/{id} | DELETE /api/list[/{id}]
basket          POST   /api/basket/compare {stores?, refresh?}
system          GET    /api/version → {version} ; pages : GET / (index.html versionné), GET /favicon.ico
status, tracking, backup, updates : vides
```

Erreurs : `{"detail": "<message en français>", "code": "<code>"}` (voir `backend/api/errors.py`) ; 422 pour une requête invalide (FastAPI).

## Lancement et tests

```bash
pip install -r requirements.txt
python -m playwright install chromium
python -m backend.main          # http://localhost:8000 (pas d'auto-reload : il casserait Playwright sous Windows)

pip install -r requirements-dev.txt          # pytest, pytest-cov, ruff
python -m pytest                             # PRIXMALIN_REQUIRE_BROWSER=1 : Chromium absent = échec (CI)
ruff check . && ruff format --check .
python -m tests.e2e.demo --port 8771 --fixed # enseignes simulées pour les captures (ports libres : 8771-8779)

# Après un changement de requirements.in (roues Windows et CPython 3.11 à 3.14) :
uv pip compile --universal --python-version 3.11 requirements.in -o requirements.txt
```

Variables utiles : `PRIXMALIN_PORT`, `PRIXMALIN_HOST`, `PRIXMALIN_DATA_DIR`, `PRIXMALIN_BROWSER` (chrome|msedge|chromium), `PRIXMALIN_TIMEOUT` (s, défaut 40), `PRIXMALIN_WARMUP=0` (pas d'ouverture des sites au démarrage), `PRIXMALIN_STEALTH=0`, `PRIXMALIN_REQUIRE_BROWSER=1`, `PRIXMALIN_TEST_ARTIFACTS=<dossier>` (captures des tests E2E en échec).

Harnais E2E (`tests/e2e/`) : `fake.py` simule les enseignes (Aldi et Lidl répondent, Carrefour avec promo, bio, EAN et produit indisponible, Intermarché « magasin à choisir » tant qu'aucun magasin n'est choisi, Courses U bloqué jusqu'à « Ouvrir le site » puis « J'ai terminé »), le géocodage, les magasins Intermarché et le navigateur ; fixtures `desktop` (1440x900), `mobile` (390x844, tactile) et `dark` ; toute erreur console, exception ou violation CSP fait échouer le test ; `axe.assert_accessible(page)`.

## Bonnes pratiques

- Préférer les API JSON internes des sites (plus stables que le HTML), appelées depuis la page du site.
- Tout ce qui est analyse de texte/JSON doit être une fonction pure testée (`parse_search_json`, `card_to_product`...) ; le JS injecté se contente de collecter.
- Quand un site change : regarder `data/debug/{enseigne}.html`, mettre à jour le scraper et les fixtures de `tests/fixtures/<enseigne>.py`.
- Ne pas contourner les captchas : en cas de blocage, l'utilisateur ouvre le site dans le navigateur PrixMalin et valide lui-même.

## Lots

Une sous-section par zone ; chaque lot ne met à jour que la sienne. Propriété des fichiers : voir le backlog (section 3) ; un besoin hors de son périmètre va dans le rapport final, « Demandes aux autres lots ».

### Interface

P1 : coquille, design system, accessibilité, PWA. Fichiers : `index.html`, `css/{tokens,base,shell,components,home,settings}.css`, `js/core/{api,ui,router,errors,icons}.js`, `js/shell/*`, `js/features/offline-banner.js`, `js/views/home/index.js`, `js/views/settings/index.js`, `js/views/settings/sections/display.js`, `backend/api/system.py` (sauf `/api/version`).

### Recherche et résultats

P2. Fichiers : `js/views/search/*`, `js/views/home/cards/recent.js`, `css/{search,results}.css`, `backend/services/{matching,products}.py`, `backend/scrapers/{parsing,aldi,lidl,carrefour,extract}.py`, `backend/models/products.py`, `tests/fixtures/{aldi,lidl,carrefour,generic}.py`.

### Navigateur et moteur

P3. Fichiers : `backend/browser.py`, `backend/services/{search,warmup}.py`, `backend/repos/cache.py`, `backend/scrapers/{base,common,intermarche}.py`, `backend/api/{search,browser}.py`, `backend/models/{search,browser}.py`, `js/views/settings/sections/advanced.js`, `tests/fixtures/intermarche.py`, bloc « délais » de `config.py`.

### Enseignes et magasins

P4. Fichiers : `backend/scrapers/coursesu.py`, `backend/services/settings.py`, `backend/repos/settings_store.py`, `backend/api/{retailers,settings,status}.py`, `backend/models/{settings,status}.py`, `js/views/settings/sections/{location,stores}.js`, `js/views/{status,onboarding}/*`, `js/views/home/cards/{status,setup}.js`, `js/features/setup-banner.js`, `css/{status,onboarding,stores}.css`, `tests/fixtures/coursesu.py`.

### Liste et panier

P5. Fichiers : `backend/services/{shopping_list,basket}.py`, `backend/repos/shopping_list.py`, `backend/api/{shopping_list,basket}.py`, `backend/models/shopping.py`, `js/views/{list,basket,shopping}/*`, `js/views/home/cards/list.js`, `css/{list,basket,shopping,print}.css`.

### Historique et suivis

P6. Fichiers : `backend/api/tracking.py`, `backend/models/tracking.py`, `js/views/{tracking,product}/*`, `js/ext/{product-badges,product-actions}.js`, `js/features/bell.js`, `js/views/home/cards/{alerts,savings}.js`, `css/{tracking,product}.css`.

### Sécurité et exploitation

P7. Fichiers : `backend/{security,instance,logging_setup}.py`, `backend/main.py`, `backend/api/{backup,updates}.py`, `js/views/settings/sections/{security,data,about,phone}.js`, `js/features/{access-code,update-banner}.js`, `css/system.css`, `lancer.bat`, `.github/*`, `README.md`, lignes `DATA_DIR`/`HOST` de `config.py`.

## Notes

- **Légalité** : usage personnel uniquement. Le scraping peut violer les CGU des sites. Ne pas distribuer ni commercialiser.
- **Lidl** ne publie en ligne qu'une partie de son assortiment alimentaire.
- Idées V2 : historique des prix, alertes de baisse, suggestions de produits équivalents moins chers.
