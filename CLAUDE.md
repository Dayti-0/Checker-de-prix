# PrixMalin - Comparateur de prix supermarchés français

## Objectif

Application web personnelle qui compare les prix de produits alimentaires courants entre supermarchés français. L'utilisateur tape un nom de produit (ex : "Huile de tournesol", "Farine", "Eau", "Vinaigre") et l'app affiche les prix trouvés chez chaque enseigne, du moins cher au plus cher. Une liste de courses permet de comparer le total d'un panier entre enseignes.

## Enseignes

| Enseigne | Clé | Méthode | Magasin |
|----------|-----|---------|---------|
| **Aldi** | `aldi` | Page `https://www.aldi.fr/recherche.html?query=` (tuiles `.product-tile`, identifiant `data-article-id` si présent), « Voir plus » ou lien `rel=next` suivi une fois (`extract.read_more`), secours : réponses Algolia interceptées, extracteur générique, JSON-LD | Prix nationaux |
| **Lidl** | `lidl` | API `GET /q/api/search?q=&assortment=FR&locale=fr_FR&version=v2.0.0&fetchsize=48` avec `accept: application/mindshift.search+json;version=2, …` (un `application/json` seul reçoit **HTTP 406**, vu sur lidl.es/.ie/.pt en 2026) (items → `gridbox.data` : `fullTitle` (entités HTML et traits d'union invisibles retirés), `price.price`, `price.oldPrice`, `price.basePrice.text`, `productId` → `sku`, `ians`/`ean`/`gtin` → `ean`) ; `numFound` plus grand que le nombre lu : suite demandée une fois avec `&offset=`. Réponse sans produit (`items: []`, `resultType: empty`) = vrai « aucun produit » (`source = api`, réponse brute gardée dans `data/debug/lidl-…-empty.json`, message `LidlScraper.empty_message`, ne compte pas pour « Probablement cassé ») : lidl.fr ne publie qu'environ 170 produits alimentaires (dont la moitié de vin) et les offres de la semaine. `resultType: redirect` → page `redirectURL` (lidl.fr seulement). Secours (API sans JSON, refus gardé en `.txt`) : page `/q/search?q=`, tuiles lues par leur attribut `data-grid-data` (même gridbox), puis extracteur générique | Prix nationaux |
| **Carrefour** | `carrefour` | `GET /s?q=&page=1` avec en-têtes `accept: application/json` + `x-requested-with: XMLHttpRequest` → JSON (`data[].attributes` : `title`, `brand`, `ean` → `ean` et `sku`, `slug`, `images` en `/media/280x280/`, `offers[ean][offerId].attributes.price.{price,perUnitLabel}`), URL produit `/p/{slug}-{ean}` ; `page=2` quand la page 1 est pleine (`links.next`, `meta.total`, sinon 24 produits ou plus). Secours : page `/s?q=&noRedirect=1` | Prix en ligne par défaut, magasin choisissable à la main sur le site |
| **Intermarché** | `intermarche` | **Fenêtre Chrome dédiée** (`backend/real_chrome.py`, voir « Navigateur et moteur »). API `POST /api/service/produits/v4/pdvs/{quote(pdvRef)}/products/byKeywordAndCategory` (`size` 40 ; réponse `produits[]` : `libelle`, `marque`, `prix`, `prixKg`, `unitePrixVente`, `images`, `produitEan13` → `ean`, `idProduit` → `sku`). Magasins : `GET /api/service/pdvs/v4/pdvs/zone?lat=&lon=&min=10&r=` (`resultats[]` : `storeCode`, `entityLabel`...). En-têtes `x-itm-*`, `x-red-*` copiés du site. Pause de 2 s après le chargement du site, bandeau cookies jamais cliqué par script. DataDome : 403 `{url: …captcha-delivery…}` → `blocked` (vérification à valider) ; `t=bv`, « Accès temporairement restreint » ou 429 → `HardBlockError` (aucune visite pendant 30 min doublées jusqu'à 4 h, jamais de relance) | **Obligatoire** : `pdvRef` choisi dans les réglages, ou lu dans le `localStorage` (`itm-store`) si choisi sur le site |
| **Courses U** | `coursesu` | Page `https://www.coursesu.com/recherche?q=` (tuiles SFCC `[data-pid]`), extracteur générique en secours. Magasins : annuaire `/drive-france` lu depuis l'onglet Courses U (blocs `data-wrapper-store-details`, secours par liens, puis page du département `/drive-herault`) | **Obligatoire** : le plus proche du code postal est choisi automatiquement (annuaire classé par distance) ; sinon liste des 8 plus proches, magasin choisi sur le site relu après « J'ai terminé », ou URL collée (ex : `https://www.coursesu.com/drive-superu-roujan`). La page du magasin est visitée avant la recherche (de nouveau après 20 min, un nouveau contexte du navigateur, ou des produits sans prix) |

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
    components/        # retailer-badge, store-filters (réexporte views/search/filters.js)
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
- `backend/database.py` : une connexion partagée (`get_db()`) en **autocommit** : chaque requête est écrite seule, et une écriture refusée (base occupée plus de 5 s) ne laisse aucune transaction ouverte (sinon toutes les écritures suivantes échouaient jusqu'au redémarrage). Plusieurs écritures liées : `async with database.transaction() as db:` (tout ou rien, une à la fois).
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
retailers       GET    /api/retailers                                 → enseignes + magasin choisi (national, finds_stores)
                GET    /api/retailers/{intermarche|coursesu}/stores   → magasins proches (code postal requis ; coursesu : ?refresh=)
                PUT    /api/retailers/{intermarche|coursesu}/store    → choisir un magasin ({id,name,address} ou {url})
                POST   /api/retailers/coursesu/store/auto?initial=    → choisir le plus proche (AutoPickResult, toujours 200)
                POST   /api/retailers/coursesu/store/from-site?opened_only= → relire le magasin choisi sur le site
                DELETE /api/retailers/{enseigne}/store
settings        GET    /api/settings | PATCH /api/settings {show_browser}
                POST   /api/settings/location {postal_code, city?}    → 422 si code postal inconnu
                GET    /api/settings/onboarding | PATCH {seen?, done?} → assistant de premier lancement
browser         GET    /api/browser | POST /api/browser/setup {store} | POST /api/browser/setup/done
shopping_list   GET    /api/list | POST /api/list {query, quantity, product?} | PATCH /api/list/{id} | DELETE /api/list[/{id}]
basket          POST   /api/basket/compare {stores?, refresh?}
system          GET    /api/version → {version} ; pages : GET / (index.html versionné), GET /favicon.ico
status          GET    /api/status/retailers | GET /api/status/snapshot/{nom} | GET /api/status/diagnostic.zip
tracking, backup, updates : vides
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

P2. Fichiers : `js/views/search/*`, `js/views/home/cards/recent.js`, `css/{search,results}.css`, `js/views/search/aliments.json`, contenu de `js/components/store-filters.js` (`#store-filters`), `backend/services/{matching,products}.py`, `backend/scrapers/{parsing,aldi,lidl,carrefour,extract}.py`, `backend/models/products.py`, `tests/fixtures/{aldi,lidl,carrefour,generic}.py`, `tests/e2e/{catalog_p2,p2_helpers}.py`.

- **Page de résultats** (`views/search/index.js`, de haut en bas) : synthèse `#summary` (`summary.js` : meilleure offre « Le moins cher » ou « Meilleur prix au kg » selon le tri, une ligne par enseigne avec son meilleur prix pertinent, l'écart et une barre proportionnelle, « — » + icône + raison pour une enseigne en échec, « Jusqu'à 0,16 € de moins que l'offre la plus chère », place de chaque ligne gardée dès le départ) ; barre d'outils (« Tout trié | Par enseigne » et tri « Prix | Prix au kg/L | Promos | Pertinence » en boutons radio, mémorisés sur l'appareil `prixmalin.resultsView` / `prixmalin.resultsSort`, « Tout trié » par défaut sous 760 px ; « Actualiser les prix » `#refresh-btn` + « Mis à jour il y a 5 min ») ; **pas de filtres Bio / En promo / Disponible / marques** (retirés à la demande de l'utilisateur, ne pas les remettre) ; barre des enseignes sans résultat (`parts.js`, « 2 enseignes indisponibles : Intermarché — Magasin à choisir [Choisir] · Courses U — Vérification requise [Ouvrir le site] [Réessayer] ») ; puis « Tout trié » (`offers.js` : liste unique avec l'enseigne (pastille devant marque · contenance) et l'écart « +0,10 €/kg, +13 % », même EAN = une ligne « Même produit dans 3 enseignes : … » dépliable, `group.js`) ou une colonne par enseigne (`columns.js` : `h2` « Aldi, 2 produits », 5 produits puis « Voir N de plus », « 12 produits lus »), ou le bloc « Aucun produit pour … » (la synthèse est alors cachée). Toujours : seuls les produits `relevance >= 1` comptent (liste, nombre, « Le moins cher », synthèse) ; « Produits proches (N) » repliés par défaut, jamais « Le moins cher » ; indisponibles en dernier ; prix au kg/L comparés dans l'unité dominante seulement (`rank.dominantUnit`). Fonctions pures dans `rank.js` (`rank`, `summarize`, `gap`, `shorterQueries`...), testées par `js_eval`.
- **Rendu progressif** : une requête `/api/search/{enseigne}` par enseigne, toutes annulées par la recherche suivante (`AbortController`), qui repart du haut de la page ; enseigne décochée pendant la recherche = requête annulée, cochée ensuite = cherchée ; mise à jour en place par `patch.js` (enfants repérés par `data-key`, `data-patch` = mise à jour récursive, focus retrouvé par `id` ou `data-focus` ; clé d'un produit `rank.productKey` = enseigne, lien, nom, contenance, prix) : focus, défilement et images gardés ; `aria-busy` ; annonces de début et de fin (« Terminé : le moins cher est Lidl, 0,75 €, … ») ; durée habituelle « ~8 s » (`memory.js`, `prixmalin.durations`), puis « Plus long que d'habitude… [Ignorer] » après max(15 s, 1,5 × l'habitude) ; « prix d'il y a 2 h » (`fetched_at`), « Prix du 03/10 … » quand `stale` ; dans « Tout trié », page défilée : « 2 nouvelles offres » au lieu d'insérer ; retour arrière vers une recherche de moins de 15 min sans nouvelle requête ; clavier du téléphone refermé. Les enseignes sans résultat quittent la grille pour la barre (une enseigne « Magasin à choisir » qui montre des produits sans prix garde sa colonne).
- **Lignes produit** (`product-row.js`) : vignette 56 px (`width`/`height`, `loading=lazy`, `decoding=async`, dessin si l'image manque), nom sur 2 lignes (lien « nouvel onglet »), marque en casse titre, contenance, promo jamais tronquée, ancien prix barré, prix et prix au kg/L (« €/œuf » avec `count_label`), « Le moins cher » (liseré `--accent-best`, icône), indisponible barré avec « + » désactivé ; noms uniques « Ajouter Farine de blé T45 Belbake (Lidl, 0,75 €) à ma liste » ; emplacements `ext/product-badges` et `ext/product-actions`.
- **Ajout à la liste** (`add-sheet.js`) : le « + » ouvre une feuille `<dialog>` (en bas sur téléphone) : « « farine », le moins cher sera choisi » ou « Exactement ce produit chez Lidl » (par défaut), quantité, « Remplace … » ; puis « Ajouté à « farine » · Voir la liste · Annuler » (ligne retrouvée avec la clé du serveur `listKey` = `matching.query_key`, « Annuler » la retrouve par son `id`) ; produit déjà choisi = « ✓ » (« Retirer … de ma liste ») ; pastille de « Ma liste » animée. API de la liste seulement (`POST /api/list`, `PATCH`, `DELETE`). Dans un test : cliquer « + » (`[data-store=lidl]` bouton « Ajouter … ») puis `get_by_role("dialog").get_by_role("button", name="Ajouter")`.
- **Suggestions** (`autocomplete.js`) : liste `#q-suggestions` (listbox, `aria-activedescendant`, ↓ ↑ Entrée Échap, Suppr retire une recherche récente) sous `#q`, qui garde son rôle `searchbox` (pas d'`aria-expanded` : « 3 suggestions, flèches haut et bas pour choisir » est annoncé à l'ouverture) ; sources : recherches récentes (`prixmalin.recentSearches`, 8 au plus), lignes de la liste, `js/views/search/aliments.json` (300 produits courants) ; préfixe d'abord puis fréquence (`suggest`, pure). Carte d'accueil `recent.js` : « Recherches récentes » supprimables, sinon « Idées de recherche ». « Aucun produit » : un seul bloc avec recherches plus courtes, conseils et « Ajouter … à ma liste quand même ».
- **Enseignes comparées** (`filters.js`, monté dans `#store-filters`) : `fieldset` « Enseignes comparées », puces avec monogramme (A, L, C, I, U), ✓ ou « + », une rangée défilante sur téléphone ; la dernière enseigne cochée reste cochée (« Gardez au moins une enseigne cochée. »).
- **Sélecteurs de test** : `[data-store=<clé>]` = colonne (vue « Par enseigne ») ou élément de la barre des enseignes sans résultat ; `[data-summary=<clé>]` = ligne de la synthèse ; `data-testid` : `summary`, `best-offer`, `offers`, `close-products`, `unavailable`, `no-results`, `new-offers`, `add-sheet`, `recent-card` ; sur téléphone, choisir d'abord `radio` « Par enseigne » pour les colonnes.

- **Pertinence** (`services/matching.py`, fonctions pures) : le produit est la **tête du libellé**, du début jusqu'au premier complément (`COMPLEMENTS` : « à », « au », « aux », « à la », « sauce », « goût », « parfum », « saveur », « arôme », « façon », « avec », « fourré », « nappé », « pour », « en »...), marque en tête ignorée. Pertinent quand : tous les mots de la requête sont présents (pluriels, accents, casse ignorés ; mots entiers) ; le mot principal (premier mot, « bio », « pur », « petits »... sautés) est dans la tête, ou une de ses sortes en tête (`HYPONYMS` : « Spaghetti », « Coquillettes » pour « pâtes », « Basmati » pour « riz »), ou dans la marque (champ `brand`, marque connue en tête `KNOWN_BRANDS` comme « Fruit d'Or », ou marque en capitales en fin de libellé, celle-ci jamais pour un aliment : « Pizza THON » n'est pas « thon ») ; s'il est un aliment (`PRODUCT_NOUNS`, comparé avec sa forme en -é : « Pure » n'est pas « purée »), aucun autre aliment ne le précède (« Sauce tomate » n'est pas « tomate ») et « pur X » après un mot qui n'est pas une découpe (`CUTS`) est un ingrédient (« Sablés pur beurre », mais « Steak haché pur bœuf » est du bœuf) ; pas de composé (`COMPOUNDS` : « Eau de javel », « Pâte à tartiner », « Beurre de cacahuète », et avant le mot « Petit Beurre » ; l'autre mot suit le mot cherché, avant tout complément : « Eau aromatisée parfum citron » est de l'eau) ; pâté ≠ pâtes, sucré ≠ sucre ; « sans X » ; contenances de la requête retirées (`query_quantity`) ; « eau -javel ». `Matcher(query).match(name, brand)` → `Match(relevance, score, reason)`.
- **Contrat produit** (`Product`, rempli par `services/products.prepare_products`) : `relevance` = 1 pour le produit cherché (liste principale, nombre de produits, « Le moins cher », choix du panier), entre 0 et 1 pour « Produits proches » (part des mots trouvés, au plus 0,99), 0 sans rapport ; `match_score` de 0 à 1 (tri par pertinence ; pertinent **exactement** quand `match_score >= matching.RELEVANT_SCORE`, 0,75) ; `match_reason` (`missing`, `complement`, `other_product`, `compound`, `excluded`, `unrelated`, nul si pertinent) ; `bio`, `store_brand` (vrai / faux / nul si marque inconnue ; `STORE_BRANDS`, à compléter) ; `unit_price` + `unit` (`kg`, `L` ou `pièce`) + `count_label` (« œuf » pour « €/œuf ») ; `old_price` ; `ean` (vérifié par `valid_ean`, nul sinon) et `sku`. Ordre : pertinents par prix (sans prix puis indisponibles en dernier), puis les proches du plus proche au moins proche. Doublons (`dedup_key`) : l'EAN, sinon (page produit, nom, contenance, prix).
- **Contenances** (`scrapers/parsing.py`) : 1L5, 6x1L5, « 6 bouteilles de 1,5 L », « pack/lot de N … », « + 1 offert », « + 20 % gratuit », « + 50 cl offerts », « au kg », « la pièce », comptes (« x12 », « 12 œufs », « 3 x 4 yaourts », « lot de 6 ») ; prix unitaires normalisés (« 0,35 €/100gr », « 2,49 € / 500 g », « 1 kg = 12 € », « 0,25 €/œuf ») ; un prix unitaire du site à plus de 3 fois du calcul est remplacé et journalisé ; jamais de €/kg comparé à des €/L.
- **Pages** (`scrapers/extract.py`) : une seule page de plus, seulement dans la première moitié du délai de l'enseigne (`PageBudget`, `config.scraper_timeout`), après une pause de 0,8 s ; fusion sans doublon (`merge_pages`). Vignettes : taille `medium`/`small` préférée (`first_url`), Carrefour en 280x280.
- **Tests** : `tests/test_p2_{matching,parsing,scrapers,api,frontend_static}.py`, `tests/e2e/test_p2_{relevance,rank,results,progressive,add,suggest,layout}.py` (axe en clair et en sombre, aucun défilement horizontal à 360 et 390 px pour les échelles 0,9 à 1,6, CLS < 0,1, focus gardé, annulation) ; `tests/e2e/catalog_p2.py` (« huile de tournesol » avec thon, sardines, chips et mayonnaise moins chers et « Lesieur Huile de tournesol » ; même EAN Maille chez Carrefour, Lidl et Intermarché ; crème fraîche en €/L et en €/kg ; bio, promo, indisponible ; « tomate » ; « pois chiches » avec vignettes `https://images.prixmalin.test/…` servies par `page.route` ; œufs), sans les mots cherchés par les autres tests (farine, blé, eau, lait, pirate).

### Navigateur et moteur

P3. Fichiers : `backend/browser.py`, `backend/real_chrome.py`, `backend/services/{search,warmup,circuit}.py`, `backend/repos/cache.py`, `backend/scrapers/{base,common,intermarche}.py`, `backend/api/{search,browser}.py`, `backend/models/{search,browser}.py`, `js/views/settings/sections/advanced.js`, `tests/fixtures/intermarche.py`, bloc « délais » de `config.py`, `docs/verification-intermarche.md`. Complète la puce « Navigateur » de l'architecture : il y a désormais **deux navigateurs**.

- **Navigateur partagé** (Aldi, Lidl, Carrefour, Courses U) : celui décrit plus haut (Playwright + stealth, invisible, profil `data/browser-profile`). Fenêtre visible seulement en réglage ou avec « Montrer le navigateur ». Fermée par l'utilisateur : `show_browser` repasse à faux (enregistré), le cache de l'enseigne ouverte est vidé, la recherche suivante relance en invisible (`closed_by_user`, `setup_store` dans `BrowserStatus`). User-agent sans `HeadlessChrome` mémorisé dans `data/browser-ua.json` (par canal et version : un seul lancement au démarrage) et appliqué seulement en invisible. Onglets Aldi et Courses U invisibles « allégés » (images, médias, polices, publicités bloqués ; `PRIXMALIN_LIGHT=0` pour tout charger), jamais Carrefour ni Intermarché. Les cookies `intermarche.com` et `captcha-delivery.com` de ce profil sont effacés une fois (fichier témoin `prixmalin-intermarche-oublie.txt`). Il n'ouvre **jamais** intermarche.com.
- **Fenêtre Chrome dédiée** (`config.REAL_CHROME_STORES`, `intermarche` par défaut ; `PRIXMALIN_REAL_CHROME=` vide = ancien fonctionnement, déconseillé) : `backend/real_chrome.py`. Le Chrome installé (sinon Edge ; `PRIXMALIN_CHROME_PATH` pour forcer) lancé comme un programme ordinaire et détaché, profil `data/chrome-intermarche`, avec seulement `--remote-debugging-address=127.0.0.1 --remote-debugging-port=<port libre> --user-data-dir=… --no-first-run --no-default-browser-check` (+ `--start-minimized`, ignoré par Chrome : la fenêtre est réduite par CDP quand PrixMalin la lance pour une recherche). **Pas** `--remote-debugging-port=0` : Chrome met alors `navigator.webdriver` à vrai ; le port est noté dans `<profil>/PrixMalinDebugPort` pour retrouver la fenêtre après un redémarrage de PrixMalin. patchright `connect_over_cdp(no_defaults=True)`, `browser.contexts[0]`, onglet existant ; aucun stealth, aucun réglage modifié, jamais invisible. « Ouvrir le site » la remet en fenêtre normale au premier plan ; une recherche ne la met jamais devant. Fermée par l'utilisateur : rouverte (réduite) à la recherche suivante. Démarrage dans sa propre tâche partagée (`RealChrome._start_task`) : une recherche annulée ne l'interrompt pas, la fenêtre est quand même réduite. Pas de capture d'écran de cette fenêtre (HTML seul).
- **`browser.run(key, fn, *args, timeout=, priority=)`** : une tâche à la fois par enseigne (`_Slot`), file par priorité `interactive` > `basket` > `background` puis arrivée, attente limitée à `QUEUE_TIMEOUT_SECONDS` (90 s, `QueueTimeout`), `timeout` ne couvre que le travail ; espacement `MIN_REQUEST_INTERVAL_SECONDS` (1,1 s pour Intermarché) + 0 à `REQUEST_JITTER_SECONDS` ; aucun appel pendant un blocage dur (`HardBlockError` immédiat) : la pause démarre sur la boucle du navigateur dès la réponse lue (`HardBlocks.start`, enregistrée ensuite par `flush`), donc les appels qui attendaient l'onglet n'envoient rien et ne la doublent pas ; après une vérification anti-robot, ceux qui attendaient échouent aussitôt avec la même `BlockedError` (`_refuse_after_block`) ; annulé sur la boucle du navigateur quand l'appelant l'est. Démarrage, relance et arrêt dans leur propre tâche (`asyncio.shield`) : un délai côté appelant ne les coupe pas ; navigateur à moitié lancé refermé ; profil verrouillé → « Le profil du navigateur PrixMalin est déjà utilisé… » sans essayer d'autre canal. Page d'une recherche bloquée, trop lente ou en erreur gardée dans `data/debug/{clé}-{AAAAMMJJ-HHMMSS}-{statut}.html|png` (réponses brutes `.json|.txt` à côté ; 5 par enseigne, tous types).
- **DataDome** (`common.classify_datadome`, `classify_page`, `intermarche.check_answer`, fonctions pures) : URL ou iframe `captcha-delivery.com` → `captcha` (`BlockedError`, à valider dans la fenêtre) ; `t=bv`, « Accès temporairement restreint », « You have been blocked » ou HTTP 429 → `hard_block` (`HardBlockError`, jamais relancé). Titre de challenge Cloudflare ancré (`^(just a moment|un instant…)`) et seulement avec les marques d'une page Cloudflare.
- **Pauses** (`services/circuit.py`) : blocage dur = aucune visite pendant 30 min, doublées à chaque nouveau blocage jusqu'à 4 h (remis à 30 min après 24 h sans blocage), gardé dans les préférences `p3.blocks` ; « Réessayer maintenant » (`DELETE /api/browser/blocks/{clé}`) lève la pause sans oublier son doublement. Disjoncteur en mémoire par (enseigne, magasin) : 10 min après `blocked` ou `store_required` (ou jusqu'à `setup/done`, ou un autre magasin), 2 min après 2 délais dépassés de suite ; une recherche relancée par l'utilisateur passe, sauf blocage dur et vérification Intermarché non validée ; jamais le panier ni le fond. `search.retailer_state(key)` (async) → `RetailerState`, `search.reset_circuit(key)`.
- **`search.search_store`** : cache frais 6 h (« aucun produit » 30 min) ; entre 1 h et 6 h servi puis relu en fond (`background`, jamais pour Intermarché) ; site en échec → derniers prix de moins de 7 jours, `stale=True`, `problem`, message « Prix du 03/10 à 14 h (Carrefour : vérification requise) » ; recherches identiques simultanées mutualisées ; nouvel essai seulement après une erreur de navigation (onglet neuf), jamais pour Intermarché ; délai par enseigne `config.scraper_timeout(key)` (`PRIXMALIN_TIMEOUT_<CLE>`, 60 s par défaut pour Courses U et Intermarché) ; messages français sans détail technique (« Le site Aldi met trop de temps à répondre. »). Rien en cache pour une enseigne sans magasin dont aucun produit n'a de prix. `StoreResult` : `fetched_at`, `source`, `stale`, `problem`, `retry_after`.
- **Cache** (`repos/cache.py`) : la lecture ne supprime rien ; `get_cached` → `(produits, heure)` frais, `get_entry(key, max_age)` → `CacheEntry(products, created_at, source)` ; purge des entrées de plus de 7 jours au démarrage puis chaque jour (hook `warmup`).
- **Préchauffage** (`services/warmup.py`) : Carrefour et Lidl seulement, si l'enseigne peut répondre (magasin choisi si nécessaire, ni vérification ni blocage depuis 24 h). Jamais Intermarché.
- **API** : `GET /api/search*` annule la recherche si le client est parti (contrôle toutes les 0,5 s, réponse 499) ; `POST /api/browser/setup/done` ne vide que le cache et le disjoncteur de l'enseigne ouverte (aussi quand l'utilisateur a fermé sa fenêtre avant ; rien quand rien n'est montré ; navigateur ouvert sans enseigne → enseignes du navigateur partagé seulement) ; `GET /api/browser` → `BrowserStatus` (+ `windows`, `blocked_until`) ; `DELETE /api/browser/blocks/{clé}`.
- **Tests** : `tests/test_p3_*.py` ; la fenêtre dédiée tourne dans un vrai Chromium visible (`tests/p3_chrome.py` lance un Xvfb s'il n'y a pas d'écran ; binaire `PRIXMALIN_CHROME_PATH` ou le Chromium de Playwright) ; `test_p3_fingerprint.py` compare l'empreinte de la fenêtre dédiée à un Chrome sans automatisation (sonde de la recherche DataDome).
- Variables : `PRIXMALIN_REAL_CHROME`, `PRIXMALIN_CHROME_PATH`, `PRIXMALIN_CHROME_ARGS` (tests), `PRIXMALIN_TIMEOUT_<CLE>`, `PRIXMALIN_QUEUE_TIMEOUT`, `PRIXMALIN_LIGHT`.

### Enseignes et magasins

P4. Fichiers : `backend/scrapers/coursesu.py`, `backend/services/{settings,stores,health}.py`, `backend/repos/{settings_store,scrape_log,stores_cache}.py`, `backend/api/{retailers,settings,status}.py`, `backend/models/{settings,status}.py`, migrations `p4_001_scrape_log`, `p4_002_stores_cache`, `js/views/settings/sections/{location,stores}.js`, `js/views/{status,onboarding}/*`, `js/views/home/cards/{status,setup}.js`, `js/features/setup-banner.js`, `css/{status,onboarding,stores}.css`, `tests/fixtures/coursesu.py`, `tests/e2e/catalog_p4.py`.

- **Réglages** (`services/settings.py`) : toute écriture passe par `settings.modify(fn)` (lecture, modification, écriture sous un verrou). `geocode(cp)` : geo.api.gouv.fr puis IGN, `[]` = code postal inconnu (422, rien n'est enregistré), `GeocodingUnavailable` = aucun service (code postal enregistré sans commune) ; tests avec `settings.HTTP_TRANSPORT = httpx.MockTransport(...)`. Validation : identifiant de magasin `^\d{2,8}$`, nom et adresse ≤ 200, URL Courses U `https://www.coursesu.com/…` ≤ 300, commune ≤ 100.
- **Magasins Courses U** (`services/stores.py`, `scrapers/coursesu.py`) : `fetch_store_directory` lit `/drive-france` par `fetch()` dans l'onglet (page chargée en vrai si une vérification répond, `BlockedError` sinon) ; `parse_store_directory` (blocs ; nom = valeur de `data-store-name`, sinon texte de l'élément, sinon tiré du lien, jamais vide ; liens `?…`/`#…` acceptés), puis sous 50 magasins `cards_to_stores` (liens) avec la page gardée dans `data/debug/coursesu-stores.html`, puis la page du département (`department_name_of` : nom enregistré, sinon déduit du code postal ; gardée dans `coursesu-stores-departement.html` seulement si elle ne donne rien). Annuaire en cache 7 jours (table `stores_cache`, seulement s'il a au moins 50 magasins ; le dernier lu sert toujours à nommer un magasin relu), table des communes geo.api.gouv.fr 30 jours (`build_commune_index`, `locate`, `rank_stores` : distance, code CEDEX placé par sa commune, sinon même code postal puis même département). Les fixtures de l'annuaire sont **synthétiques** : à remplacer par un extrait réel après le premier essai sur le PC.
- **Choix automatique** : `auto_pick_coursesu()` choisit le plus proche (`StoreSelection.auto = true`, `distance_km`) sauf si l'utilisateur a choisi le sien ; si la localisation change pendant la lecture, le choix est refait pour la nouvelle ; le front l'appelle à chaque nouveau code postal ou commune (un appel pendant qu'un autre tourne est rejoué à la fin) et une fois au chargement (`initial=true` : une seule fois par code postal, jamais après « Retirer », préférences `p4.coursesu`). Après « Ouvrir le site » sur Courses U puis « J'ai terminé », `read_back_coursesu(opened_only=True)` lit `window.storeLink` ou l'identifiant du magasin (`storeId`, `tc_vars`, `dataLayerNC`) et l'enregistre (`CoursesUScraper.setup_url` note l'ouverture).
- **Journal et état** (`services/health.py`) : le hook `search_finished` écrit chaque recherche dans `scrape_log` (purge à 30 jours) ; `retailer_health()` (pure) donne Prêt, Dégradé (méthode de secours), Échec récent, Probablement cassé (3 recherches vides ou en erreur sur des requêtes différentes), Vérification requise, Magasin à choisir, Pas encore testé. Les résultats du cache sont journalisés mais ne comptent pas ; une réponse « Magasin à choisir » pour un autre magasin que l'actuel non plus ; magasin enregistré mais inconnu du site : « Magasin à choisir » avec `last_error` (Réglages : « Magasin à changer », liste ouverte). `all_health` lit par enseigne les 500 dernières recherches et calcule 7 jours / dernière réussite en SQL (`scrape_log.totals`). Diagnostic zip : journaux `data/logs/*`, 20 dernières captures, état, versions, réglages sans données personnelles ; jamais `browser-profile`, cookies ni base.
- **Front** : `views/status/shared.js` (état des enseignes `loadHealth()`, pastilles `statePill`, `openSite(key)` avec confirmation depuis un téléphone, choix automatique, relecture après « J'ai terminé ») ; `features/setup-banner.js` (bandeau interrogé toutes les 3 s, texte selon `is_local`, confirmation des boutons `[data-setup]` depuis un téléphone, ouverture de l'assistant au premier lancement) ; `#/etat`, `#/bienvenue` ; cartes d'accueil `setup` (`primary`) et `status`.
- **Tests** : `tests/test_p4_*.py`, `tests/e2e/test_p4_*.py` ; `tests/e2e/catalog_p4.py` simule l'annuaire Courses U, la table des communes et le magasin affiché par le site (`catalog_p4.SITE_STORE`), vide le journal entre deux tests et coupe l'ouverture automatique de l'assistant (`settings.AUTO_ONBOARDING`, ou `PRIXMALIN_ONBOARDING=0`).

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
