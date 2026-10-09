"use strict";

const $ = (sel) => document.querySelector(sel);

const state = {
    retailers: [],
    settings: null,
    enabled: new Set(),
    query: "",
    results: {},
    searchToken: 0,
    sort: "price",
    expanded: {},
    list: [],
    browser: null,
    intermarcheStores: null,
};

const PAGE_SIZE = 5;

// ---------------------------------------------------------------- helpers

async function api(path, options = {}) {
    const resp = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options,
        body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
    if (resp.status === 204) return null;
    const data = await resp.json().catch(() => null);
    if (!resp.ok) {
        const detail = data && data.detail;
        const message = Array.isArray(detail) ? detail.map((d) => d.msg).join(", ") : detail;
        throw new Error(message || `Erreur serveur (${resp.status})`);
    }
    return data;
}

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function euros(value) {
    return value == null ? "" : `${value.toFixed(2).replace(".", ",")} €`;
}

function unitText(p) {
    if (p.unit_price != null && p.unit) return `${euros(p.unit_price)}/${p.unit}`;
    return p.unit_price_label || "";
}

function retailer(key) {
    return state.retailers.find((r) => r.key === key) || { key, label: key };
}

let toastTimer = null;
function toast(message, isError = false) {
    const el = $("#toast");
    el.textContent = message;
    el.classList.toggle("error", isError);
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 3000);
}

function loadEnabled() {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem("prixmalin.enabled")); } catch { /* ignore */ }
    const keys = state.retailers.map((r) => r.key);
    state.enabled = new Set(Array.isArray(saved) ? saved.filter((k) => keys.includes(k)) : keys);
    if (state.enabled.size === 0) state.enabled = new Set(keys);
}

function saveEnabled() {
    try { localStorage.setItem("prixmalin.enabled", JSON.stringify([...state.enabled])); } catch { /* ignore */ }
}

// ---------------------------------------------------------------- store filters

function renderFilters() {
    $("#store-filters").innerHTML = state.retailers.map((r) => `
        <label class="store-toggle ${state.enabled.has(r.key) ? "on" : ""}">
            <input type="checkbox" value="${r.key}" ${state.enabled.has(r.key) ? "checked" : ""}>
            <span class="dot ${r.key}-bg"></span>${escapeHtml(r.label)}
        </label>`).join("");
}

$("#store-filters").addEventListener("change", (e) => {
    const key = e.target.value;
    if (e.target.checked) state.enabled.add(key);
    else if (state.enabled.size > 1) state.enabled.delete(key);
    else e.target.checked = true;
    saveEnabled();
    renderFilters();
    if (state.query && e.target.checked && !state.results[key]) searchStore(key, state.searchToken);
    renderResults();
});

// ---------------------------------------------------------------- search

$("#search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("#q").value.trim();
    if (q) startSearch(q);
});

document.querySelectorAll(".suggestion").forEach((btn) =>
    btn.addEventListener("click", () => {
        $("#q").value = btn.textContent;
        startSearch(btn.textContent);
    }));

$("#refresh-btn").addEventListener("click", () => state.query && startSearch(state.query, true));

$("#sort").addEventListener("change", (e) => {
    state.sort = e.target.value;
    renderResults();
});

function startSearch(query, refresh = false) {
    state.query = query;
    state.results = {};
    state.expanded = {};
    const token = ++state.searchToken;
    showTab("results");
    history.replaceState(null, "", `?q=${encodeURIComponent(query)}`);
    for (const key of state.enabled) state.results[key] = { status: "loading" };
    renderResults();
    for (const key of state.enabled) searchStore(key, token, refresh);
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
    for (const key of state.enabled) {
        const r = state.results[key];
        if (r && r.products) all.push(...relevantProducts(r).filter((p) => p.price != null && p.available));
    }
    const byPrice = all.length ? all.reduce((a, b) => (b.price < a.price ? b : a)) : null;
    const withUnit = all.filter((p) => p.unit_price != null);
    const byUnit = withUnit.length ? withUnit.reduce((a, b) => (b.unit_price < a.unit_price ? b : a)) : null;
    return { byPrice, byUnit };
}

// Products rendered on the page, referenced by the "+" buttons
let productIndex = [];

function renderResults() {
    productIndex = [];
    const hasQuery = Boolean(state.query);
    $("#welcome").hidden = hasQuery;
    $("#results").hidden = !hasQuery;
    if (!hasQuery) return;

    $("#add-query-btn").textContent = `+ Ajouter « ${state.query} » à ma liste`;
    const best = bestOffers();
    renderSummary(best);
    $("#columns").innerHTML = state.retailers
        .filter((r) => state.enabled.has(r.key))
        .map((r) => renderColumn(r, best))
        .join("");
}

function renderSummary({ byPrice, byUnit }) {
    const keys = [...state.enabled];
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
            <span class="badge ${product.store}-bg">${escapeHtml(retailer(product.store).label)}</span>
            <div>
                <div class="label">${escapeHtml(label)}</div>
                <div class="value">${escapeHtml(value)}</div>
                <div class="what">${escapeHtml(product.name)}</div>
            </div>
        </div>`;
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
            body += `<ul class="products">${shown.map((p) => productRow(p, best)).join("")}</ul>`;
            if (relevant.length > shown.length) {
                body += `<button class="more-btn" data-more="${r.key}">Voir ${relevant.length - shown.length} de plus</button>`;
            }
        } else {
            body += `<div class="notice">Aucun produit ne contient tous les mots de « ${escapeHtml(state.query)} ».</div>`;
        }
        if (approx.length && (expanded || !relevant.length)) {
            body += `<div class="approx-title">Résultats approchants</div>
                <ul class="products">${approx.slice(0, expanded ? 50 : PAGE_SIZE).map((p) => productRow(p, best)).join("")}</ul>`;
        } else if (approx.length && relevant.length <= PAGE_SIZE) {
            body += `<button class="more-btn" data-more="${r.key}">Voir ${approx.length} résultat${approx.length > 1 ? "s" : ""} approchant${approx.length > 1 ? "s" : ""}</button>`;
        }
    } else {
        status = { empty: "0 produit", store_required: "Magasin à choisir", blocked: "Bloqué", timeout: "Délai dépassé" }[result.status] || "Erreur";
        const actions = [];
        if (result.status === "store_required") actions.push(`<button class="btn-primary small" data-open-settings="${r.key}">Choisir mon magasin</button>`);
        if (result.status === "blocked") actions.push(`<button class="btn-primary small" data-setup="${r.key}">Ouvrir le site</button>`);
        if (result.status !== "empty") actions.push(`<button class="btn-ghost small" data-retry="${r.key}">Réessayer</button>`);
        const warn = result.status === "empty" ? "" : " warn";
        body = `<div class="notice${warn}">${escapeHtml(result.message || "Erreur inconnue")}
            ${actions.length ? `<div class="actions">${actions.join("")}</div>` : ""}</div>`;
        if (result.status === "store_required" && result.products && result.products.length) {
            body += `<ul class="products">${result.products.slice(0, PAGE_SIZE).map((p) => productRow(p, best)).join("")}</ul>`;
        }
    }

    const sub = result.store_label || (r.store && r.store.name);
    return `
        <div class="column" data-store="${r.key}">
            <div class="column-head">
                <span class="badge ${r.key}-bg">${escapeHtml(r.label)}</span>
                <span class="column-status">${status}</span>
            </div>
            ${sub ? `<div class="column-sub">${escapeHtml(sub)}</div>` : ""}
            ${body}
        </div>`;
}

function productRow(p, best) {
    const isBest = best.byPrice && p === best.byPrice;
    const isBestUnit = best.byUnit && p === best.byUnit;
    const tags = [];
    if (isBest) tags.push(`<span class="tag best">Le moins cher</span>`);
    if (isBestUnit && !isBest) tags.push(`<span class="tag best">Meilleur prix au ${escapeHtml(p.unit)}</span>`);
    if (p.promo) tags.push(`<span class="tag promo">${escapeHtml(p.promo)}</span>`);
    if (!p.available) tags.push(`<span class="tag out">Indisponible</span>`);
    const meta = [p.brand, p.quantity_label].filter(Boolean).map(escapeHtml).join(" · ");
    const image = p.image_url
        ? `<img src="${escapeHtml(p.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">`
        : "🛒";
    const index = productIndex.push(p) - 1;
    return `
        <li class="product${isBest || isBestUnit ? " best" : ""}${p.available ? "" : " unavailable"}">
            <div class="thumb">${image}</div>
            <div class="info">
                <a class="name" href="${escapeHtml(p.product_url)}" target="_blank" rel="noopener">${escapeHtml(p.name)}</a>
                ${meta ? `<div class="meta">${meta}</div>` : ""}
                ${tags.join("")}
            </div>
            <div class="pricing">
                ${p.price != null ? `<div class="price">${euros(p.price)}</div>` : `<div class="price none">Prix non affiché</div>`}
                ${unitText(p) ? `<div class="unit">${escapeHtml(unitText(p))}</div>` : ""}
                <button class="add-btn" data-add="${index}" title="Ajouter ce produit à ma liste" aria-label="Ajouter à ma liste">+</button>
            </div>
        </li>`;
}

$("#columns").addEventListener("click", async (e) => {
    const target = e.target.closest("button");
    if (!target) return;
    if (target.dataset.more) {
        state.expanded[target.dataset.more] = true;
        renderResults();
    } else if (target.dataset.retry) {
        searchStore(target.dataset.retry, state.searchToken, true);
    } else if (target.dataset.openSettings) {
        openSettings(target.dataset.openSettings);
    } else if (target.dataset.setup) {
        openSetup(target.dataset.setup);
    } else if (target.dataset.add) {
        const product = productIndex[Number(target.dataset.add)];
        await addToList(state.query, product);
    }
});

$("#add-query-btn").addEventListener("click", () => addToList(state.query, null));

// ---------------------------------------------------------------- tabs

document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => showTab(tab.dataset.tab)));

function showTab(name) {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    $("#tab-results").hidden = name !== "results";
    $("#tab-list").hidden = name !== "list";
    if (name === "list") renderList();
}

// ---------------------------------------------------------------- shopping list

async function loadList() {
    try {
        state.list = await api("/api/list");
    } catch {
        state.list = [];
    }
    renderListCount();
}

function renderListCount() {
    $("#list-count").textContent = state.list.length;
}

async function addToList(query, product) {
    try {
        await api("/api/list", { method: "POST", body: { query, quantity: 1, product } });
        await loadList();
        toast(product ? `Ajouté : ${product.name} (${retailer(product.store).label})` : `« ${query} » ajouté à votre liste`);
    } catch (err) {
        toast(err.message, true);
    }
}

$("#list-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = $("#list-input").value.trim();
    const quantity = Math.max(1, Math.min(99, Number($("#list-qty").value) || 1));
    if (!query) return;
    try {
        await api("/api/list", { method: "POST", body: { query, quantity } });
        $("#list-input").value = "";
        $("#list-qty").value = 1;
        await loadList();
        renderList();
    } catch (err) {
        toast(err.message, true);
    }
});

function renderList() {
    const items = state.list;
    $("#list-actions").hidden = items.length === 0;
    if (!items.length) {
        $("#list-items").innerHTML = `<li class="muted">Votre liste est vide.</li>`;
        $("#basket").innerHTML = "";
        return;
    }
    $("#list-items").innerHTML = items.map((item) => {
        const picks = Object.entries(item.picks || {}).map(([store, p]) => `
            <span class="pick" title="${escapeHtml(p.name)}">
                <span class="dot ${store}-bg"></span>
                <span class="txt">${escapeHtml(retailer(store).label)} : ${escapeHtml(p.name)}${p.price != null ? ` (${euros(p.price)})` : ""}</span>
                <button data-unpick="${item.id}" data-store="${store}" aria-label="Retirer ce choix">✕</button>
            </span>`).join("");
        return `
            <li class="list-item">
                <div class="list-main">
                    <strong>${escapeHtml(item.query)}</strong>
                    ${picks ? `<div class="picks">${picks}</div>` : `<div class="muted small">Le moins cher des produits correspondants sera retenu.</div>`}
                </div>
                <div class="qty">
                    <button data-qty="${item.id}" data-delta="-1" aria-label="Moins">−</button>
                    <span>${item.quantity}</span>
                    <button data-qty="${item.id}" data-delta="1" aria-label="Plus">+</button>
                </div>
                <button class="icon-btn" data-delete="${item.id}" aria-label="Supprimer">🗑</button>
            </li>`;
    }).join("");
}

$("#list-items").addEventListener("click", async (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    try {
        if (btn.dataset.qty) {
            const item = state.list.find((i) => i.id === Number(btn.dataset.qty));
            const quantity = item.quantity + Number(btn.dataset.delta);
            if (quantity < 1) await api(`/api/list/${item.id}`, { method: "DELETE" });
            else await api(`/api/list/${item.id}`, { method: "PATCH", body: { quantity } });
        } else if (btn.dataset.delete) {
            await api(`/api/list/${btn.dataset.delete}`, { method: "DELETE" });
        } else if (btn.dataset.unpick) {
            await api(`/api/list/${btn.dataset.unpick}`, { method: "PATCH", body: { remove_pick: btn.dataset.store } });
        }
        await loadList();
        renderList();
    } catch (err) {
        toast(err.message, true);
    }
});

$("#clear-list-btn").addEventListener("click", async () => {
    if (!confirm("Vider toute la liste ?")) return;
    await api("/api/list", { method: "DELETE" });
    await loadList();
    renderList();
});

$("#compare-btn").addEventListener("click", async () => {
    const btn = $("#compare-btn");
    btn.disabled = true;
    $("#basket").innerHTML = `<p class="muted"><span class="spinner"></span> Recherche de chaque article dans ${state.enabled.size} enseignes… (plus rapide les fois suivantes grâce au cache)</p>`;
    try {
        const comparison = await api("/api/basket/compare", { method: "POST", body: { stores: [...state.enabled] } });
        renderBasket(comparison);
    } catch (err) {
        $("#basket").innerHTML = `<div class="notice warn">${escapeHtml(err.message)}</div>`;
    } finally {
        btn.disabled = false;
    }
});

function renderBasket(comparison) {
    const stores = [...comparison.stores].sort((a, b) => (a.missing - b.missing) || (a.total - b.total));
    const lineFor = (s, item) => s.lines.find((l) => l.item_id === item.id);
    const cards = stores.map((s) => `
        <div class="basket-card${s.store === comparison.best_store ? " best" : ""}">
            <span class="badge ${s.store}-bg">${escapeHtml(s.label)}</span>
            <div class="total">${s.missing === s.lines.length ? "—" : euros(s.total)}</div>
            <div class="small ${s.missing ? "muted" : ""}">${s.missing ? `${s.missing} article${s.missing > 1 ? "s" : ""} non trouvé${s.missing > 1 ? "s" : ""}` : "Panier complet"}</div>
            ${s.store === comparison.best_store ? `<div class="small"><strong>Panier le moins cher</strong></div>` : ""}
            ${s.message ? `<div class="small muted">${escapeHtml(s.message)}</div>` : ""}
        </div>`).join("");

    const split = comparison.split_total != null
        ? `<p class="basket-split">En achetant chaque article là où il est le moins cher : <strong>${euros(comparison.split_total)}</strong>${comparison.split_missing ? ` (${comparison.split_missing} article(s) introuvable(s))` : ""}</p>`
        : "";

    const rows = state.list.map((item) => {
        const totals = stores.map((s) => lineFor(s, item)?.line_total).filter((v) => v != null);
        const min = totals.length ? Math.min(...totals) : null;
        const cells = stores.map((s) => {
            const line = lineFor(s, item);
            if (!line || line.line_total == null) return `<td class="cell muted">—</td>`;
            return `<td class="cell${line.line_total === min ? " cheapest" : ""}">
                <span class="cell-price">${euros(line.line_total)}</span>${line.quantity > 1 ? ` <span class="muted">(${line.quantity} × ${euros(line.product.price)})</span>` : ""}
                <a class="cell-name" href="${escapeHtml(line.product.product_url)}" target="_blank" rel="noopener">${line.picked ? "★ " : ""}${escapeHtml(line.product.name)}</a>
            </td>`;
        }).join("");
        return `<tr><th>${escapeHtml(item.query)}${item.quantity > 1 ? ` ×${item.quantity}` : ""}</th>${cells}</tr>`;
    }).join("");

    $("#basket").innerHTML = `
        <div class="basket-cards">${cards}</div>
        ${split}
        <div class="table-wrap">
            <table class="basket-table">
                <thead><tr><th>Article</th>${stores.map((s) => `<th><span class="badge ${s.store}-bg">${escapeHtml(s.label)}</span></th>`).join("")}</tr></thead>
                <tbody>${rows}</tbody>
                <tfoot><tr><td>Total</td>${stores.map((s) => `<td>${s.missing === s.lines.length ? "—" : euros(s.total)}</td>`).join("")}</tr></tfoot>
            </table>
        </div>
        <p class="muted small">★ = produit choisi par vous. Sinon, le produit le moins cher contenant tous les mots de l'article est retenu.</p>`;
}

// ---------------------------------------------------------------- settings

const dialog = $("#settings-dialog");

$("#settings-btn").addEventListener("click", () => openSettings());
$("#location-chip").addEventListener("click", () => openSettings());
$("#settings-close").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });

async function loadSettings() {
    const [retailers, settings, browser] = await Promise.all([
        api("/api/retailers"), api("/api/settings"), api("/api/browser"),
    ]);
    state.retailers = retailers;
    state.settings = settings;
    state.browser = browser;
    renderLocationChip();
    renderSetupBanner();
}

function renderLocationChip() {
    const loc = state.settings && state.settings.location;
    $("#location-label").textContent = loc ? (loc.city ? `${loc.postal_code} ${loc.city}` : loc.postal_code) : "Code postal";
    $("#location-chip").classList.toggle("configured", Boolean(loc));
    const missingStores = state.retailers.some((r) => r.needs_store && !r.store);
    $("#welcome-setup").hidden = !missingStores;
}

function renderSetupBanner() {
    $("#setup-banner").hidden = !(state.browser && state.browser.setup_mode);
}

async function openSettings(focusKey) {
    try {
        await loadSettings();
    } catch (err) {
        toast(err.message, true);
    }
    renderSettings();
    if (!dialog.open) dialog.showModal();
    if (focusKey) {
        const el = dialog.querySelector(`[data-retailer="${focusKey}"]`);
        if (el) el.scrollIntoView({ block: "center" });
    }
}

function renderSettings() {
    const loc = state.settings.location;
    $("#postal-input").value = loc ? loc.postal_code : "";
    $("#location-info").textContent = loc
        ? (loc.lat != null ? `Localisation : ${loc.city || loc.postal_code}` : `Code postal ${loc.postal_code} enregistré (ville introuvable : la recherche de magasins Intermarché ne marchera pas).`)
        : "Nécessaire pour trouver votre magasin Intermarché.";
    $("#show-browser").checked = state.settings.show_browser;

    $("#retailer-settings").innerHTML = `<h3>Enseignes</h3>` + state.retailers.map(renderRetailerSettings).join("");

    const b = state.browser;
    $("#browser-status").textContent = b
        ? (b.error ? `Problème : ${b.error}` : b.running ? `Navigateur actif (${b.channel || "chromium"}, ${b.headless ? "invisible" : "visible"}).` : "Le navigateur démarrera à la première recherche.")
        : "";
}

function renderRetailerSettings(r) {
    const configured = Boolean(r.store);
    const state_ = r.needs_store
        ? (configured ? `<span class="state ok">✓ ${escapeHtml(r.store.name || "Magasin choisi")}</span>` : `<span class="state todo">Magasin à choisir</span>`)
        : `<span class="state ok">Prêt</span>`;
    let extra = "";
    if (r.key === "intermarche") {
        const stores = state.intermarcheStores;
        extra = `
            ${configured && r.store.address ? `<p class="small muted">${escapeHtml(r.store.address)}</p>` : ""}
            <div class="retailer-actions">
                <button class="btn-ghost small" data-find-stores>Trouver les magasins proches</button>
                ${configured ? `<button class="btn-ghost small danger" data-remove-store="intermarche">Retirer</button>` : ""}
            </div>
            ${stores === "loading" ? `<p class="small muted"><span class="spinner"></span> Recherche des magasins…</p>` : ""}
            ${Array.isArray(stores) ? (stores.length ? `<ul class="store-list">${stores.map((s) => `
                <li><button data-pick-store="${escapeHtml(s.id)}">
                    <strong>${escapeHtml(s.name)}</strong>${s.distance_km != null ? ` · ${String(s.distance_km).replace(".", ",")} km` : ""}
                    ${s.address ? `<span class="addr">${escapeHtml(s.address)}</span>` : ""}
                </button></li>`).join("")}</ul>` : `<p class="small muted">Aucun magasin trouvé autour de chez vous.</p>`) : ""}`;
    } else if (r.key === "coursesu") {
        extra = `
            <form class="row" data-coursesu-form>
                <input name="url" type="url" placeholder="https://www.coursesu.com/drive-superu-..." value="${escapeHtml(configured && r.store.url ? r.store.url : "")}" aria-label="Adresse du magasin Courses U">
                <button class="btn-primary small" type="submit">Enregistrer</button>
            </form>
            ${configured ? `<div class="retailer-actions"><button class="btn-ghost small danger" data-remove-store="coursesu">Retirer</button></div>` : ""}`;
    }
    return `
        <div class="retailer-card" data-retailer="${r.key}">
            <div class="retailer-head"><span class="badge ${r.key}-bg">${escapeHtml(r.label)}</span>${state_}</div>
            <p class="small muted">${escapeHtml(r.store_hint)}</p>
            ${extra}
            <div class="retailer-actions"><button class="btn-ghost small" data-setup="${r.key}">Ouvrir le site</button></div>
        </div>`;
}

$("#location-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    await saveLocation($("#postal-input").value.trim());
});

async function saveLocation(postalCode, city) {
    if (!/^\d{5}$/.test(postalCode)) {
        toast("Le code postal doit contenir 5 chiffres", true);
        return;
    }
    try {
        const res = await api("/api/settings/location", { method: "POST", body: { postal_code: postalCode, city } });
        state.settings = res.settings;
        state.intermarcheStores = null;
        $("#commune-choice").innerHTML = res.communes.length > 1 && !city
            ? `<div class="commune-list">${res.communes.map((c) => `<button class="btn-ghost small" data-commune="${escapeHtml(c.city)}">${escapeHtml(c.city)}</button>`).join("")}</div>`
            : "";
        renderLocationChip();
        renderSettings();
        toast(`Localisation enregistrée : ${res.settings.location.city || postalCode}`);
    } catch (err) {
        toast(err.message, true);
    }
}

$("#commune-choice").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-commune]");
    if (!btn) return;
    $("#commune-choice").innerHTML = "";
    saveLocation($("#postal-input").value.trim(), btn.dataset.commune);
});

$("#show-browser").addEventListener("change", async (e) => {
    try {
        state.settings = await api("/api/settings", { method: "PATCH", body: { show_browser: e.target.checked } });
        state.browser = await api("/api/browser");
        renderSettings();
    } catch (err) {
        e.target.checked = !e.target.checked;
        toast(err.message, true);
    }
});

$("#retailer-settings").addEventListener("click", async (e) => {
    const btn = e.target.closest("button");
    if (!btn || btn.type === "submit") return;
    try {
        if (btn.hasAttribute("data-find-stores")) {
            if (!state.settings.location || state.settings.location.lat == null) {
                toast("Indiquez d'abord votre code postal", true);
                return;
            }
            state.intermarcheStores = "loading";
            renderSettings();
            try {
                state.intermarcheStores = await api("/api/retailers/intermarche/stores");
            } catch (err) {
                state.intermarcheStores = null;
                throw err;
            } finally {
                renderSettings();
            }
        } else if (btn.dataset.pickStore) {
            const store = state.intermarcheStores.find((s) => s.id === btn.dataset.pickStore);
            await api("/api/retailers/intermarche/store", { method: "PUT", body: { id: store.id, name: store.name, address: store.address } });
            state.intermarcheStores = null;
            await afterStoreChange(`Magasin Intermarché : ${store.name}`);
        } else if (btn.dataset.removeStore) {
            await api(`/api/retailers/${btn.dataset.removeStore}/store`, { method: "DELETE" });
            await afterStoreChange("Magasin retiré");
        } else if (btn.dataset.setup) {
            await openSetup(btn.dataset.setup);
        }
    } catch (err) {
        toast(err.message, true);
    }
});

$("#retailer-settings").addEventListener("submit", async (e) => {
    if (!e.target.matches("[data-coursesu-form]")) return;
    e.preventDefault();
    const url = e.target.elements.url.value.trim();
    try {
        const settings = await api("/api/retailers/coursesu/store", { method: "PUT", body: { url } });
        await afterStoreChange(`Magasin Courses U : ${settings.stores.coursesu.name}`);
    } catch (err) {
        toast(err.message, true);
    }
});

async function afterStoreChange(message) {
    await loadSettings();
    renderSettings();
    toast(message);
    if (state.query) startSearch(state.query);
}

// ---------------------------------------------------------------- manual setup in the browser

async function openSetup(key) {
    toast(`Ouverture de ${retailer(key).label}…`);
    try {
        state.browser = await api("/api/browser/setup", { method: "POST", body: { store: key } });
        renderSetupBanner();
        if (dialog.open) renderSettings();
        toast(`${retailer(key).label} est ouvert dans la fenêtre du navigateur PrixMalin. Cliquez sur « J'ai terminé » ensuite.`);
    } catch (err) {
        toast(err.message, true);
    }
}

$("#setup-banner-done").addEventListener("click", async () => {
    try {
        state.browser = await api("/api/browser/setup/done", { method: "POST" });
        renderSetupBanner();
        toast("C'est noté, les recherches reprennent en arrière-plan");
        if (state.query) startSearch(state.query);
    } catch (err) {
        toast(err.message, true);
    }
});

// ---------------------------------------------------------------- text size

// Multiplies the 16px base (CSS: html { font-size: calc(16px * var(--ui-scale)) })
const TEXT_SCALES = [0.9, 1, 1.125, 1.25, 1.4, 1.6];

function defaultScale() {
    return window.matchMedia("(min-width: 900px)").matches ? 1.125 : 1;
}

function currentScale() {
    let saved = null;
    try { saved = Number(localStorage.getItem("prixmalin.textScale")); } catch { /* ignore */ }
    return TEXT_SCALES.includes(saved) ? saved : defaultScale();
}

function applyScale(scale, save) {
    document.documentElement.style.setProperty("--ui-scale", String(scale));
    $("#text-smaller").disabled = scale <= TEXT_SCALES[0];
    $("#text-bigger").disabled = scale >= TEXT_SCALES[TEXT_SCALES.length - 1];
    if (save) {
        try { localStorage.setItem("prixmalin.textScale", String(scale)); } catch { /* ignore */ }
    }
}

function stepScale(direction) {
    const index = TEXT_SCALES.indexOf(currentScale());
    const next = TEXT_SCALES[Math.max(0, Math.min(TEXT_SCALES.length - 1, index + direction))];
    applyScale(next, true);
}

$("#text-smaller").addEventListener("click", () => stepScale(-1));
$("#text-bigger").addEventListener("click", () => stepScale(1));
applyScale(currentScale(), false);

// ---------------------------------------------------------------- start

(async function init() {
    try {
        await loadSettings();
    } catch (err) {
        toast(`Serveur injoignable : ${err.message}`, true);
        return;
    }
    loadEnabled();
    renderFilters();
    await loadList();
    const q = new URLSearchParams(location.search).get("q");
    if (q) {
        $("#q").value = q;
        startSearch(q);
    }
})();
