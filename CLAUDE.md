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
- **Frontend** : HTML/CSS/JS sans build (`frontend/`), mobile-first, modules ES natifs + routeur par hash (`#/recherche?q=farine`, `#/liste`, `#/reglages`) ; les anciens liens `/?q=farine` sont redirigés vers `#/recherche?q=farine`
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
  main.py              # FastAPI : lifespan, app.include_router(api_router), index, fichiers statiques ; python -m backend.main
  config.py            # chemins (data/), port, timeouts, variables PRIXMALIN_*
  browser.py           # BrowserManager (thread dédié, profil persistant, mode visible)
  database.py          # SQLite : cache, réglages, liste de courses
  models.py            # modèles Pydantic
  api/                 # routes HTTP, un APIRouter par domaine, toutes sous /api
    __init__.py        # api_router = APIRouter(prefix="/api") + liste ROUTERS
    common.py          # get_scraper(key) (404 si enseigne inconnue), logger
    search.py          # /search, /search/{enseigne}
    retailers.py       # /retailers, magasins Intermarché, choix du magasin
    settings.py        # /settings, /settings/location
    browser_routes.py  # /browser, /browser/setup[/done] (≠ backend/browser.py)
    shopping_list.py   # /list, /basket/compare
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
frontend/              # servi sous /static (Cache-Control: no-cache), index.html sous /
  index.html           # coquille : barre du haut (A−/A+, code postal, réglages), bandeau « J'ai terminé »,
                       #   nav principale (générée par le routeur), <main id="view">, toast
  css/
    base.css           # variables, reset, boutons, chips, badges/couleurs d'enseigne, filtres, toast, utilitaires
    layout.css         # barre du haut, bandeau, nav, main, responsive
    search.css list.css settings.css   # une feuille par vue (search.css contient aussi les lignes produit)
  js/
    main.js            # démarrage : taille du texte, chargements, registerView(...), start(), bandeau
    router.js          # registerView, start, navigate, currentRoute, refreshNav, hrefFor
    api.js             # api(path, {method, body}) → JSON, Error(message du serveur) sinon
    util.js            # escapeHtml, euros, unitText, toast, debounce
    store.js           # état partagé (retailers, settings, browser, list, enabled), subscribe/notify,
                       #   loadSettings, loadList, actions partagées (addToList, openSetup, endSetup)
    textsize.js        # boutons A− / A+ (localStorage prixmalin.textScale)
    components/        # morceaux réutilisés par plusieurs vues
      productRow.js retailerBadge.js storeFilters.js
    views/             # une vue = un fichier = une route
      search.js        # #/recherche?q=  (formulaire, filtres, résumé, colonnes, +, tri, actualiser)
      list.js          # #/liste         (liste de courses, comparaison du panier)
      settings.js      # #/reglages?enseigne=  (localisation, magasins, navigateur, « Ouvrir le site »)
tests/                 # pytest (dont scénarios Chromium avec sites simulés et test_frontend_e2e.py)
lancer.bat             # lanceur Windows
```

### Ajouter une vue (frontend)

1. Créer `frontend/js/views/<nom>.js` qui exporte par défaut un objet :
   ```js
   export default {
       name: "historique",                 // identifiant unique
       path: "/historique",                // route : #/historique?x=...
       title: "Historique",                // ou (params) => "..." ; document.title = « … · PrixMalin »
       nav: { label: "Historique", order: 30 },  // facultatif ; badge: () => nombre ; keepParams: true
       render(container, params) { ... },  // construit la vue DANS container (neuf à chaque affichage)
       update(params) { ... },             // facultatif : même vue, autres paramètres
       destroy() { ... },                  // facultatif : se désabonner (subscribe renvoie la fonction)
   };
   ```
2. Ajouter dans `frontend/js/main.js` : `import historyView from "./views/historique.js";` et `registerView(historyView);`.
3. Styles dans `frontend/css/<nom>.css` + une ligne `<link>` dans `index.html`.

Règles : une vue ne touche que le DOM de son `container` (`container.querySelector`, jamais `document.getElementById` pour ses propres éléments) ; la coquille (puce code postal, bandeau, badge de la nav) se met à jour via `store.js` (`notify("list")`, `setSettings()`...). L'état à garder d'une visite à l'autre vit dans le module de la vue (variables du module), les données partagées dans `store`. Naviguer : `navigate("/liste")` ou un lien `href="#/liste"`. Inutile de changer `?v=4` dans `index.html` : tout `/static` est servi en `Cache-Control: no-cache` (revalidé à chaque chargement).

### Ajouter une route (backend)

- Dans un domaine existant : ajouter la fonction au routeur du fichier `backend/api/<domaine>.py` (`@router.get("/chemin")`, le préfixe `/api` est ajouté par `api_router`).
- Nouveau domaine : créer `backend/api/<domaine>.py` avec `router = APIRouter()`, puis l'importer et l'ajouter à `ROUTERS` dans `backend/api/__init__.py`.
- La logique va dans `backend/services/`, les modèles dans `backend/models.py` (`response_model=`), et un test dans `tests/test_api.py` (le test `test_api_routes` liste toutes les URL : le compléter).

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
python -m pytest                # les tests navigateur (scrapers, interface) sont ignorés si Chromium est absent
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
