# PrixMalin - Comparateur de prix supermarchés français

## Objectif

Application web permettant de comparer les prix de produits alimentaires courants entre différents supermarchés français. L'utilisateur entre simplement un nom de produit (ex: "Huile de tournesol", "Farine", "Eau", "Vinaigre") et l'app affiche les prix trouvés chez chaque enseigne, triés du moins cher au plus cher.

## Enseignes cibles

| Enseigne | URL de recherche | Méthode | Notes |
|----------|-----------------|---------|-------|
| **Aldi** | `https://www.aldi.fr/recherche.html?query={query}` | Playwright (contenu JS) | Prix nationaux, pas de sélection de magasin nécessaire |
| **Carrefour** | `https://www.carrefour.fr/s?q={query}` | Playwright (Cloudflare 403) | Peut nécessiter un magasin pour les prix locaux |
| **Courses U** (Hyper U / Super U) | `https://www.coursesu.com/recherche?q={query}` | Playwright | **Prix visibles uniquement après sélection d'un magasin** — nécessite de configurer un magasin via cookie/session |
| **Intermarché** | `https://www.intermarche.com/recherche/{query}` | Playwright | **Prix liés au magasin sélectionné** — même contrainte que Courses U |

## Architecture technique

### Stack recommandé

- **Backend** : Python 3.11+
- **Scraping** : Playwright (async) — tous les sites utilisent du rendu JS ou du Cloudflare
- **API** : FastAPI
- **Frontend** : Interface web simple (HTML/CSS/JS ou React)
- **Base de données** : SQLite (stockage produits, prix historiques, magasins)
- **Cache** : Cache fichier ou Redis pour éviter de re-scraper trop souvent (TTL ~6h)

### Structure du projet

```
prixmalin/
├── CLAUDE.md
├── requirements.txt
├── backend/
│   ├── main.py              # FastAPI app
│   ├── config.py             # Configuration (code postal, magasins préférés)
│   ├── database.py           # SQLite models et helpers
│   ├── scrapers/
│   │   ├── base.py           # Classe abstraite BaseScraper
│   │   ├── aldi.py           # Scraper Aldi
│   │   ├── carrefour.py      # Scraper Carrefour
│   │   ├── coursesu.py        # Scraper Courses U
│   │   └── intermarche.py    # Scraper Intermarché
│   ├── models.py             # Pydantic models (Product, Price, Store)
│   └── services/
│       ├── search.py         # Orchestration de la recherche multi-enseigne
│       └── location.py       # Géolocalisation / sélection magasins
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── tests/
    └── test_scrapers.py
```

## Fonctionnalités

### V1 - MVP

1. **Recherche simple** : L'utilisateur tape un nom de produit → les scrapers cherchent en parallèle sur chaque enseigne
2. **Affichage comparatif** : Tableau/cartes montrant pour chaque enseigne les résultats trouvés avec :
   - Nom du produit
   - Prix (€)
   - Prix au kg/L si disponible
   - Image du produit si disponible
   - Lien direct vers la page produit
3. **Tri** : Par prix croissant par défaut
4. **Liste de courses** : Pouvoir ajouter plusieurs produits et voir le total par enseigne
5. **Configuration lieu** : Entrer un code postal pour paramétrer les magasins de proximité (surtout pour Courses U et Intermarché)

### V2 - Améliorations

- Historique des prix (graphique d'évolution)
- Notifications si un prix baisse
- Suggestions de produits similaires moins chers
- Mode panier : calculer où faire ses courses pour le panier le moins cher globalement

## Détails d'implémentation des scrapers

### Pattern commun (BaseScraper)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class ScrapedProduct:
    name: str
    price: float | None          # Prix en euros
    price_per_unit: str | None   # Ex: "2,50 €/kg"
    image_url: str | None
    product_url: str
    store_name: str

class BaseScraper(ABC):
    @abstractmethod
    async def search(self, query: str) -> list[ScrapedProduct]:
        """Recherche un produit et retourne la liste des résultats."""
        pass
    
    @abstractmethod
    async def setup_location(self, postal_code: str) -> bool:
        """Configure le magasin le plus proche pour cette enseigne."""
        pass
```

### Aldi (le plus simple)

- URL : `https://www.aldi.fr/recherche.html?query={query}`
- Les prix sont **nationaux** (pas de variation par magasin)
- Le contenu est rendu en JavaScript → attendre le sélecteur des résultats
- Sélecteurs à identifier : conteneur produit, nom, prix
- **Stratégie** : `page.goto()` → `page.wait_for_selector()` → parser les éléments

### Carrefour

- URL : `https://www.carrefour.fr/s?q={query}`
- Renvoie 403 sans headers/cookies appropriés
- **Stratégie** : Playwright en mode headed ou avec `stealth` plugin pour contourner Cloudflare
- Alternative : intercepter les requêtes API internes (XHR) qui renvoient du JSON structuré — plus fiable si on identifie l'endpoint

### Courses U

- URL : `https://www.coursesu.com/recherche?q={query}`
- **Les prix ne s'affichent qu'après sélection d'un magasin**
- Nécessite de persister un cookie/session de magasin
- **Stratégie** : 
  1. Naviguer vers la page d'accueil
  2. Sélectionner un magasin via le sélecteur de magasin (code postal)
  3. Sauvegarder le contexte navigateur (cookies)
  4. Réutiliser ce contexte pour les recherches suivantes

### Intermarché

- URL : `https://www.intermarche.com/recherche/{query}`
- Même contrainte que Courses U — prix liés au magasin
- **Stratégie** : Similaire à Courses U, configurer le magasin puis scraper

## Gestion de la géolocalisation

```python
# L'utilisateur entre son code postal au premier lancement
# Le système identifie les magasins les plus proches pour chaque enseigne

# Pour Aldi : pas nécessaire (prix nationaux)
# Pour Carrefour : optionnel mais recommandé  
# Pour Courses U : OBLIGATOIRE pour voir les prix
# Pour Intermarché : OBLIGATOIRE pour voir les prix

# Stocker la config dans SQLite ou un fichier JSON local
{
    "postal_code": "34000",
    "stores": {
        "coursesu": {"store_id": "xxx", "store_name": "Super U Montpellier"},
        "intermarche": {"store_id": "yyy", "store_name": "Intermarché Montpellier"},
        "carrefour": {"store_id": "zzz", "store_name": "Carrefour Montpellier"}
    }
}
```

## Robustesse et bonnes pratiques

### Anti-détection

- Utiliser `playwright-stealth` pour éviter la détection bot
- Varier les user-agents
- Ajouter des délais aléatoires entre les requêtes (1-3s)
- Ne pas scraper plus d'une fois par produit par 6h (cache)
- Réutiliser les contextes navigateur (cookies persistants)

### Gestion d'erreurs

- Si un scraper échoue, afficher les résultats des autres (dégradation gracieuse)
- Retry avec backoff exponentiel (max 2 retries)
- Logger les erreurs pour debug
- Timeout par scraper : 15 secondes max

### Performance

- Lancer les scrapers en **parallèle** (asyncio.gather)
- Cache des résultats (SQLite ou fichier) avec TTL de 6h
- Possibilité de rafraîchir manuellement

## API Endpoints

```
GET  /api/search?q={query}                    → Recherche un produit sur toutes les enseignes
GET  /api/search?q={query}&stores=aldi,carrefour → Filtrer par enseigne
POST /api/config/location                      → Configurer le code postal
GET  /api/config/stores                        → Voir les magasins configurés
GET  /api/products                             → Liste des produits suivis
POST /api/products                             → Ajouter un produit à suivre
GET  /api/products/{id}/prices                 → Historique des prix d'un produit
```

## Interface utilisateur

### Page principale

- Barre de recherche en haut (grande, centrée)
- Bouton "Configurer ma localisation" (code postal)
- Résultats en cartes côte à côte par enseigne
- Badge couleur par enseigne (Aldi=bleu, Carrefour=bleu foncé, U=rouge, Intermarché=jaune)
- Indication du meilleur prix en vert

### Design

- Clean, moderne, responsive
- Couleurs : fond clair, accents par enseigne
- Mobile-first (beaucoup d'usage mobile pour les courses)

## Installation et lancement

```bash
# Installer les dépendances
pip install -r requirements.txt
playwright install chromium

# Configurer le code postal (première fois)
# Se fait via l'interface web

# Lancer
python -m backend.main
# → http://localhost:8000
```

## Dépendances (requirements.txt)

```
fastapi>=0.100.0
uvicorn>=0.23.0
playwright>=1.40.0
playwright-stealth>=1.0.0
beautifulsoup4>=4.12.0
pydantic>=2.0.0
aiosqlite>=0.19.0
httpx>=0.25.0
```

## Notes importantes

- **Légalité** : Ce projet est à usage personnel uniquement. Le scraping de ces sites peut violer leurs CGU. Ne pas distribuer ni commercialiser.
- **Fragilité** : Les sélecteurs CSS/XPath peuvent casser si les sites changent leur HTML. Prévoir un système de monitoring qui alerte si un scraper ne retourne plus de résultats.
- **Commencer petit** : Implémenter Aldi en premier (le plus simple), puis ajouter les autres un par un.
- **Alternative API** : Avant de scraper, vérifier si les sites ont des API internes (requêtes XHR dans l'onglet Network du navigateur). Les API retournent du JSON structuré et sont plus stables que le HTML.
