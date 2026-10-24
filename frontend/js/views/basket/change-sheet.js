// Sheet « Changer » of a cell of the basket (B60, B71): the suitable products
// of the retailer for the item (GET /api/basket/candidates, from the prices
// already read), cheapest per kg/L first. Choosing one saves it as the choice
// of the item at that retailer (PATCH /api/list/{id} {set_pick}); « Pas
// disponible ici » ({exclude_store}), « Revenir au choix automatique »
// ({remove_pick}) and « Saisir le prix vu en magasin » ({manual_price}). The
// basket is then compared again from the prices already read (runner.recompare).

import { api } from "../../core/api.js";
import { euros } from "../../core/fmt.js";
import { attr, html } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { loadList } from "../../core/store.js";
import { notify } from "../../core/ui.js";
import { openSheet } from "../list/sheet.js";
import { brandText, productLabel, unitLabel } from "../search/product-row.js";
import { patch } from "../search/patch.js";
import { recompare } from "./runner.js";

function today() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function candidateRow(p, i, data) {
    const current = data.current_url && p.product_url === data.current_url;
    const auto = data.auto_url && p.product_url === data.auto_url;
    const meta = [brandText(p.brand), p.quantity_label].filter(Boolean).join(" · ");
    const unit = unitLabel(p);
    return html`<li class="cand${current ? " current" : ""}${p.available === false ? " unavailable" : ""}" data-key="c-${i}">
        <button type="button" class="cand-btn" data-pick="${i}" aria-label="Choisir ${productLabel(p)}"${attr({ "aria-current": current ? "true" : null })}>
            <span class="cand-main">
                <span class="cand-name">${p.name}</span>
                ${meta ? html`<span class="cand-meta">${meta}</span>` : ""}
                <span class="cand-tags">${current ? html`<span class="tag ok">${icon("check")}Retenu</span>` : ""}${auto && !current ? html`<span class="tag">Choix automatique</span>` : ""}${p.available === false ? html`<span class="tag warn">Indisponible</span>` : ""}</span>
            </span>
            <span class="cand-price"><strong>${p.price != null ? euros(p.price) : "—"}</strong>${unit ? html`<span class="cand-unit">${unit}</span>` : ""}</span>
        </button>
    </li>`;
}

function manualForm(item, label, line) {
    const name = (line && line.product && line.product.name) || item.query;
    return html`<form class="manual-form" data-manual-form data-key="manual">
        <h3 class="edit-sub">Prix vu en magasin chez ${label}</h3>
        <div class="field">
            <label for="manual-name">Produit</label>
            <input id="manual-name" name="name" value="${name}" maxlength="120" required>
        </div>
        <div class="field-row">
            <div class="field">
                <label for="manual-price">Prix (€)</label>
                <input id="manual-price" name="price" type="text" inputmode="decimal" placeholder="ex : 1,49" required autocomplete="off">
            </div>
            <div class="field">
                <label for="manual-qty">Contenance</label>
                <input id="manual-qty" name="quantity_label" maxlength="40" placeholder="ex : 1 kg">
            </div>
        </div>
        <div class="field">
            <label for="manual-date">Vu le</label>
            <input id="manual-date" name="seen" type="date" value="${today()}" max="${today()}">
        </div>
        <p class="field-help">Ce prix est compté dans le panier pendant quelques semaines (réglages du panier), avec la mention « saisi le … ».</p>
        <p class="form-error" role="alert" data-error hidden></p>
        <div class="sheet-buttons">
            <button type="button" class="btn-ghost" data-manual-cancel>Retour</button>
            <button type="submit" class="btn-primary">Enregistrer le prix</button>
        </div>
    </form>`;
}

function body({ item, label, line, data, manual, error }) {
    if (manual) return manualForm(item, label, line);
    let products;
    if (error) products = html`<p class="notice warn" data-key="err">${error}</p>`;
    else if (!data) products = html`<p class="muted" data-key="wait"><span class="spinner" aria-hidden="true"></span> Recherche des produits de ${label}…</p>`;
    else if (!data.products.length) {
        products = html`<p class="muted" data-key="none">${data.message || `Aucun produit de ${label} ne correspond à « ${item.query} ».`}</p>`;
    } else {
        products = html`<ul class="cand-list" data-key="list" data-patch aria-label="Produits de ${label}">${data.products.map((p, i) => candidateRow(p, i, data))}</ul>
            ${data.message ? html`<p class="muted small" data-key="msg">${data.message}</p>` : ""}`;
    }
    const excluded = line && line.status === "excluded";
    const chosen = line && (line.basis === "pick" || line.basis === "manual" || line.pick);
    return html`<p class="change-intro" data-key="intro">Produits de ${label} pour « ${item.query} », du moins cher au kilo ou au litre au plus cher.</p>
        <div class="cand-box" data-key="products" data-patch>${products}</div>
        <div class="change-actions" data-key="actions">
            ${chosen && !excluded ? html`<button type="button" class="btn-ghost" data-auto>Revenir au choix automatique</button>` : ""}
            ${excluded ? html`<button type="button" class="btn-ghost" data-auto>Comparer de nouveau chez ${label}</button>` : html`<button type="button" class="btn-ghost" data-exclude>Pas disponible chez ${label}</button>`}
            <button type="button" class="btn-ghost" data-manual-open>Saisir le prix vu en magasin</button>
        </div>`;
}

export function openChangeSheet({ item, store, label, line, manual = false }) {
    const ctx = { item, label, line, data: null, manual, error: null };
    const sheet = openSheet({ id: "change-sheet", title: `« ${item.query} » chez ${label}`, body: html`` });
    const draw = () => sheet.open && patch(sheet.content, body(ctx));
    draw();

    async function save(update, message) {
        try {
            await api(`/api/list/${item.id}`, { method: "PATCH", body: update });
            const again = recompare();
            await loadList();
            sheet.close();
            notify(message);
            await again;
        } catch (err) {
            notify(err.message, { type: "error" });
        }
    }

    sheet.content.addEventListener("click", async (e) => {
        const b = e.target.closest("button");
        if (!b) return;
        const d = b.dataset;
        if (d.pick !== undefined && ctx.data) {
            const product = ctx.data.products[Number(d.pick)];
            if (product) await save({ set_pick: product }, `${product.name} retenu chez ${label}`);
        } else if ("auto" in d) {
            await save({ remove_pick: store }, `${label} : retour au choix automatique`);
        } else if ("exclude" in d) {
            await save({ exclude_store: store }, `« ${item.query} » : pas disponible chez ${label}`);
        } else if ("manualOpen" in d) {
            ctx.manual = true;
            draw();
            sheet.content.querySelector("#manual-price")?.focus();
        } else if ("manualCancel" in d) {
            ctx.manual = false;
            draw();
            sheet.content.querySelector("[data-manual-open]")?.focus();
        }
    });

    sheet.content.addEventListener("submit", async (e) => {
        e.preventDefault();
        const f = e.target;
        const error = f.querySelector("[data-error]");
        const price = Number(String(f.price.value).replace(",", ".").replace(/\s|€/g, ""));
        if (!(price > 0 && price <= 10000)) {
            error.textContent = "Indiquez un prix, par exemple 1,49.";
            error.hidden = false;
            f.price.focus();
            return;
        }
        const seen = f.seen.value ? new Date(`${f.seen.value}T12:00:00`).getTime() / 1000 : null;
        await save(
            {
                manual_price: {
                    store,
                    name: f.name.value.trim() || item.query,
                    price,
                    quantity_label: f.quantity_label.value.trim() || null,
                    seen_at: seen && seen <= Date.now() / 1000 ? seen : null,
                },
            },
            `Prix saisi : ${euros(price)} chez ${label}`,
        );
    });

    if (manual) sheet.content.querySelector("#manual-price")?.focus();
    api(`/api/basket/candidates/${item.id}/${store}`)
        .then((data) => {
            ctx.data = data;
        })
        .catch((err) => {
            ctx.error = err.message;
        })
        .finally(draw);
    return sheet;
}
