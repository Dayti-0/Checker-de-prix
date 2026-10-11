// What this device remembers about the searches (localStorage, never needed:
// every read and write may fail in a private window):
//   - the recent searches (at most 8, the last first), for the suggestions and
//     the home card « Recherches récentes »;
//   - how long each retailer usually takes to answer (« ~8 s »);
//   - the choices of the results page (view « Tout trié » / « Par enseigne », sort).

import { emit } from "../../core/store.js";

const RECENT_KEY = "prixmalin.recentSearches";
const DURATIONS_KEY = "prixmalin.durations";
export const RECENT_MAX = 8;
const DURATIONS_KEPT = 5;

function read(key, fallback) {
    try {
        const value = JSON.parse(localStorage.getItem(key));
        return value ?? fallback;
    } catch {
        return fallback;
    }
}

function write(key, value) {
    try {
        localStorage.setItem(key, JSON.stringify(value));
    } catch {
        /* not saved: still used for this page */
    }
}

export function readChoice(key, allowed, fallback) {
    let value = null;
    try {
        value = localStorage.getItem(key);
    } catch {
        /* storage unavailable */
    }
    return allowed.includes(value) ? value : fallback;
}

export function saveChoice(key, value) {
    try {
        localStorage.setItem(key, value);
    } catch {
        /* applied, not saved */
    }
}

// ---------------------------------------------------------------- recent searches

const same = (a, b) => a.trim().toLocaleLowerCase("fr") === b.trim().toLocaleLowerCase("fr");

// [{ q, n, t }]: query, number of searches, last time (ms); the last one first
export function recentSearches() {
    const list = read(RECENT_KEY, []);
    return Array.isArray(list)
        ? list.filter((r) => r && typeof r.q === "string" && r.q.trim()).slice(0, RECENT_MAX)
        : [];
}

export function rememberSearch(query, now = Date.now()) {
    const q = String(query || "").trim();
    if (!q) return;
    const list = recentSearches();
    const previous = list.find((r) => same(r.q, q));
    const rest = list.filter((r) => !same(r.q, q));
    write(RECENT_KEY, [{ q, n: (previous ? previous.n || 1 : 0) + 1, t: now }, ...rest].slice(0, RECENT_MAX));
    emit("recent:changed");
}

export function forgetSearch(query) {
    write(
        RECENT_KEY,
        recentSearches().filter((r) => !same(r.q, query)),
    );
    emit("recent:changed");
}

// ---------------------------------------------------------------- durations

export function recordDuration(key, ms) {
    if (!(ms > 0)) return;
    const all = read(DURATIONS_KEY, {});
    const list = Array.isArray(all[key]) ? all[key] : [];
    all[key] = [...list, Math.round(ms)].slice(-DURATIONS_KEPT);
    write(DURATIONS_KEY, all);
}

// Usual time (ms) of a retailer: median of its last answers, null when unknown
export function usualDuration(key) {
    const list = read(DURATIONS_KEY, {})[key];
    if (!Array.isArray(list) || !list.length) return null;
    const sorted = [...list].filter((v) => v > 0).sort((a, b) => a - b);
    return sorted.length ? sorted[Math.floor(sorted.length / 2)] : null;
}
