// Fixed table of the routes of the app (stable: a lot fills its view module,
// it does not add or rename routes here). Views with `enabled = false` are
// hidden: their address leads to the home page.

import * as basket from "./views/basket/index.js";
import * as home from "./views/home/index.js";
import * as list from "./views/list/index.js";
import * as onboarding from "./views/onboarding/index.js";
import * as product from "./views/product/index.js";
import * as search from "./views/search/index.js";
import * as settings from "./views/settings/index.js";
import * as shopping from "./views/shopping/index.js";
import * as status from "./views/status/index.js";
import * as priceHistory from "./views/tracking/history.js";
import * as tracking from "./views/tracking/index.js";

export const DEFAULT_PATH = "/";

export const ROUTES = [
    { name: "home", path: "/", view: home }, // P1: accueil, entrée « Rechercher »
    { name: "search", path: "/recherche", view: search }, // P2: #/recherche?q=farine
    { name: "list", path: "/liste", view: list }, // P5: « Ma liste » et comparaison du panier
    { name: "basket", path: "/panier", view: basket }, // P5
    { name: "shopping", path: "/courses", view: shopping }, // P5: mode « En magasin »
    { name: "tracking", path: "/suivis", view: tracking }, // P6
    { name: "history", path: "/historique", view: priceHistory }, // P6
    { name: "product", path: "/produit/:store/:key", view: product }, // P6
    { name: "settings", path: "/reglages", view: settings }, // P1: #/reglages?enseigne=intermarche
    { name: "status", path: "/etat", view: status }, // P4: état des enseignes
    { name: "onboarding", path: "/bienvenue", view: onboarding }, // P4: premier lancement
];
