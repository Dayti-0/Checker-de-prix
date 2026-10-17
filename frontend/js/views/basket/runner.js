// The basket comparison in progress (B59), kept while the user goes to
// another view (the searches go on; leaving the page or « Arrêter » stops them).
//
//   compareNow({ refresh })   live comparison (EventSource on
//                             GET /api/basket/compare/stream), retailers ticked
//   recompare()               again from the prices already read (after « Changer »)
//   stop()                    « Arrêter »: the server cancels the searches
//   loadLast()                the last comparison (GET /api/basket/last)
//   subscribe(fn)             fn() after each change of `run`
//
// Without EventSource, or when the stream cannot be opened, the comparison is
// asked with POST /api/basket/compare (no cell by cell progress).

import { api } from "../../core/api.js";
import { state } from "../../core/store.js";

export const run = {
    // idle | running | done | stopped | error
    status: "idle",
    // From the « start » event: [{ id, query }], [{ store, label }]
    items: [],
    stores: [],
    skipped: [],
    total: 0,
    done: 0,
    // "store:itemId" → BasketLine received while the retailers answer
    cells: {},
    // store → { status, message, retry_after } once the retailer is over
    storeStates: {},
    // The comparison (BasketComparison) once done, or the last one
    comparison: null,
    error: null,
    refresh: false,
    // The comparison came from GET /api/basket/last (not run in this page)
    fromLast: false,
    // Comparison asked again from the prices already read (« Changer »)
    updating: false,
};

const listeners = new Set();
let source = null;
let token = 0;

export function subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
}

function changed(event = null) {
    for (const fn of [...listeners]) {
        try {
            fn(event);
        } catch (err) {
            console.error(err);
        }
    }
}

// Retailers ticked, in the order of the app
export function tickedStores() {
    const keys = state.retailers.map((r) => r.key).filter((k) => state.enabled.has(k));
    return keys.length ? keys : [...state.enabled];
}

function close() {
    if (source) {
        source.close();
        source = null;
    }
}

function reset(refresh) {
    Object.assign(run, {
        status: "running",
        items: [],
        stores: tickedStores().map((store) => ({ store, label: (state.retailers.find((r) => r.key === store) || {}).label || store })),
        skipped: [],
        total: 0,
        done: 0,
        cells: {},
        storeStates: {},
        error: null,
        refresh,
        fromLast: false,
    });
}

function finish(comparison) {
    close();
    run.status = "done";
    run.comparison = comparison;
    run.fromLast = false;
    changed("done");
}

function fail(message) {
    close();
    run.status = "error";
    run.error = message;
    changed("error");
}

async function post({ refresh = false, cacheOnly = false } = {}, mine = token) {
    try {
        const comparison = await api("/api/basket/compare", {
            method: "POST",
            body: { stores: tickedStores(), refresh, cache_only: cacheOnly },
        });
        if (mine === token) finish(comparison);
    } catch (err) {
        if (mine === token) fail(err.message);
    }
}

const READ = (e) => {
    try {
        return JSON.parse(e.data);
    } catch {
        return null;
    }
};

export function compareNow({ refresh = false } = {}) {
    close();
    const mine = ++token;
    reset(refresh);
    changed("start");
    if (typeof EventSource !== "function") {
        post({ refresh }, mine);
        return;
    }
    const params = new URLSearchParams({ stores: tickedStores().join(",") });
    if (refresh) params.set("refresh", "true");
    let started = false;
    const es = new EventSource(`/api/basket/compare/stream?${params}`);
    source = es;
    es.addEventListener("start", (e) => {
        const data = READ(e);
        if (!data || mine !== token) return;
        started = true;
        Object.assign(run, { items: data.items, stores: data.stores, skipped: data.skipped || [], total: data.total, done: 0 });
        changed("start");
    });
    es.addEventListener("line", (e) => {
        const data = READ(e);
        if (!data || mine !== token) return;
        run.cells[`${data.store}:${data.item_id}`] = data.line;
        run.done = data.done;
        run.total = data.total;
        changed("line");
    });
    es.addEventListener("store", (e) => {
        const data = READ(e);
        if (!data || mine !== token) return;
        run.storeStates[data.store] = data;
        changed("store");
    });
    es.addEventListener("done", (e) => {
        const data = READ(e);
        if (!data || mine !== token) return;
        finish(data.comparison);
    });
    // « error »: the event of the server (with data), or the connection was lost
    es.addEventListener("error", (e) => {
        if (mine !== token) return;
        const data = e.data ? READ(e) : null;
        if (data) {
            fail(data.message);
        } else if (!started) {
            close();
            post({ refresh }, mine); // the stream could not be opened: in one request
        } else if (run.status === "running") {
            fail("La connexion avec PrixMalin a été coupée. Réessayez dans un instant.");
        }
    });
}

// After « Changer »: the comparison again, from the prices already read
export async function recompare() {
    close();
    const mine = ++token;
    run.updating = true;
    changed("updating");
    await post({ cacheOnly: true }, mine);
    run.updating = false;
    changed("updated");
}

export function stop() {
    if (run.status !== "running") return;
    token += 1;
    close();
    run.status = "stopped";
    changed("stopped");
}

// The last comparison, once per page (none: null)
export async function loadLast() {
    if (run.comparison || run.status === "running") return run.comparison;
    try {
        const last = await api("/api/basket/last");
        if (last && !run.comparison && run.status !== "running") {
            run.comparison = last;
            run.status = "done";
            run.fromLast = true;
            changed("last");
        }
    } catch {
        /* no last basket */
    }
    return run.comparison;
}
