// #/liste : shopping list and basket comparison between the ticked retailers.

import { api } from "../api.js";
import { retailerBadge, retailerDot } from "../components/retailerBadge.js";
import { mountStoreFilters } from "../components/storeFilters.js";
import { addToList, loadList, retailer, store, subscribe } from "../store.js";
import { escapeHtml, euros, safeUrl, toast } from "../util.js";

// Kept while the view is hidden, like the old "Ma liste" tab
const local = { basketHtml: "", comparing: false };

let root = null;
let unsubscribers = [];

const TEMPLATE = `
    <div id="store-filters" class="store-filters" aria-label="Enseignes"></div>
    <form id="list-form" class="list-form">
        <input id="list-input" placeholder="Ajouter un article (ex : lait demi-écrémé)" maxlength="120" aria-label="Article" required>
        <input id="list-qty" type="number" min="1" max="99" value="1" aria-label="Quantité">
        <button class="btn-primary" type="submit">Ajouter</button>
    </form>
    <p class="muted small">Ajoutez des articles ici, ou avec le bouton <strong>+</strong> d'un produit dans les résultats pour choisir un produit précis.</p>
    <ul id="list-items" class="list-items"></ul>
    <div id="list-actions" class="list-actions" hidden>
        <button id="compare-btn" class="btn-primary" type="button">Comparer mon panier</button>
        <button id="clear-list-btn" class="btn-ghost danger" type="button">Vider la liste</button>
    </div>
    <div id="basket"></div>`;

const $ = (sel) => (root ? root.querySelector(sel) : null);

function setBasket(html) {
    local.basketHtml = html;
    const el = $("#basket");
    if (el) el.innerHTML = html;
}

function renderList() {
    if (!root) return;
    const items = store.list;
    $("#list-actions").hidden = items.length === 0;
    if (!items.length) {
        $("#list-items").innerHTML = `<li class="muted">Votre liste est vide.</li>`;
        setBasket("");
        return;
    }
    $("#list-items").innerHTML = items.map((item) => {
        const picks = Object.entries(item.picks || {}).map(([key, p]) => `
            <span class="pick" title="${escapeHtml(p.name)}">
                ${retailerDot(key)}
                <span class="txt">${escapeHtml(retailer(key).label)} : ${escapeHtml(p.name)}${p.price != null ? ` (${euros(p.price)})` : ""}</span>
                <button type="button" data-unpick="${item.id}" data-store="${escapeHtml(key)}" aria-label="Retirer ce choix">✕</button>
            </span>`).join("");
        return `
            <li class="list-item">
                <div class="list-main">
                    <strong>${escapeHtml(item.query)}</strong>
                    ${picks ? `<div class="picks">${picks}</div>` : `<div class="muted small">Le moins cher des produits correspondants sera retenu.</div>`}
                </div>
                <div class="qty">
                    <button type="button" data-qty="${item.id}" data-delta="-1" aria-label="Moins">−</button>
                    <span>${item.quantity}</span>
                    <button type="button" data-qty="${item.id}" data-delta="1" aria-label="Plus">+</button>
                </div>
                <button class="icon-btn" type="button" data-delete="${item.id}" aria-label="Supprimer">🗑</button>
            </li>`;
    }).join("");
}

function basketHtml(comparison) {
    const stores = [...comparison.stores].sort((a, b) => (a.missing - b.missing) || (a.total - b.total));
    const lineFor = (s, item) => s.lines.find((l) => l.item_id === item.id);
    const cards = stores.map((s) => `
        <div class="basket-card${s.store === comparison.best_store ? " best" : ""}">
            ${retailerBadge(s.store, s.label)}
            <div class="total">${s.missing === s.lines.length ? "—" : euros(s.total)}</div>
            <div class="small ${s.missing ? "muted" : ""}">${s.missing ? `${s.missing} article${s.missing > 1 ? "s" : ""} non trouvé${s.missing > 1 ? "s" : ""}` : "Panier complet"}</div>
            ${s.store === comparison.best_store ? `<div class="small"><strong>Panier le moins cher</strong></div>` : ""}
            ${s.message ? `<div class="small muted">${escapeHtml(s.message)}</div>` : ""}
        </div>`).join("");

    const split = comparison.split_total != null
        ? `<p class="basket-split">En achetant chaque article là où il est le moins cher : <strong>${euros(comparison.split_total)}</strong>${comparison.split_missing ? ` (${comparison.split_missing} article(s) introuvable(s))` : ""}</p>`
        : "";

    const rows = store.list.map((item) => {
        const totals = stores.map((s) => lineFor(s, item)?.line_total).filter((v) => v != null);
        const min = totals.length ? Math.min(...totals) : null;
        const cells = stores.map((s) => {
            const line = lineFor(s, item);
            if (!line || line.line_total == null) return `<td class="cell muted">—</td>`;
            const link = safeUrl(line.product.product_url);
            return `<td class="cell${line.line_total === min ? " cheapest" : ""}">
                <span class="cell-price">${euros(line.line_total)}</span>${line.quantity > 1 ? ` <span class="muted">(${line.quantity} × ${euros(line.product.price)})</span>` : ""}
                <a class="cell-name"${link ? ` href="${escapeHtml(link)}" target="_blank" rel="noopener"` : ""}>${line.picked ? "★ " : ""}${escapeHtml(line.product.name)}</a>
            </td>`;
        }).join("");
        return `<tr><th>${escapeHtml(item.query)}${item.quantity > 1 ? ` ×${item.quantity}` : ""}</th>${cells}</tr>`;
    }).join("");

    return `
        <div class="basket-cards">${cards}</div>
        ${split}
        <div class="table-wrap">
            <table class="basket-table">
                <thead><tr><th>Article</th>${stores.map((s) => `<th>${retailerBadge(s.store, s.label)}</th>`).join("")}</tr></thead>
                <tbody>${rows}</tbody>
                <tfoot><tr><td>Total</td>${stores.map((s) => `<td>${s.missing === s.lines.length ? "—" : euros(s.total)}</td>`).join("")}</tr></tfoot>
            </table>
        </div>
        <p class="muted small">★ = produit choisi par vous. Sinon, le produit le moins cher contenant tous les mots de l'article est retenu.</p>`;
}

async function compareBasket() {
    local.comparing = true;
    $("#compare-btn").disabled = true;
    setBasket(`<p class="muted"><span class="spinner"></span> Recherche de chaque article dans ${store.enabled.size} enseignes… (plus rapide les fois suivantes grâce au cache)</p>`);
    try {
        const comparison = await api("/api/basket/compare", { method: "POST", body: { stores: [...store.enabled] } });
        setBasket(basketHtml(comparison));
    } catch (err) {
        setBasket(`<div class="notice warn">${escapeHtml(err.message)}</div>`);
    } finally {
        local.comparing = false;
        const btn = $("#compare-btn");
        if (btn) btn.disabled = false;
    }
}

function bind() {
    mountStoreFilters($("#store-filters"));

    $("#list-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const query = $("#list-input").value.trim();
        const quantity = Math.max(1, Math.min(99, Number($("#list-qty").value) || 1));
        if (!query) return;
        try {
            await addToList(query, null, quantity);
            if (root) {
                $("#list-input").value = "";
                $("#list-qty").value = 1;
            }
        } catch (err) {
            toast(err.message, true);
        }
    });

    $("#list-items").addEventListener("click", async (e) => {
        const btn = e.target.closest("button");
        if (!btn) return;
        try {
            if (btn.dataset.qty) {
                const item = store.list.find((i) => i.id === Number(btn.dataset.qty));
                const quantity = item.quantity + Number(btn.dataset.delta);
                if (quantity < 1) await api(`/api/list/${item.id}`, { method: "DELETE" });
                else await api(`/api/list/${item.id}`, { method: "PATCH", body: { quantity } });
            } else if (btn.dataset.delete) {
                await api(`/api/list/${btn.dataset.delete}`, { method: "DELETE" });
            } else if (btn.dataset.unpick) {
                await api(`/api/list/${btn.dataset.unpick}`, { method: "PATCH", body: { remove_pick: btn.dataset.store } });
            }
            await loadList();
        } catch (err) {
            toast(err.message, true);
        }
    });

    $("#clear-list-btn").addEventListener("click", async () => {
        if (!confirm("Vider toute la liste ?")) return;
        try {
            await api("/api/list", { method: "DELETE" });
            await loadList();
        } catch (err) {
            toast(err.message, true);
        }
    });

    $("#compare-btn").addEventListener("click", compareBasket);
}

export default {
    name: "list",
    path: "/liste",
    title: "Ma liste",
    nav: { label: "Ma liste", order: 20, badge: () => store.list.length },

    render(container) {
        root = container;
        root.innerHTML = TEMPLATE;
        bind();
        $("#basket").innerHTML = local.basketHtml;
        $("#compare-btn").disabled = local.comparing;
        renderList();
        unsubscribers = [subscribe("list", renderList)];
    },

    destroy() {
        unsubscribers.forEach((off) => off());
        unsubscribers = [];
        root = null;
    },
};
