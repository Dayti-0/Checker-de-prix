// Shared by the views of P4 (Réglages › Enseignes, État des enseignes,
// assistant, home cards): state of the retailers, state pills, store lists and
// the automatic choice of the nearest Courses U store.
//
//   await loadHealth()            GET /api/status/retailers → health.list, "status:changed"
//   setupState(retailer)          { kind: "ready" | "store" | "check", label }
//   statePill(kind, label)        pill with an icon and a text (never colour only)
//   await autoPickCoursesU()      POST /api/retailers/coursesu/store/auto, "coursesu:auto"
//   distanceText(store)           « ≈ 2 km », « même commune »
//   await openSite(key)           « Ouvrir le site » (confirmation from a phone)
//   watchStores()                 at startup (features/setup-banner.js): automatic
//                                 choice once the settings are loaded, store chosen
//                                 on the Courses U site read back after « J'ai terminé »

import { api } from "../../core/api.js";
import { html } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { emit, loadSettings, on, openSetup, state } from "../../core/store.js";
import { announce, confirmDialog, notify } from "../../core/ui.js";

// ---------------------------------------------------------------- state of the retailers

export const health = { list: null, error: null };

let pending = null;

// Loads the state of every retailer (one request at a time)
export function loadHealth() {
    if (!pending) {
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
    }
    return pending;
}

export function healthOf(key) {
    return (health.list || []).find((h) => h.key === key) || null;
}

// What the user has to do for a retailer: nothing, choose a store, pass a check
export function setupState(r) {
    if (r.needs_store && !r.store) return { kind: "store", label: "Magasin à choisir" };
    const h = healthOf(r.key);
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

// Courses U: beyond this distance the nearest store is reported as far
export const FAR_KM = 40;

// ---------------------------------------------------------------- automatic choice (Courses U)

// status: "idle" | "loading" | "done"; result: answer of /store/auto
export const autoPick = { status: "idle", result: null };

// Chooses the nearest Courses U store unless the user chose one himself.
// initial: when a page loads (only once per postal code, see the backend)
export async function autoPickCoursesU({ refresh = false, initial = false } = {}) {
    if (autoPick.status === "loading") return autoPick.result;
    autoPick.status = "loading";
    emit("coursesu:auto");
    const query = [refresh && "refresh=true", initial && "initial=true"].filter(Boolean).join("&");
    try {
        autoPick.result = await api(`/api/retailers/coursesu/store/auto${query ? `?${query}` : ""}`, {
            method: "POST",
            timeout: 120000,
        });
        if (autoPick.result.status === "chosen") {
            await loadSettings();
            emit("results:stale");
            const store = autoPick.result.store;
            announce(`Magasin Courses U choisi automatiquement : ${store.name}`);
        }
    } catch (err) {
        autoPick.result = { status: "error", message: err.message };
    } finally {
        autoPick.status = "done";
        emit("coursesu:auto");
    }
    return autoPick.result;
}

// A new postal code: the nearest Courses U store is chosen again, unless the
// user chose his own
export function needsAutoPick() {
    const settings = state.settings;
    if (!settings || !settings.location) return false;
    const chosen = settings.stores && settings.stores.coursesu;
    return !chosen || chosen.auto;
}

on("location:changed", () => {
    autoPick.result = null;
    if (needsAutoPick()) autoPickCoursesU();
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
    // Settings loaded with a postal code but no Courses U store (first start
    // after an update, store not found the last time): choose it now
    on("settings:changed", () => {
        const settings = state.settings;
        if (autoPick.status !== "idle" || !settings || !settings.location) return;
        if (settings.stores && settings.stores.coursesu) return;
        autoPickCoursesU({ initial: true });
    });
    // « J'ai terminé »: the store chosen on the Courses U site is saved
    let setupMode = Boolean(state.browser && state.browser.setup_mode);
    on("browser:changed", () => {
        const now = Boolean(state.browser && state.browser.setup_mode);
        if (setupMode && !now) afterSetup();
        setupMode = now;
    });
}

async function afterSetup() {
    loadHealth();
    let result = null;
    try {
        result = await api("/api/retailers/coursesu/store/from-site?opened_only=true", {
            method: "POST",
            timeout: 90000,
        });
    } catch {
        /* best effort: the user can still choose in the list */
    }
    if (result && result.status === "chosen") {
        await loadSettings();
        emit("results:stale");
        const message = `Magasin Courses U : ${result.store.name} (choisi sur le site)`;
        notify(message);
        announce(message);
        return;
    }
    const settings = state.settings;
    if (settings && settings.location && !(settings.stores && settings.stores.coursesu)) {
        autoPickCoursesU({ initial: true });
    }
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
