// #/recherche?q=farine : prices of a product at every ticked retailer (area of P2).
//
// The search state lives in state.search (core/store.js): it survives a trip
// to another view, and each retailer column is shown as soon as its retailer
// answers. Searches are asked with the event "search:requested" (form of the
// page, suggestions...) and replace the address in the history.

import { retailerBadge } from "../../components/retailer-badge.js";
import { api } from "../../core/api.js";
import { euros, plural } from "../../core/fmt.js";
import { html, setHtml } from "../../core/html.js";
import { navigate } from "../../core/router.js";
import { addToList, emit, on, openSetup, retailer, state } from "../../core/store.js";
import { notify } from "../../core/ui.js";
import { productRow } from "./product-row.js";

const PAGE_SIZE = 5;
const search = state.search;

let root = null; // container while the view is shown
// Products rendered on the page, referenced by the « + » buttons
let productIndex = [];

const TEMPLATE = html`
    <div id="results">
        <div id="summary" class="summary"></div>
        <div class="toolbar">
            <label class="sort">Trier par
                <select id="sort">
                    <option value="price">prix</option>
                    <option value="unit">prix au kg / L</option>
                </select>
            </label>
            <button id="add-query-btn" class="btn-ghost" type="button"></button>
            <button id="refresh-btn" class="btn-ghost" type="button" title="Ignorer le cache et relancer la recherche">↻ Actualiser</button>
        </div>
        <div id="columns" class="columns"></div>
    </div>`;

const $ = (sel) => (root ? root.querySelector(sel) : null);

// ---------------------------------------------------------------- searching

// Searches `query` at every ticked retailer (works even when the view is hidden)
function runSearch(query, refresh = false) {
    search.query = query;
    search.results = {};
    search.expanded = {};
    const token = ++search.token;
    for (const key of state.enabled) search.results[key] = { status: "loading" };
    emit("search:started", { query });
    renderResults();
    for (const key of state.enabled) searchStore(key, token, refresh);
}

function resetSearch() {
    search.query = "";
    search.results = {};
    search.expanded = {};
    search.token++;
}

async function searchStore(key, token, refresh = false) {
    search.results[key] = { status: "loading" };
    renderResults();
    let result;
    try {
        result = await api(`/api/search/${key}?q=${encodeURIComponent(search.query)}${refresh ? "&refresh=true" : ""}`);
    } catch (err) {
        result = { store: key, status: "error", message: err.message, products: [] };
    }
    if (token !== search.token) return;
    search.results[key] = result;
    emit("search:result", { query: search.query, store: key, result });
    if (Object.values(search.results).every((r) => r.status !== "loading")) emit("search:done", { query: search.query });
    renderResults();
}

// A search asked from the page (form, suggestion): the address follows the query
on("search:requested", ({ query, refresh = false }) => {
    runSearch(query, refresh);
    navigate("/recherche", { q: query }, { replace: true });
});

on("search:reset", resetSearch);

// A store was chosen or the user acted on a site: search again
on("results:stale", () => {
    if (search.query) runSearch(search.query);
});

// A retailer was ticked: search it too
on("filters:changed", (key) => {
    if (search.query && state.enabled.has(key) && !search.results[key]) searchStore(key, search.token);
    else renderResults();
});

function sortProducts(products) {
    const list = [...products];
    if (search.sort === "unit") {
        list.sort(
            (a, b) =>
                (a.unit_price == null) - (b.unit_price == null) ||
                (a.unit_price ?? 0) - (b.unit_price ?? 0) ||
                (a.price == null) - (b.price == null) ||
                (a.price ?? 0) - (b.price ?? 0),
        );
    } else {
        list.sort((a, b) => (a.price == null) - (b.price == null) || (a.price ?? 0) - (b.price ?? 0));
    }
    return list;
}

function relevantProducts(result) {
    return (result.products || []).filter((p) => p.relevance >= 1);
}

function bestOffers() {
    const all = [];
    for (const key of state.enabled) {
        const r = search.results[key];
        if (r && r.products) all.push(...relevantProducts(r).filter((p) => p.price != null && p.available));
    }
    const byPrice = all.length ? all.reduce((a, b) => (b.price < a.price ? b : a)) : null;
    const withUnit = all.filter((p) => p.unit_price != null);
    const byUnit = withUnit.length ? withUnit.reduce((a, b) => (b.unit_price < a.unit_price ? b : a)) : null;
    return { byPrice, byUnit };
}

// ---------------------------------------------------------------- rendering

function renderResults() {
    if (!root || !search.query) return;
    productIndex = [];
    $("#add-query-btn").textContent = `+ Ajouter « ${search.query} » à ma liste`;
    const best = bestOffers();
    renderSummary(best);
    setHtml(
        $("#columns"),
        html`${state.retailers.filter((r) => state.enabled.has(r.key)).map((r) => renderColumn(r, best))}`,
    );
}

function renderSummary({ byPrice, byUnit }) {
    const keys = [...state.enabled];
    const done = keys.filter((k) => search.results[k] && search.results[k].status !== "loading").length;
    const cards = [];
    if (byPrice) {
        cards.push(summaryCard("Le moins cher", euros(byPrice.price), byPrice));
    }
    if (byUnit && (!byPrice || byUnit !== byPrice)) {
        cards.push(summaryCard(`Meilleur prix au ${byUnit.unit}`, `${euros(byUnit.unit_price)}/${byUnit.unit}`, byUnit));
    }
    if (done < keys.length) {
        cards.push(
            html`<div class="summary-progress"><span class="spinner"></span> ${done}/${keys.length} enseignes ont répondu…</div>`,
        );
    }
    setHtml($("#summary"), html`${cards}`);
}

function summaryCard(label, value, product) {
    return html`
        <div class="summary-card">
            ${retailerBadge(product.store)}
            <div>
                <div class="label">${label}</div>
                <div class="value">${value}</div>
                <div class="what">${product.name}</div>
            </div>
        </div>`;
}

function row(p, best) {
    return productRow(p, best, productIndex.push(p) - 1);
}

const SKELETON = html`<div class="skeleton"><div class="s-img"></div><div><div class="s-line"></div><div class="s-line short"></div></div></div>`;
const STATUS_TEXT = { empty: "0 produit", store_required: "Magasin à choisir", blocked: "Bloqué", timeout: "Délai dépassé" };

function renderColumn(r, best) {
    const result = search.results[r.key] || { status: "loading" };
    let status;
    const body = [];

    if (result.status === "loading") {
        status = html`<span class="spinner"></span> Recherche…`;
        body.push(SKELETON, SKELETON, SKELETON);
    } else if (result.status === "ok") {
        const relevant = sortProducts(relevantProducts(result));
        // Products sharing at least one word with the query
        const approx = sortProducts(result.products.filter((p) => p.relevance > 0 && p.relevance < 1));
        status = `${plural(relevant.length, "produit")}${result.cached ? " · en cache" : ""}`;
        const expanded = search.expanded[r.key];
        if (relevant.length) {
            const shown = expanded ? relevant : relevant.slice(0, PAGE_SIZE);
            body.push(html`<ul class="products">${shown.map((p) => row(p, best))}</ul>`);
            if (relevant.length > shown.length) {
                body.push(
                    html`<button class="more-btn" type="button" data-more="${r.key}">Voir ${relevant.length - shown.length} de plus</button>`,
                );
            }
        } else {
            body.push(html`<div class="notice">Aucun produit ne contient tous les mots de « ${search.query} ».</div>`);
        }
        if (approx.length && (expanded || !relevant.length)) {
            body.push(html`<div class="approx-title">Résultats approchants</div>
                <ul class="products">${approx.slice(0, expanded ? 50 : PAGE_SIZE).map((p) => row(p, best))}</ul>`);
        } else if (approx.length && relevant.length <= PAGE_SIZE) {
            const what = plural(approx.length, "résultat approchant", "résultats approchants");
            body.push(html`<button class="more-btn" type="button" data-more="${r.key}">Voir ${what}</button>`);
        }
    } else {
        status = STATUS_TEXT[result.status] || "Erreur";
        const actions = [];
        if (result.status === "store_required") {
            actions.push(
                html`<button class="btn-primary small" type="button" data-open-settings="${r.key}">Choisir mon magasin</button>`,
            );
        }
        if (result.status === "blocked") {
            actions.push(html`<button class="btn-primary small" type="button" data-setup="${r.key}">Ouvrir le site</button>`);
        }
        if (result.status !== "empty") {
            actions.push(html`<button class="btn-ghost small" type="button" data-retry="${r.key}">Réessayer</button>`);
        }
        const warn = result.status === "empty" ? "" : " warn";
        body.push(html`<div class="notice${warn}">${result.message || "Erreur inconnue"}
            ${actions.length > 0 && html`<div class="actions">${actions}</div>`}</div>`);
        if (result.status === "store_required" && result.products && result.products.length) {
            body.push(html`<ul class="products">${result.products.slice(0, PAGE_SIZE).map((p) => row(p, best))}</ul>`);
        }
    }

    const sub = result.store_label || (r.store && r.store.name);
    return html`
        <div class="column" data-store="${r.key}">
            <div class="column-head">
                ${retailerBadge(r.key, r.label)}
                <span class="column-status">${status}</span>
            </div>
            ${sub && html`<div class="column-sub">${sub}</div>`}
            ${body}
        </div>`;
}

// ---------------------------------------------------------------- actions

async function addQueryOrProduct(query, product) {
    try {
        await addToList(query, product);
        notify(
            product ? `Ajouté : ${product.name} (${retailer(product.store).label})` : `« ${query} » ajouté à votre liste`,
        );
    } catch (err) {
        notify(err.message, { type: "error" });
    }
}

function bind() {
    $("#refresh-btn").addEventListener("click", () => search.query && emit("search:requested", { query: search.query, refresh: true }));

    $("#sort").addEventListener("change", (e) => {
        search.sort = e.target.value;
        renderResults();
    });

    $("#add-query-btn").addEventListener("click", () => addQueryOrProduct(search.query, null));

    $("#columns").addEventListener("click", async (e) => {
        const target = e.target.closest("button");
        if (!target) return;
        if (target.dataset.more) {
            search.expanded[target.dataset.more] = true;
            renderResults();
        } else if (target.dataset.retry) {
            searchStore(target.dataset.retry, search.token, true);
        } else if (target.dataset.openSettings) {
            navigate("/reglages", { enseigne: target.dataset.openSettings });
        } else if (target.dataset.setup) {
            openSetup(target.dataset.setup);
        } else if (target.dataset.add) {
            await addQueryOrProduct(search.query, productIndex[Number(target.dataset.add)]);
        }
    });
}

// Shows the search of the address; without q, back to the home page
function applyParams(params) {
    const q = (params.q || "").trim();
    if (!q) {
        navigate("/", {}, { replace: true });
        return;
    }
    document.getElementById("q").value = q;
    if (q !== search.query) runSearch(q);
    else renderResults();
}

export const enabled = true;
export const title = (params) => (params.q ? `${params.q} – Rechercher` : "Rechercher");
export const shell = { search: true, filters: true };

export function render(container, params) {
    root = container;
    setHtml(root, TEMPLATE);
    $("#sort").value = search.sort;
    bind();
    applyParams(params);
}

export function update(params) {
    applyParams(params);
}

export function destroy() {
    root = null;
}
