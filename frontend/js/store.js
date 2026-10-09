// Shared state of the app and a tiny publish/subscribe.
//
// Topics:
//   "settings"      store.retailers / store.settings changed (location, stores)
//   "browser"       store.browser changed (setup mode, visible window...)
//   "list"          store.list changed
//   "enabled"       store.enabled changed (retailers ticked in the filters)
//   "results-stale" search results may be outdated (store chosen, setup done)
//   "*"             any of the above
//
// Views subscribe in render() and unsubscribe in destroy().

import { api } from "./api.js";
import { toast } from "./util.js";

export const store = {
    retailers: [],
    settings: null,
    browser: null,
    list: [],
    enabled: new Set(),
};

const listeners = new Map();

// Returns the function that unsubscribes
export function subscribe(topic, fn) {
    if (!listeners.has(topic)) listeners.set(topic, new Set());
    listeners.get(topic).add(fn);
    return () => listeners.get(topic)?.delete(fn);
}

export function notify(topic, detail) {
    const fns = [...(listeners.get(topic) || [])];
    if (topic !== "*") fns.push(...(listeners.get("*") || []));
    for (const fn of fns) {
        try {
            fn(detail, topic);
        } catch (err) {
            console.error(err);
        }
    }
}

export function retailer(key) {
    return store.retailers.find((r) => r.key === key) || { key, label: key };
}

// ---------------------------------------------------------------- loaders

export async function loadSettings() {
    const [retailers, settings, browser] = await Promise.all([
        api("/api/retailers"), api("/api/settings"), api("/api/browser"),
    ]);
    store.retailers = retailers;
    store.settings = settings;
    store.browser = browser;
    notify("settings");
    notify("browser");
}

export function setSettings(settings) {
    store.settings = settings;
    notify("settings");
}

export function setBrowser(status) {
    store.browser = status;
    notify("browser");
}

export async function loadList() {
    try {
        store.list = await api("/api/list");
    } catch {
        store.list = [];
    }
    notify("list");
}

// ---------------------------------------------------------------- retailers ticked in the filters

const ENABLED_KEY = "prixmalin.enabled";

export function loadEnabled() {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(ENABLED_KEY)); } catch { /* ignore */ }
    const keys = store.retailers.map((r) => r.key);
    store.enabled = new Set(Array.isArray(saved) ? saved.filter((k) => keys.includes(k)) : keys);
    if (store.enabled.size === 0) store.enabled = new Set(keys);
}

// Ticks or unticks a retailer (at least one stays ticked). Returns its new state.
export function setEnabled(key, on) {
    if (on) store.enabled.add(key);
    else if (store.enabled.size > 1) store.enabled.delete(key);
    else return true;
    try { localStorage.setItem(ENABLED_KEY, JSON.stringify([...store.enabled])); } catch { /* ignore */ }
    notify("enabled", key);
    return on;
}

// ---------------------------------------------------------------- shared actions

// Adds a query (and optionally the product chosen for one retailer) to the list
export async function addToList(query, product = null, quantity = 1) {
    const item = await api("/api/list", { method: "POST", body: { query, quantity, product } });
    await loadList();
    return item;
}

// Shows the retailer site in the PrixMalin browser window ("Ouvrir le site")
export async function openSetup(key) {
    toast(`Ouverture de ${retailer(key).label}…`);
    try {
        setBrowser(await api("/api/browser/setup", { method: "POST", body: { store: key } }));
        toast(`${retailer(key).label} est ouvert dans la fenêtre du navigateur PrixMalin. Cliquez sur « J'ai terminé » ensuite.`);
    } catch (err) {
        toast(err.message, true);
    }
}

// Ends the setup mode ("J'ai terminé" in the banner)
export async function endSetup() {
    try {
        setBrowser(await api("/api/browser/setup/done", { method: "POST" }));
        toast("C'est noté, les recherches reprennent en arrière-plan");
        notify("results-stale");
    } catch (err) {
        toast(err.message, true);
    }
}
