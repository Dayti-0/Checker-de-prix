// #/liste : shopping list and basket comparison between the ticked retailers (area of P5).

import { retailerBadge, retailerDot } from "../../components/retailer-badge.js";
import { api } from "../../core/api.js";
import { euros, plural } from "../../core/fmt.js";
import { html, raw, safeUrl, setHtml } from "../../core/html.js";
import { addToList, loadList, on, retailer, state } from "../../core/store.js";
import { confirmDialog, notify } from "../../core/ui.js";

// Kept while the view is hidden
const local = { basket: raw(""), comparing: false };

let root = null;
let unsubscribers = [];

const TEMPLATE = html`
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

function setBasket(content) {
    local.basket = content;
    const el = $("#basket");
    if (el) setHtml(el, content);
}

function renderList() {
    if (!root) return;
    const items = state.list;
    $("#list-actions").hidden = items.length === 0;
    if (!items.length) {
        setHtml($("#list-items"), html`<li class="muted">Votre liste est vide.</li>`);
        setBasket(raw(""));
        return;
    }
    setHtml(
        $("#list-items"),
        html`${items.map((item) => {
            const picks = Object.entries(item.picks || {}).map(
                ([key, p]) => html`
            <span class="pick" title="${p.name}">
                ${retailerDot(key)}
                <span class="txt">${retailer(key).label} : ${p.name}${p.price != null && ` (${euros(p.price)})`}</span>
                <button type="button" data-unpick="${item.id}" data-store="${key}" aria-label="Retirer ce choix">✕</button>
            </span>`,
            );
            return html`
            <li class="list-item">
                <div class="list-main">
                    <strong>${item.query}</strong>
                    ${picks.length ? html`<div class="picks">${picks}</div>` : html`<div class="muted small">Le moins cher des produits correspondants sera retenu.</div>`}
                </div>
                <div class="qty">
                    <button type="button" data-qty="${item.id}" data-delta="-1" aria-label="Moins">−</button>
                    <span>${item.quantity}</span>
                    <button type="button" data-qty="${item.id}" data-delta="1" aria-label="Plus">+</button>
                </div>
                <button class="icon-btn" type="button" data-delete="${item.id}" aria-label="Supprimer">🗑</button>
            </li>`;
        })}`,
    );
}

function basketView(comparison) {
    const stores = [...comparison.stores].sort((a, b) => a.missing - b.missing || a.total - b.total);
    const lineFor = (s, item) => s.lines.find((l) => l.item_id === item.id);
    const cards = stores.map(
        (s) => html`
        <div class="basket-card${s.store === comparison.best_store ? " best" : ""}">
            ${retailerBadge(s.store, s.label)}
            <div class="total">${s.missing === s.lines.length ? "—" : euros(s.total)}</div>
            <div class="small ${s.missing ? "muted" : ""}">${s.missing ? plural(s.missing, "article non trouvé", "articles non trouvés") : "Panier complet"}</div>
            ${s.store === comparison.best_store && html`<div class="small"><strong>Panier le moins cher</strong></div>`}
            ${s.message && html`<div class="small muted">${s.message}</div>`}
        </div>`,
    );

    const split =
        comparison.split_total != null
            ? html`<p class="basket-split">En achetant chaque article là où il est le moins cher : <strong>${euros(comparison.split_total)}</strong>${comparison.split_missing > 0 && ` (${plural(comparison.split_missing, "article introuvable", "articles introuvables")})`}</p>`
            : "";

    const rows = state.list.map((item) => {
        const totals = stores.map((s) => lineFor(s, item)?.line_total).filter((v) => v != null);
        const min = totals.length ? Math.min(...totals) : null;
        const cells = stores.map((s) => {
            const line = lineFor(s, item);
            if (!line || line.line_total == null) return html`<td class="cell muted">—</td>`;
            const link = safeUrl(line.product.product_url);
            const name = html`${line.picked && "★ "}${line.product.name}`;
            return html`<td class="cell${line.line_total === min ? " cheapest" : ""}">
                <span class="cell-price">${euros(line.line_total)}</span>${line.quantity > 1 && html` <span class="muted">(${line.quantity} × ${euros(line.product.price)})</span>`}
                ${link ? html`<a class="cell-name" href="${link}" target="_blank" rel="noopener">${name}</a>` : html`<a class="cell-name">${name}</a>`}
            </td>`;
        });
        return html`<tr><th>${item.query}${item.quantity > 1 && ` ×${item.quantity}`}</th>${cells}</tr>`;
    });

    return html`
        <div class="basket-cards">${cards}</div>
        ${split}
        <div class="table-wrap">
            <table class="basket-table">
                <thead><tr><th>Article</th>${stores.map((s) => html`<th>${retailerBadge(s.store, s.label)}</th>`)}</tr></thead>
                <tbody>${rows}</tbody>
                <tfoot><tr><td>Total</td>${stores.map((s) => html`<td>${s.missing === s.lines.length ? "—" : euros(s.total)}</td>`)}</tr></tfoot>
            </table>
        </div>
        <p class="muted small">★ = produit choisi par vous. Sinon, le produit le moins cher contenant tous les mots de l'article est retenu.</p>`;
}

async function compareBasket() {
    local.comparing = true;
    $("#compare-btn").disabled = true;
    setBasket(
        html`<p class="muted"><span class="spinner"></span> Recherche de chaque article dans ${state.enabled.size} enseignes… (plus rapide les fois suivantes grâce au cache)</p>`,
    );
    try {
        const comparison = await api("/api/basket/compare", { method: "POST", body: { stores: [...state.enabled] } });
        setBasket(basketView(comparison));
    } catch (err) {
        setBasket(html`<div class="notice warn">${err.message}</div>`);
    } finally {
        local.comparing = false;
        const btn = $("#compare-btn");
        if (btn) btn.disabled = false;
    }
}

function bind() {
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
            notify(err.message, { type: "error" });
        }
    });

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
        } catch (err) {
            notify(err.message, { type: "error" });
        }
    });

    $("#clear-list-btn").addEventListener("click", async () => {
        if (!(await confirmDialog({ message: "Vider toute la liste ?", confirmLabel: "Vider", danger: true }))) return;
        try {
            await api("/api/list", { method: "DELETE" });
            await loadList();
        } catch (err) {
            notify(err.message, { type: "error" });
        }
    });

    $("#compare-btn").addEventListener("click", compareBasket);
}

export const enabled = true;
export const title = "Ma liste";
export const nav = { id: "list", label: "Ma liste", icon: "list", order: 20, badge: () => state.list.length };
export const shell = { search: false, filters: true };

export function render(container) {
    root = container;
    setHtml(root, TEMPLATE);
    bind();
    setHtml($("#basket"), local.basket);
    $("#compare-btn").disabled = local.comparing;
    renderList();
    unsubscribers = [on("list:changed", renderList)];
}

export function destroy() {
    unsubscribers.forEach((off) => off());
    unsubscribers = [];
    root = null;
}
