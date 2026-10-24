// Shared state of the app, its loaders and the actions used by several views.
//
// Events (on(event, fn) / emit(event, data), from core/events.js):
//   settings:changed   state.settings or state.retailers changed (location, stores)
//   browser:changed    state.browser changed (setup mode, visible window...)
//   list:changed       state.list changed
//   filters:changed    a retailer was ticked or unticked (data: its key)
//   results:stale      results may be outdated (store chosen, setup done)
//   search:requested   { query, refresh } a search was asked (form, suggestion)
//   search:reset       back to the home page: forget the current search
//   search:started     { query }
//   search:result      { query, store, result } one retailer answered
//   search:done        { query } every retailer answered
//   route:changed      { name, path, params } a view was shown
//   api:offline / api:online / api:unauthorized (core/api.js)
//   "*"                any event

import { api } from "./api.js";
import { emit, on } from "./events.js";
import { notify } from "./ui.js";

export { emit, on };

export const state = {
    settings: null, // GET /api/settings
    retailers: [], // GET /api/retailers (display order)
    browser: null, // GET /api/browser
    list: [], // GET /api/list
    enabled: new Set(), // retailers ticked in the filters
    // Current search (views/search): query, results by retailer...
    search: { query: "", results: {}, token: 0, sort: "price", expanded: {} },
};

export function retailer(key) {
    return state.retailers.find((r) => r.key === key) || { key, label: key };
}

// ---------------------------------------------------------------- loaders

export async function loadSettings() {
    const [retailers, settings, browser] = await Promise.all([
        api("/api/retailers"),
        api("/api/settings"),
        api("/api/browser"),
    ]);
    state.retailers = retailers;
    state.settings = settings;
    state.browser = browser;
    emit("settings:changed");
    emit("browser:changed");
}

export function setSettings(settings) {
    state.settings = settings;
    emit("settings:changed");
}

export function setBrowser(status) {
    state.browser = status;
    emit("browser:changed");
}

export async function loadList() {
    let list = null;
    try {
        list = await api("/api/list");
    } catch {
        // offline or refused: an empty list
    }
    // An answer cut short (page reloaded at once) gives null, never a list
    state.list = Array.isArray(list) ? list : [];
    emit("list:changed");
}

// ---------------------------------------------------------------- retailers ticked in the filters

const ENABLED_KEY = "prixmalin.enabled";

export function loadEnabled() {
    let saved = null;
    try {
        saved = JSON.parse(localStorage.getItem(ENABLED_KEY));
    } catch {
        /* no saved choice */
    }
    const keys = state.retailers.map((r) => r.key);
    state.enabled = new Set(Array.isArray(saved) ? saved.filter((k) => keys.includes(k)) : keys);
    if (state.enabled.size === 0) state.enabled = new Set(keys);
}

// Ticks or unticks a retailer (at least one stays ticked). Returns its new state.
export function setEnabled(key, enabled) {
    if (enabled) state.enabled.add(key);
    else if (state.enabled.size > 1) state.enabled.delete(key);
    else return true;
    try {
        localStorage.setItem(ENABLED_KEY, JSON.stringify([...state.enabled]));
    } catch {
        /* not saved, still applied */
    }
    emit("filters:changed", key);
    return enabled;
}

// ---------------------------------------------------------------- shared actions

// Asks for a search of `query` (handled by views/search)
export function requestSearch(query, { refresh = false } = {}) {
    emit("search:requested", { query, refresh });
}

// Adds a query (and optionally the product chosen for one retailer) to the list
export async function addToList(query, product = null, quantity = 1) {
    const item = await api("/api/list", { method: "POST", body: { query, quantity, product } });
    await loadList();
    return item;
}

// Shows the retailer site in the PrixMalin browser window ("Ouvrir le site")
export async function openSetup(key) {
    notify(`Ouverture de ${retailer(key).label}…`);
    try {
        setBrowser(await api("/api/browser/setup", { method: "POST", body: { store: key } }));
        notify(
            `${retailer(key).label} est ouvert dans la fenêtre du navigateur PrixMalin. Cliquez sur « J'ai terminé » ensuite.`,
        );
    } catch (err) {
        notify(err.message, { type: "error" });
    }
}

// Ends the setup mode ("J'ai terminé" in the banner)
export async function endSetup() {
    try {
        setBrowser(await api("/api/browser/setup/done", { method: "POST" }));
        notify("C'est noté, les recherches reprennent en arrière-plan");
        emit("results:stale");
    } catch (err) {
        notify(err.message, { type: "error" });
    }
}
