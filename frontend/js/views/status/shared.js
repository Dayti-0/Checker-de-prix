// Shared by the views of P4 (Réglages › Enseignes, État des enseignes,
// assistant, home cards): state of the retailers, state pills, store lists and
// the automatic choice of the nearest store (Courses U, E.Leclerc: the
// retailers whose `auto_store` is true).
//
//   await loadHealth()            GET /api/status/retailers → health.list, "status:changed"
//   setupState(retailer)          { kind: "ready" | "store" | "check", label }
//   statePill(kind, label)        pill with an icon and a text (never colour only)
//   await autoPickStore(key)      POST /api/retailers/{key}/store/auto, "{key}:auto"
//   await autoPickCoursesU()      the same for Courses U
//   distanceText(store)           « ≈ 2 km », « même commune »
//   await openSite(key)           « Ouvrir le site » (confirmation from a phone)
//   watchStores()                 at startup (features/setup-banner.js): automatic
//                                 choice once the settings are loaded, store chosen
//                                 on the site read back after « J'ai terminé »
//   ofLabel(label), andList(words) « d'E.Leclerc », « Aldi, Lidl et Carrefour »

import { api } from "../../core/api.js";
import { html } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { emit, loadSettings, on, openSetup, state } from "../../core/store.js";
import { announce, confirmDialog, notify } from "../../core/ui.js";

// ---------------------------------------------------------------- state of the retailers

export const health = { list: null, error: null };

let pending = null;
let rerun = null;

// Loads the state of every retailer (one request at a time). Asked while a
// request runs, whose answer may predate the change: asked again after it.
export function loadHealth() {
    if (pending) {
        if (!rerun) {
            rerun = pending.then(() => {
                rerun = null;
                return loadHealth();
            });
        }
        return rerun;
    }
    pending = api("/api/status/retailers")
        .then((list) => {
            health.list = list;
            health.error = null;
        })
        .catch((err) => {
            health.error = err.message;
        })
        .finally(() => {
            pending = null;
            emit("status:changed");
        });
    return pending;
}

export function healthOf(key) {
    return (health.list || []).find((h) => h.key === key) || null;
}

// The site no longer knows the store saved for `r` (« Ce magasin n'existe
// plus »): the state was computed for that very store
export function storeGone(r, h = healthOf(r.key)) {
    return Boolean(r.store && h && h.state === "store_required" && (h.store_name || null) === (r.store.name || null));
}

// What the user has to do for a retailer: nothing, choose a store, pass a check
export function setupState(r) {
    if (r.needs_store && !r.store) return { kind: "store", label: "Magasin à choisir" };
    const h = healthOf(r.key);
    if (storeGone(r, h)) return { kind: "store", label: "Magasin à changer" };
    if (h && (h.state === "blocked" || h.last_status === "blocked")) {
        return { kind: "check", label: "Vérification requise" };
    }
    return { kind: "ready", label: "Prêt" };
}

// Retailers the user still has to set up (store to choose, check to pass)
export function pendingSetups() {
    return state.retailers.filter((r) => setupState(r).kind !== "ready");
}

// Kind of pill for each state of /api/status/retailers
export const HEALTH_KIND = {
    ok: "ready",
    degraded: "warn",
    failing: "warn",
    broken: "bad",
    blocked: "check",
    store_required: "store",
    unknown: "unknown",
};

const PILL_ICON = {
    ready: "circle-check",
    store: "map-pin",
    check: "triangle-alert",
    warn: "circle-alert",
    bad: "triangle-alert",
    unknown: "clock",
};

export function statePill(kind, label) {
    return html`<span class="pill pill-${kind}">${icon(PILL_ICON[kind] || "info")}<span>${label}</span></span>`;
}

// ---------------------------------------------------------------- stores

// « 2,4 km »
export function km(value) {
    return `${String(Math.round(value * 10) / 10).replace(".", ",")} km`;
}

function sameTown(a, b) {
    const norm = (s) =>
        String(s || "")
            .normalize("NFD")
            .replace(/[̀-ͯ]/g, "")
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, " ")
            .trim();
    return Boolean(a) && norm(a) === norm(b);
}

// « ≈ 2 km », « même commune », or "" when the distance is unknown
export function distanceText(store, location = state.settings && state.settings.location) {
    if (location && store.postal_code === location.postal_code && sameTown(store.city, location.city)) {
        return "même commune";
    }
    if (store.distance_km == null) return "";
    return `≈ ${Math.max(1, Math.round(store.distance_km))} km`;
}

// Courses U, E.Leclerc: beyond this distance the nearest store is reported as far
export const FAR_KM = 40;

// « d'Intermarché », « d'E.Leclerc », « de Courses U »
export function ofLabel(label) {
    return /^[aeiouyàâéèêîôû]/i.test(label) ? `d'${label}` : `de ${label}`;
}

// « Aldi », « Aldi et Lidl », « Aldi, Lidl et Carrefour »
export function andList(words) {
    if (words.length < 2) return words.join("");
    return `${words.slice(0, -1).join(", ")} et ${words[words.length - 1]}`;
}

// What a retailer calls its stores: « drive » for E.Leclerc Drive
export function storeNoun(key) {
    return key === "leclerc" ? "drive" : "magasin";
}

// ---------------------------------------------------------------- automatic choice (Courses U, E.Leclerc)

// Retailers whose nearest store PrixMalin chooses by itself (RetailerInfo.auto_store)
export function autoStoreKeys(retailers = state.retailers) {
    const keys = (retailers || []).filter((r) => r.auto_store).map((r) => r.key);
    return keys.length || (retailers || []).length ? keys : ["coursesu", "leclerc"];
}

// key → { status: "idle" | "loading" | "done", result: answer of /store/auto, queued }
const autoPicks = {};

export function autoPickOf(key) {
    if (!autoPicks[key]) autoPicks[key] = { status: "idle", result: null, queued: false };
    return autoPicks[key];
}

// The automatic choice of Courses U (kept for the callers of P4)
export const autoPick = autoPickOf("coursesu");

function labelOf(key) {
    const r = (state.retailers || []).find((x) => x.key === key);
    return r ? r.label : key;
}

// « Magasin Courses U », « Drive E.Leclerc »
export function storeTitle(key) {
    const noun = storeNoun(key);
    return `${noun[0].toUpperCase()}${noun.slice(1)} ${labelOf(key)}`;
}

// Chooses the nearest store of `key` unless the user chose one himself.
// initial: when a page loads (only once per postal code, see the backend).
// A location saved while a choice runs (town chosen right after the postal
// code): the choice is made again once the running one ends.
export async function autoPickStore(key, { refresh = false, initial = false } = {}) {
    const pick = autoPickOf(key);
    if (pick.status === "loading") {
        if (!initial) pick.queued = true;
        return pick.result;
    }
    pick.status = "loading";
    emit(`${key}:auto`);
    const query = [refresh && "refresh=true", initial && "initial=true"].filter(Boolean).join("&");
    try {
        pick.result = await api(`/api/retailers/${key}/store/auto${query ? `?${query}` : ""}`, {
            method: "POST",
            timeout: 120000,
        });
        if (pick.result.status === "chosen") {
            await loadSettings();
            emit("results:stale");
            announce(`${storeTitle(key)} choisi automatiquement : ${pick.result.store.name}`);
        }
    } catch (err) {
        pick.result = { status: "error", message: err.message };
    } finally {
        pick.status = "done";
        emit(`${key}:auto`);
    }
    if (pick.queued) {
        pick.queued = false;
        if (needsAutoPick(key)) return autoPickStore(key);
    }
    return pick.result;
}

export function autoPickCoursesU(options = {}) {
    return autoPickStore("coursesu", options);
}

// A new postal code: the nearest store is chosen again, unless the user chose his own
export function needsAutoPick(key = "coursesu") {
    const settings = state.settings;
    if (!settings || !settings.location) return false;
    const chosen = settings.stores && settings.stores[key];
    return !chosen || chosen.auto;
}

on("location:changed", () => {
    for (const key of autoStoreKeys()) {
        autoPickOf(key).result = null;
        if (needsAutoPick(key)) autoPickStore(key);
    }
});

// The state of the sites may change when a store is chosen or a check passed
on("results:stale", () => {
    if (health.list) loadHealth();
});

// ---------------------------------------------------------------- startup (features/setup-banner.js)

let watching = false;

export function watchStores() {
    if (watching) return;
    watching = true;
    // Settings loaded with a postal code but no store (first start after an
    // update, store not found the last time): choose it now
    on("settings:changed", () => {
        const settings = state.settings;
        if (!settings || !settings.location) return;
        for (const key of autoStoreKeys()) {
            if (autoPickOf(key).status !== "idle") continue;
            if (settings.stores && settings.stores[key]) continue;
            autoPickStore(key, { initial: true });
        }
    });
    // « J'ai terminé »: the store chosen on the site is saved
    let setupMode = Boolean(state.browser && state.browser.setup_mode);
    on("browser:changed", () => {
        const now = Boolean(state.browser && state.browser.setup_mode);
        if (setupMode && !now) afterSetup();
        setupMode = now;
    });
}

// Reads back the store chosen on the site of `key` (nothing when the site was
// not opened with « Ouvrir le site », see the backend)
async function readBack(key) {
    let result = null;
    try {
        result = await api(`/api/retailers/${key}/store/from-site?opened_only=true`, {
            method: "POST",
            timeout: 90000,
        });
    } catch {
        /* best effort: the user can still choose in the list */
    }
    if (result && result.status === "chosen") {
        await loadSettings();
        emit("results:stale");
        const message = `${storeTitle(key)} : ${result.store.name} (choisi sur le site)`;
        notify(message);
        announce(message);
        return;
    }
    const settings = state.settings;
    if (settings && settings.location && !(settings.stores && settings.stores[key])) {
        autoPickStore(key, { initial: true });
    }
}

async function afterSetup() {
    loadHealth();
    await Promise.all(autoStoreKeys().map(readBack));
}

// ---------------------------------------------------------------- « Ouvrir le site »

export const REMOTE_SETUP_MESSAGE =
    "La page va s'ouvrir sur l'ordinateur où tourne PrixMalin. Allez-y pour valider la vérification ou choisir le magasin, puis appuyez ici sur « J'ai terminé ».";

// Opens the site of `key` in the PrixMalin browser window; from a phone (the
// window is on the PC) the user confirms first. Returns false when cancelled.
export async function openSite(key) {
    const remote = state.browser && state.browser.is_local === false;
    if (remote) {
        const ok = await confirmDialog({
            title: "Ouvrir le site sur l'ordinateur",
            message: REMOTE_SETUP_MESSAGE,
            confirmLabel: "Ouvrir sur l'ordinateur",
        });
        if (!ok) return false;
    }
    await openSetup(key);
    return true;
}
