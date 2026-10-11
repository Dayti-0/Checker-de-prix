// #/recherche?q=farine : prices of a product at every ticked retailer (area of P2).
//
// Layout, from top to bottom:
//   #summary         the best offer and one line per retailer (summary.js, B26)
//   toolbar          « Tout trié | Par enseigne », sort, « Actualiser » (B25, B30)
//   #result-filters  Bio, En promo, Disponible, marques (filters.js, B31)
//   #unavailable     retailers without results, with their actions (parts.js, B27)
//   #results-body    « Tout trié » (offers.js) or the columns (columns.js),
//                    or « Aucun produit » (parts.js, B34)
//
// The search state lives in state.search (core/store.js): it survives a trip
// to another view, and each retailer is shown as soon as it answers (one
// request per retailer, all cancelled by the next search). The page is
// updated in place (patch.js): the focus, the scroll and the images stay.
// Searches are asked with the event "search:requested" (form, suggestions,
// « Aucun produit ») and each one adds an entry to the history; going back to
// a search made a moment ago shows it again without asking the sites.

import { api } from "../../core/api.js";
import { euros, plural, relativeTime } from "../../core/fmt.js";
import { html, setHtml } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { currentRoute, navigate } from "../../core/router.js";
import { emit, on, openSetup, retailer, state } from "../../core/store.js";
import { announce, notify } from "../../core/ui.js";
import { addToMyList, isListed, openAddSheet, removeFromMyList } from "./add-sheet.js";
import { initAutocomplete } from "./autocomplete.js";
import { columnsMarkup } from "./columns.js";
import { resultFiltersMarkup } from "./filters.js";
import { group } from "./group.js";
import { readChoice, recordDuration, rememberSearch, saveChoice, usualDuration } from "./memory.js";
import { offersMarkup } from "./offers.js";
import { noResults, unavailableBar } from "./parts.js";
import { patch } from "./patch.js";
import {
    applyFilters,
    closeOf,
    filterCounts,
    gap,
    gapText,
    productKey,
    rank,
    rankClose,
    relevantOf,
    retailerState,
    SORTS,
    summarize,
    valueOf,
} from "./rank.js";
import { applyBars, slowAfter, summaryMarkup } from "./summary.js";

const VIEW_KEY = "prixmalin.resultsView";
const SORT_KEY = "prixmalin.resultsSort";
const VIEWS = ["all", "stores"];
// Under this width, « Tout trié » is the default view
const WIDE = "(min-width: 760px)";
// A search shown again from the history when it is younger than this
const SNAPSHOT_MS = 15 * 60000;

const search = state.search;
Object.assign(search, {
    view: readChoice(VIEW_KEY, VIEWS, window.matchMedia(WIDE).matches ? "stores" : "all"),
    sort: readChoice(SORT_KEY, SORTS, "price"),
    filters: [],
    expanded: {},
    closeOpen: {},
    groupsOpen: {},
    shown: new Set(), // retailers whose offers are in « Tout trié »
    held: new Set(), // retailers that answered while the user was reading further down
    controller: null,
    storeControllers: {},
    finishedAt: 0,
});

const snapshots = new Map();
let root = null; // container while the view is shown
let products = new Map(); // product key → product, for the buttons
let ticker = null;
let clock = "";

const TEMPLATE = html`
    <div id="results" class="results" aria-busy="false">
        <section id="summary" class="summary" aria-labelledby="summary-title" data-testid="summary"></section>
        <div class="results-toolbar" data-testid="results-toolbar">
            <fieldset class="seg" id="view-switch">
                <legend class="visually-hidden">Affichage des résultats</legend>
                <label><input type="radio" name="results-view" value="all"><span>${icon("list")}Tout trié</span></label>
                <label><input type="radio" name="results-view" value="stores"><span>${icon("store")}Par enseigne</span></label>
            </fieldset>
            <div class="refresh-box">
                <span id="updated" class="updated"></span>
                <button id="refresh-btn" class="icon-btn" type="button" aria-label="Actualiser les prix" title="Actualiser les prix">${icon("refresh-cw")}</button>
            </div>
            <fieldset class="seg" id="sort-switch">
                <legend class="seg-legend">Trier</legend>
                <label><input type="radio" name="results-sort" value="price"><span>Prix</span></label>
                <label><input type="radio" name="results-sort" value="unit"><span id="sort-unit-label">Prix au kg/L</span></label>
                <label><input type="radio" name="results-sort" value="promo"><span>Promos</span></label>
                <label><input type="radio" name="results-sort" value="relevance"><span>Pertinence</span></label>
            </fieldset>
        </div>
        <div id="result-filters" class="result-filters"></div>
        <div id="unavailable"></div>
        <div id="results-body" class="results-body"></div>
    </div>`;

const $ = (sel) => (root ? root.querySelector(sel) : null);

function enabledKeys() {
    return state.retailers.filter((r) => state.enabled.has(r.key)).map((r) => r.key);
}

function snapshotKey(query) {
    return `${query.trim().toLocaleLowerCase("fr")}|${enabledKeys().join(",")}`;
}

function isLoading(key) {
    return retailerState(search.results[key]) === "loading";
}

// Retailers « plus longs que d'habitude » and the half-minute: when this
// changes, the texts that depend on the time are drawn again
function clockSignature(now) {
    const slow = enabledKeys().filter(
        (k) => isLoading(k) && now - (search.results[k].started || now) > slowAfter(usualDuration(k)),
    );
    return `${slow.join(",")}|${Math.floor(now / 30000)}`;
}

// ---------------------------------------------------------------- searching

// Searches `query` at every ticked retailer (works even when the view is hidden)
function runSearch(query, refresh = false) {
    if (search.controller) search.controller.abort();
    search.controller = new AbortController();
    search.storeControllers = {};
    search.query = query;
    search.results = {};
    search.expanded = {};
    search.closeOpen = {};
    search.groupsOpen = {};
    search.shown = new Set();
    search.held = new Set();
    search.finishedAt = 0;
    const token = ++search.token;
    const keys = enabledKeys();
    for (const key of keys) search.results[key] = { status: "loading", started: Date.now() };
    rememberSearch(query);
    emit("search:started", { query });
    announce(`Recherche de « ${query} » dans ${plural(keys.length, "enseigne")}…`);
    renderResults();
    // A new search is read from its top (the previous one was perhaps read
    // further down: the new offers would otherwise wait, held back)
    if (root && window.scrollY > 0) window.scrollTo(0, 0);
    for (const key of keys) searchStore(key, token, refresh);
}

function resetSearch() {
    if (search.controller) search.controller.abort();
    search.query = "";
    search.results = {};
    search.expanded = {};
    search.token++;
}

// The user scrolled down the list of « Tout trié »: new offers wait (no jump)
function readingFurther() {
    if (!root || search.view !== "all" || ![...search.shown].some((k) => relevantOf(search.results[k]).length)) {
        return false;
    }
    // « Si l'utilisateur a défilé »: the page is no longer at its top
    return window.scrollY > 80;
}

async function searchStore(key, token, refresh = false) {
    const controller = new AbortController();
    search.storeControllers[key] = controller;
    const parent = search.controller;
    if (parent) parent.signal.addEventListener("abort", () => controller.abort(), { once: true });
    search.results[key] = { status: "loading", started: Date.now() };
    search.shown.delete(key);
    search.held.delete(key);
    renderResults();
    startTicker();
    let result;
    try {
        const path = `/api/search/${encodeURIComponent(key)}?q=${encodeURIComponent(search.query)}${refresh ? "&refresh=true" : ""}`;
        result = await api(path, { signal: controller.signal });
    } catch (err) {
        if (err.code === "aborted") return; // a newer search, or « Ignorer »
        result = { store: key, label: retailer(key).label, status: "error", message: err.message, products: [] };
    }
    if (token !== search.token) return;
    if (!result.cached && result.elapsed_ms > 0) recordDuration(key, result.elapsed_ms);
    search.results[key] = result;
    if (readingFurther()) search.held.add(key);
    else search.shown.add(key);
    emit("search:result", { query: search.query, store: key, result });
    if (enabledKeys().every((k) => !isLoading(k))) finish();
    renderResults();
}

// « Ignorer »: the answer of this retailer is no longer awaited
function skipStore(key) {
    const controller = search.storeControllers[key];
    if (controller) controller.abort();
    const label = retailer(key).label;
    search.results[key] = {
        store: key,
        label,
        status: "skipped",
        message: `${label} est ignorée pour cette recherche.`,
        products: [],
    };
    search.shown.add(key);
    if (enabledKeys().every((k) => !isLoading(k))) finish();
    renderResults();
}

function finish() {
    search.finishedAt = Date.now();
    emit("search:done", { query: search.query });
    const keys = enabledKeys();
    const best = summarize(search.results, keys, { sort: "price" }).cheapest;
    const failed = keys.filter((k) => retailerState(search.results[k]) === "error").length;
    const first = best
        ? `Terminé : le moins cher est ${retailer(best.store).label}, ${euros(best.price)}, ${best.name}.`
        : `Terminé : aucun produit pour « ${search.query} ».`;
    announce(failed ? `${first} ${plural(failed, "enseigne indisponible", "enseignes indisponibles")}.` : first);
    snapshots.delete(snapshotKey(search.query));
    snapshots.set(snapshotKey(search.query), { results: { ...search.results }, time: Date.now() });
    if (snapshots.size > 10) snapshots.delete(snapshots.keys().next().value);
}

// Shows again a search made a moment ago (back in the history): no request
function restore(query) {
    const saved = snapshots.get(snapshotKey(query));
    if (!saved || Date.now() - saved.time > SNAPSHOT_MS) return false;
    if (search.controller) search.controller.abort();
    search.token++;
    search.query = query;
    search.results = { ...saved.results };
    search.expanded = {};
    search.closeOpen = {};
    search.groupsOpen = {};
    search.shown = new Set(Object.keys(saved.results));
    search.held = new Set();
    search.finishedAt = saved.time;
    renderResults();
    return true;
}

function startTicker() {
    if (ticker || !root) return;
    ticker = setInterval(() => {
        if (root && search.query && clockSignature(Date.now()) !== clock) renderResults();
    }, 1000);
}

function stopTicker() {
    clearInterval(ticker);
    ticker = null;
}

// ---------------------------------------------------------------- events

// A search asked from the page (form, suggestion): a new entry of the history
on("search:requested", ({ query, refresh = false }) => {
    const box = document.getElementById("q");
    if (box) {
        box.value = query;
        // The keyboard of a phone hides the results: closed after the search
        if (window.matchMedia("(pointer: coarse)").matches) box.blur();
    }
    runSearch(query, refresh);
    const route = currentRoute();
    const here = Boolean(route) && route.name === "search" && route.params.q === query;
    navigate("/recherche", { q: query }, { replace: here });
});

on("search:reset", resetSearch);

// A store was chosen or the user acted on a site: search again
on("results:stale", () => {
    if (search.query) runSearch(search.query);
});

// A retailer was ticked: search it too. Unticked while it was searching: its
// answer is no longer awaited (the search may be over without it)
on("filters:changed", (key) => {
    if (search.query && state.enabled.has(key) && !search.results[key]) {
        searchStore(key, search.token);
        return;
    }
    if (search.query && !state.enabled.has(key) && search.results[key] && isLoading(key)) {
        if (search.storeControllers[key]) search.storeControllers[key].abort();
        delete search.results[key];
        if (enabledKeys().every((k) => !isLoading(k))) finish();
    }
    renderResults();
});

// The « ✓ » of the products follow the list
on("list:changed", () => renderResults());

// ---------------------------------------------------------------- rendering

function retailerModel(key, keys, unit) {
    const r = retailer(key);
    const result = search.results[key] || { status: "loading" };
    const allRelevant = rank(relevantOf(result), { sort: search.sort, unit, order: keys });
    return {
        key,
        label: r.label,
        retailer: r,
        result,
        state: retailerState(result),
        allRelevant,
        relevant: applyFilters(allRelevant, search.filters),
        close: rankClose(applyFilters(closeOf(result), search.filters), keys),
    };
}

// Where a retailer goes: "grid" (a column), "error" or "empty" (the bar), or
// "offers" (« Tout trié »)
function placeOf(m) {
    const hasProducts = (m.result.products || []).length > 0;
    if (search.view === "stores") {
        if (m.state === "loading" || m.state === "ok") return "grid";
        if (m.state === "error") return m.result.status === "store_required" && hasProducts ? "grid" : "error";
        return m.close.length || m.allRelevant.length ? "grid" : "empty";
    }
    if (m.state === "error") return "error";
    if (m.state === "none" && !m.allRelevant.length && !m.close.length) return "empty";
    return "offers";
}

// « Mis à jour il y a 5 min »: age of the oldest prices shown
function updatedText(keys, now) {
    if (keys.some(isLoading)) return "";
    const times = keys
        .map((k) => search.results[k])
        .filter((r) => r && r.status === "ok" && r.fetched_at)
        .map((r) => r.fetched_at * 1000);
    const ts = times.length ? Math.min(...times) : search.finishedAt;
    return ts ? `Mis à jour ${relativeTime(ts, now)}` : "";
}

const UNIT_SORT_LABEL = { kg: "Prix au kg", L: "Prix au litre", pièce: "Prix à la pièce" };

function syncToolbar(summary, keys, now) {
    for (const input of root.querySelectorAll("input[name=results-view]")) input.checked = input.value === search.view;
    for (const input of root.querySelectorAll("input[name=results-sort]")) input.checked = input.value === search.sort;
    const unitLabel = UNIT_SORT_LABEL[summary.unit] || "Prix au kg/L";
    if ($("#sort-unit-label").textContent !== unitLabel) $("#sort-unit-label").textContent = unitLabel;
    const updated = updatedText(keys, now);
    if ($("#updated").textContent !== updated) $("#updated").textContent = updated;
}

const SKELETON_ROWS = html`<div class="offers-loading" data-key="loading" aria-hidden="true">${[1, 2, 3].map(
    () =>
        html`<div class="skeleton"><div class="s-img"></div><div><div class="s-line"></div><div class="s-line short"></div></div></div>`,
)}</div>`;

// « Aucun produit » for the whole search (one block, B34): every retailer
// answered and none has the product (or none is left by the filters)
function nothingFound(models, loading) {
    const anyRelevant = models.some((m) => m.state === "ok" && m.allRelevant.length);
    const filteredOut = anyRelevant && !models.some((m) => m.state === "ok" && m.relevant.length);
    return {
        nothing: !loading && (!anyRelevant || filteredOut) && models.some((m) => m.state !== "error"),
        filteredOut,
    };
}

function bodyMarkup(models, placed, keys, unit, view, loading) {
    const { nothing, filteredOut } = nothingFound(models, loading);
    if (search.view === "stores") {
        const grid = placed.filter((x) => x.place === "grid").map((x) => x.m);
        return html`${nothing && noResults(search.query, { filtered: filteredOut })}${grid.length > 0 && columnsMarkup(grid, view)}`;
    }
    const inList = placed.filter((x) => x.place === "offers").map((x) => x.m);
    const offers = rank(
        inList.filter((m) => m.state === "ok").flatMap((m) => m.relevant),
        { sort: search.sort, unit, order: keys },
    );
    const close = rankClose(
        inList.flatMap((m) => m.close),
        keys,
    );
    const pending = models
        .filter((m) => search.held.has(m.key) && m.state === "ok")
        .reduce((n, m) => n + m.relevant.length, 0);
    if (nothing) {
        const rest = close.length > 0 && offersMarkup({ groups: [], count: 0, stores: 0, close, pending: 0 }, view);
        return html`${noResults(search.query, { filtered: filteredOut })}${rest}`;
    }
    if (!offers.length && loading) return SKELETON_ROWS;
    if (!offers.length && !close.length && !pending) return html``;
    const stores = new Set(offers.map((p) => p.store)).size;
    return offersMarkup({ groups: group(offers), count: offers.length, stores, close, pending }, view);
}

function renderResults() {
    if (!root || !search.query) return;
    const now = Date.now();
    const keys = enabledKeys();
    const summary = summarize(search.results, keys, { sort: search.sort, filters: search.filters });
    const { unit, criterion } = summary;
    const models = keys.map((k) => retailerModel(k, keys, unit));
    const loading = models.some((m) => m.state === "loading");
    products = new Map();
    for (const m of models) for (const p of m.result.products || []) products.set(productKey(p), p);

    const cheapestKey = summary.cheapest ? productKey(summary.cheapest) : null;
    const bestUnitKey = summary.bestUnit ? productKey(summary.bestUnit) : null;
    const bestValue = summary.best ? valueOf(summary.best, criterion, unit) : null;
    const view = {
        query: search.query,
        now,
        results: search.results,
        keys,
        filtered: search.filters.length > 0,
        expanded: search.expanded,
        closeOpen: search.closeOpen,
        groupsOpen: search.groupsOpen,
        label: (k) => retailer(k).label,
        usual: usualDuration,
        rowOptions: (p, inAll = false) => ({
            cheapest: cheapestKey,
            bestUnit: bestUnitKey,
            sort: search.sort,
            showStore: inAll,
            listed: isListed(p),
            gap: inAll ? gapText(gap(valueOf(p, criterion, unit), bestValue), criterion === "unit" ? unit : null) : "",
        }),
        closeRowOptions: (p) => ({ sort: search.sort, showStore: search.view === "all", listed: isListed(p) }),
    };

    // In « Tout trié », the retailers held back (the user reads further down) wait
    const visible = (m) => search.view === "stores" || !search.held.has(m.key);
    const placed = models.map((m) => ({ m, place: visible(m) ? placeOf(m) : "held" }));
    const found = nothingFound(models, loading);
    // The retailers without the product are not listed again under « Aucun produit »
    const empties = found.nothing ? [] : placed.filter((x) => x.place === "empty");
    const bar = [
        ...placed.filter((x) => x.place === "error").map((x) => ({ ...x.m, kind: "error" })),
        ...empties.map((x) => ({ ...x.m, kind: "empty" })),
    ];
    const unavailable = models.filter((m) => m.state === "error").length;
    const shownRelevant = models.filter(visible).flatMap((m) => (m.state === "ok" ? m.allRelevant : []));

    patch($("#summary"), summaryMarkup(summary, { ...view, unavailable }));
    // « Aucun produit » anywhere: the block says it, the summary would only repeat it
    $("#summary").hidden = found.nothing && !found.filteredOut;
    // The filters stay in place while the retailers answer; gone when nothing was found
    const withFilters = loading || shownRelevant.length > 0 || search.filters.length > 0;
    patch(
        $("#result-filters"),
        withFilters
            ? resultFiltersMarkup(filterCounts(shownRelevant), shownRelevant.length, search.filters)
            : html``,
    );
    patch($("#unavailable"), unavailableBar(bar, now));
    patch($("#results-body"), bodyMarkup(models, placed, keys, unit, view, loading));
    applyBars(root);
    syncToolbar(summary, keys, now);
    $("#results").setAttribute("aria-busy", loading ? "true" : "false");
    clock = clockSignature(now);
}

// ---------------------------------------------------------------- actions

function showHeld() {
    for (const key of search.held) search.shown.add(key);
    search.held = new Set();
    renderResults();
    $("#results-body")?.scrollIntoView({ block: "start" });
    announce("Nouvelles offres affichées");
}

// « 3 produits affichés » after a change of the filters
function filtersText() {
    const count = enabledKeys()
        .map((k) => search.results[k])
        .filter((r) => r && r.status === "ok")
        .reduce((n, r) => n + applyFilters(relevantOf(r), search.filters).length, 0);
    return plural(count, "produit affiché", "produits affichés");
}

function onClick(e) {
    const target = e.target.closest("button");
    if (!target || !root || !root.contains(target)) return;
    const { action } = target.dataset;
    const key = target.dataset.storeKey;
    if (target.dataset.openSettings) {
        navigate("/reglages", { enseigne: target.dataset.openSettings });
    } else if (target.dataset.setup) {
        openSetup(target.dataset.setup);
    } else if (action === "add") {
        const product = products.get(target.dataset.product);
        if (product) openAddSheet(product, search.query, target);
    } else if (action === "remove") {
        const product = products.get(target.dataset.product);
        if (product) removeFromMyList(product);
    } else if (action === "more") {
        search.expanded[key] = true;
        renderResults();
    } else if (action === "close") {
        search.closeOpen[target.dataset.close] = !search.closeOpen[target.dataset.close];
        renderResults();
    } else if (action === "group") {
        search.groupsOpen[target.dataset.group] = !search.groupsOpen[target.dataset.group];
        renderResults();
    } else if (action === "retry") {
        searchStore(key, search.token, true);
    } else if (action === "skip") {
        skipStore(key);
    } else if (action === "show-pending") {
        showHeld();
    } else if (action === "filter") {
        if (target.getAttribute("aria-disabled") === "true") return;
        const id = target.dataset.filter;
        search.filters = search.filters.includes(id) ? search.filters.filter((f) => f !== id) : [...search.filters, id];
        renderResults();
        announce(filtersText());
    } else if (action === "clear-filters") {
        search.filters = [];
        renderResults();
        announce(filtersText());
    } else if (action === "query") {
        emit("search:requested", { query: target.dataset.query });
    } else if (action === "add-query") {
        addToMyList({ query: search.query, quantity: 1 }).catch((err) => notify(err.message, { type: "error" }));
    }
}

// Back near the top of the list: the offers held back are shown
function onScroll() {
    if (!search.held.size || readingFurther()) return;
    for (const key of search.held) search.shown.add(key);
    search.held = new Set();
    renderResults();
}

function onChange(e) {
    const input = e.target;
    if (input.name === "results-view" && VIEWS.includes(input.value)) {
        search.view = input.value;
        saveChoice(VIEW_KEY, search.view);
        for (const key of search.held) search.shown.add(key);
        search.held = new Set();
        renderResults();
    } else if (input.name === "results-sort" && SORTS.includes(input.value)) {
        search.sort = input.value;
        saveChoice(SORT_KEY, search.sort);
        renderResults();
    }
}

function bind() {
    root.addEventListener("click", onClick);
    root.addEventListener("change", onChange);
    $("#refresh-btn").addEventListener("click", () => {
        if (search.query) emit("search:requested", { query: search.query, refresh: true });
    });
    window.addEventListener("scroll", onScroll, { passive: true });
}

// Shows the search of the address; without q, back to the home page
function applyParams(params) {
    const q = (params.q || "").trim();
    if (!q) {
        navigate("/", {}, { replace: true });
        return;
    }
    const box = document.getElementById("q");
    if (box && box.value !== q) box.value = q;
    if (q === search.query) renderResults();
    else if (!restore(q)) runSearch(q);
}

initAutocomplete();

export const enabled = true;
export const title = (params) => (params.q ? `${params.q} – Rechercher` : "Rechercher");
export const shell = { search: true, filters: true };

export function render(container, params) {
    root = container;
    setHtml(root, TEMPLATE);
    bind();
    startTicker();
    applyParams(params);
}

export function update(params) {
    applyParams(params);
}

export function destroy() {
    window.removeEventListener("scroll", onScroll);
    stopTicker();
    root = null;
}
