// #/recherche?q=farine : prices of a product at every ticked retailer.
//
// The search state lives in this module: it survives a trip to another view,
// and each retailer column is shown as soon as its retailer answers.

import { api } from "../api.js";
import { productRow } from "../components/productRow.js";
import { retailerBadge } from "../components/retailerBadge.js";
import { mountStoreFilters } from "../components/storeFilters.js";
import { navigate } from "../router.js";
import { addToList, openSetup, retailer, store, subscribe } from "../store.js";
import { escapeHtml, euros, toast } from "../util.js";

const PAGE_SIZE = 5;

const state = {
    query: "",
    results: {},
    searchToken: 0,
    sort: "price",
    expanded: {},
};

let root = null; // container while the view is shown
let unsubscribers = [];
// Products rendered on the page, referenced by the "+" buttons
let productIndex = [];

const TEMPLATE = `
    <form id="search-form" class="search" role="search">
        <input id="q" type="search" placeholder="Farine, huile de tournesol, eau…" autocomplete="off" enterkeyhint="search" aria-label="Produit à rechercher" required>
        <button type="submit" class="btn-primary">Comparer</button>
    </form>
    <div id="store-filters" class="store-filters" aria-label="Enseignes"></div>

    <div id="welcome" class="welcome">
        <p>Tapez un produit pour comparer ses prix chez <strong>Aldi</strong>, <strong>Lidl</strong>, <strong>Carrefour</strong>, <strong>Intermarché</strong> et <strong>Courses U</strong>.</p>
        <div class="suggestions">
            <button type="button" class="suggestion">Farine</button>
            <button type="button" class="suggestion">Huile de tournesol</button>
            <button type="button" class="suggestion">Eau minérale</button>
            <button type="button" class="suggestion">Vinaigre</button>
            <button type="button" class="suggestion">Lait demi-écrémé</button>
            <button type="button" class="suggestion">Sucre</button>
        </div>
        <p id="welcome-setup" class="muted small" hidden>Astuce : indiquez votre code postal et vos magasins (⚙️) pour voir les prix Intermarché et Courses U.</p>
    </div>

    <div id="results" hidden>
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
    state.query = query;
    state.results = {};
    state.expanded = {};
    const token = ++state.searchToken;
    for (const key of store.enabled) state.results[key] = { status: "loading" };
    renderResults();
    for (const key of store.enabled) searchStore(key, token, refresh);
}

// Search started from the view: the address follows the query
function startSearch(query, refresh = false) {
    runSearch(query, refresh);
    if (root) navigate("/recherche", { q: query }, { replace: true });
}

function resetSearch() {
    state.query = "";
    state.results = {};
    state.expanded = {};
    state.searchToken++;
}

async function searchStore(key, token, refresh = false) {
    state.results[key] = { status: "loading" };
    renderResults();
    let result;
    try {
        result = await api(`/api/search/${key}?q=${encodeURIComponent(state.query)}${refresh ? "&refresh=true" : ""}`);
    } catch (err) {
        result = { store: key, status: "error", message: err.message, products: [] };
    }
    if (token !== state.searchToken) return;
    state.results[key] = result;
    renderResults();
}

// A store was chosen or the user acted on a site: search again
subscribe("results-stale", () => {
    if (state.query) runSearch(state.query);
});

// A retailer was ticked (here or in another view): search it too
subscribe("enabled", (key) => {
    if (state.query && store.enabled.has(key) && !state.results[key]) searchStore(key, state.searchToken);
});

function sortProducts(products) {
    const list = [...products];
    if (state.sort === "unit") {
        list.sort((a, b) => (a.unit_price == null) - (b.unit_price == null)
            || (a.unit_price ?? 0) - (b.unit_price ?? 0)
            || (a.price == null) - (b.price == null)
            || (a.price ?? 0) - (b.price ?? 0));
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
    for (const key of store.enabled) {
        const r = state.results[key];
        if (r && r.products) all.push(...relevantProducts(r).filter((p) => p.price != null && p.available));
    }
    const byPrice = all.length ? all.reduce((a, b) => (b.price < a.price ? b : a)) : null;
    const withUnit = all.filter((p) => p.unit_price != null);
    const byUnit = withUnit.length ? withUnit.reduce((a, b) => (b.unit_price < a.unit_price ? b : a)) : null;
    return { byPrice, byUnit };
}

// ---------------------------------------------------------------- rendering

function renderWelcomeSetup() {
    const hint = $("#welcome-setup");
    if (hint) hint.hidden = !store.retailers.some((r) => r.needs_store && !r.store);
}

function renderResults() {
    if (!root) return;
    productIndex = [];
    const hasQuery = Boolean(state.query);
    $("#welcome").hidden = hasQuery;
    $("#results").hidden = !hasQuery;
    if (!hasQuery) return;

    $("#add-query-btn").textContent = `+ Ajouter « ${state.query} » à ma liste`;
    const best = bestOffers();
    renderSummary(best);
    $("#columns").innerHTML = store.retailers
        .filter((r) => store.enabled.has(r.key))
        .map((r) => renderColumn(r, best))
        .join("");
}

function renderSummary({ byPrice, byUnit }) {
    const keys = [...store.enabled];
    const done = keys.filter((k) => state.results[k] && state.results[k].status !== "loading").length;
    const cards = [];
    if (byPrice) {
        cards.push(summaryCard("Le moins cher", euros(byPrice.price), byPrice));
    }
    if (byUnit && (!byPrice || byUnit !== byPrice)) {
        cards.push(summaryCard(`Meilleur prix au ${byUnit.unit}`, `${euros(byUnit.unit_price)}/${byUnit.unit}`, byUnit));
    }
    if (done < keys.length) {
        cards.push(`<div class="summary-progress"><span class="spinner"></span> ${done}/${keys.length} enseignes ont répondu…</div>`);
    }
    $("#summary").innerHTML = cards.join("");
}

function summaryCard(label, value, product) {
    return `
        <div class="summary-card">
            ${retailerBadge(product.store)}
            <div>
                <div class="label">${escapeHtml(label)}</div>
                <div class="value">${escapeHtml(value)}</div>
                <div class="what">${escapeHtml(product.name)}</div>
            </div>
        </div>`;
}

function row(p, best) {
    return productRow(p, best, productIndex.push(p) - 1);
}

function renderColumn(r, best) {
    const result = state.results[r.key] || { status: "loading" };
    let status = "";
    let body = "";

    if (result.status === "loading") {
        status = `<span class="spinner"></span> Recherche…`;
        body = `<div class="skeleton"><div class="s-img"></div><div><div class="s-line"></div><div class="s-line" style="width:60%"></div></div></div>`.repeat(3);
    } else if (result.status === "ok") {
        const relevant = sortProducts(relevantProducts(result));
        // Products sharing at least one word with the query
        const approx = sortProducts(result.products.filter((p) => p.relevance > 0 && p.relevance < 1));
        status = `${relevant.length} produit${relevant.length > 1 ? "s" : ""}${result.cached ? " · en cache" : ""}`;
        const expanded = state.expanded[r.key];
        if (relevant.length) {
            const shown = expanded ? relevant : relevant.slice(0, PAGE_SIZE);
            body += `<ul class="products">${shown.map((p) => row(p, best)).join("")}</ul>`;
            if (relevant.length > shown.length) {
                body += `<button class="more-btn" type="button" data-more="${r.key}">Voir ${relevant.length - shown.length} de plus</button>`;
            }
        } else {
            body += `<div class="notice">Aucun produit ne contient tous les mots de « ${escapeHtml(state.query)} ».</div>`;
        }
        if (approx.length && (expanded || !relevant.length)) {
            body += `<div class="approx-title">Résultats approchants</div>
                <ul class="products">${approx.slice(0, expanded ? 50 : PAGE_SIZE).map((p) => row(p, best)).join("")}</ul>`;
        } else if (approx.length && relevant.length <= PAGE_SIZE) {
            body += `<button class="more-btn" type="button" data-more="${r.key}">Voir ${approx.length} résultat${approx.length > 1 ? "s" : ""} approchant${approx.length > 1 ? "s" : ""}</button>`;
        }
    } else {
        status = { empty: "0 produit", store_required: "Magasin à choisir", blocked: "Bloqué", timeout: "Délai dépassé" }[result.status] || "Erreur";
        const actions = [];
        if (result.status === "store_required") actions.push(`<button class="btn-primary small" type="button" data-open-settings="${r.key}">Choisir mon magasin</button>`);
        if (result.status === "blocked") actions.push(`<button class="btn-primary small" type="button" data-setup="${r.key}">Ouvrir le site</button>`);
        if (result.status !== "empty") actions.push(`<button class="btn-ghost small" type="button" data-retry="${r.key}">Réessayer</button>`);
        const warn = result.status === "empty" ? "" : " warn";
        body = `<div class="notice${warn}">${escapeHtml(result.message || "Erreur inconnue")}
            ${actions.length ? `<div class="actions">${actions.join("")}</div>` : ""}</div>`;
        if (result.status === "store_required" && result.products && result.products.length) {
            body += `<ul class="products">${result.products.slice(0, PAGE_SIZE).map((p) => row(p, best)).join("")}</ul>`;
        }
    }

    const sub = result.store_label || (r.store && r.store.name);
    return `
        <div class="column" data-store="${r.key}">
            <div class="column-head">
                ${retailerBadge(r.key, r.label)}
                <span class="column-status">${status}</span>
            </div>
            ${sub ? `<div class="column-sub">${escapeHtml(sub)}</div>` : ""}
            ${body}
        </div>`;
}

// ---------------------------------------------------------------- actions

async function addQueryOrProduct(query, product) {
    try {
        await addToList(query, product);
        toast(product ? `Ajouté : ${product.name} (${retailer(product.store).label})` : `« ${query} » ajouté à votre liste`);
    } catch (err) {
        toast(err.message, true);
    }
}

function bind() {
    $("#search-form").addEventListener("submit", (e) => {
        e.preventDefault();
        const q = $("#q").value.trim();
        if (q) startSearch(q);
    });

    root.querySelectorAll(".suggestion").forEach((btn) =>
        btn.addEventListener("click", () => {
            $("#q").value = btn.textContent;
            startSearch(btn.textContent);
        }));

    $("#refresh-btn").addEventListener("click", () => state.query && startSearch(state.query, true));

    $("#sort").addEventListener("change", (e) => {
        state.sort = e.target.value;
        renderResults();
    });

    $("#add-query-btn").addEventListener("click", () => addQueryOrProduct(state.query, null));

    $("#columns").addEventListener("click", async (e) => {
        const target = e.target.closest("button");
        if (!target) return;
        if (target.dataset.more) {
            state.expanded[target.dataset.more] = true;
            renderResults();
        } else if (target.dataset.retry) {
            searchStore(target.dataset.retry, state.searchToken, true);
        } else if (target.dataset.openSettings) {
            navigate("/reglages", { enseigne: target.dataset.openSettings });
        } else if (target.dataset.setup) {
            openSetup(target.dataset.setup);
        } else if (target.dataset.add) {
            await addQueryOrProduct(state.query, productIndex[Number(target.dataset.add)]);
        }
    });

    // The search of a newly ticked retailer starts in the "enabled" subscriber above
    mountStoreFilters($("#store-filters"), () => renderResults());
}

// Shows the search of the address (#/recherche?q=...), the welcome without q
function applyParams(params) {
    const q = (params.q || "").trim();
    $("#q").value = q;
    if (!q) {
        resetSearch();
        renderResults();
    } else if (q !== state.query) {
        runSearch(q);
    } else {
        renderResults();
    }
}

export default {
    name: "search",
    path: "/recherche",
    title: (params) => (params.q ? `${params.q} – Rechercher` : "Rechercher"),
    nav: { label: "Rechercher", order: 10, keepParams: true },

    render(container, params) {
        root = container;
        root.innerHTML = TEMPLATE;
        $("#sort").value = state.sort;
        bind();
        renderWelcomeSetup();
        unsubscribers = [subscribe("settings", renderWelcomeSetup)];
        applyParams(params);
    },

    update(params) {
        applyParams(params);
    },

    destroy() {
        unsubscribers.forEach((off) => off());
        unsubscribers = [];
        root = null;
    },
};
