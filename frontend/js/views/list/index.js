// #/liste : « Ma liste » (area of P5).
//
// - add form, the « habituels » (one tap), the help shown once;
// - the items by aisle (headers that fold), each with its quantity, target,
//   note and the products chosen « ● Lidl · Farine de blé T45 · 0,75 € »;
// - « Supprimer » then « Annuler » (6 s) puts the line back as it was
//   (POST /api/list/restore), « Vider la liste » asks first;
// - « Comparer mon panier » (#/panier), « En magasin » (#/courses), « Coller une
//   liste », « Listes enregistrées », « Partager ou imprimer » (sheets of this folder);
// - the list follows the changes made on another device (sync.js).
// The page is updated in place (patch.js of the search page): focus and typed text stay.

import { api } from "../../core/api.js";
import { plural } from "../../core/fmt.js";
import { attr, html, setHtml } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { navigate } from "../../core/router.js";
import { loadList, on, retailer, state } from "../../core/store.js";
import { announce, confirmDialog, notify } from "../../core/ui.js";
import { compareNow } from "../basket/runner.js";
import { listKey } from "../search/add-sheet.js";
import { patch } from "../search/patch.js";
import { knownCategories, loadCategories, readJson, restoreItems, writeJson } from "./data.js";
import { openEditSheet } from "./edit-sheet.js";
import { groupByAisle, pickParts, quantityText } from "./model.js";
import { openPasteSheet } from "./paste-sheet.js";
import { openShareSheet } from "./share-sheet.js";
import { watchList } from "./sync.js";
import { openTemplatesSheet } from "./templates-sheet.js";

export const enabled = true;
export const title = "Ma liste";
export const nav = {
    id: "list",
    label: "Ma liste",
    icon: "list",
    order: 20,
    badge: () => state.list.length,
    also: ["/panier", "/courses"],
};
export const shell = { search: false, filters: true };

const HELP_KEY = "prixmalin.listHelpSeen";
const FOLDED_KEY = "prixmalin.listFolded";
export const QUICK_ADD = ["Lait", "Pain", "Œufs"];

let root = null;
let cleanups = [];
let usual = [];
// Quantities asked and not saved yet (fast taps on « + »)
const pendingQty = new Map();

// ---------------------------------------------------------------- markup

function pickLine(store, pick) {
    const parts = pickParts(pick);
    return html`<li class="row-pick" data-key="pick-${store}">
        <span class="dot ${store}-bg" aria-hidden="true"></span>
        <span class="pick-text"><span class="pick-store">${retailer(store).label}</span> · <span class="pick-name">${parts.name}</span>${parts.note ? html` <span class="pick-note">(${parts.note})</span>` : ""}</span>
        ${parts.price ? html`<span class="pick-price">${parts.price}</span>` : ""}
    </li>`;
}

function itemRow(item) {
    const q = item.query;
    const qty = pendingQty.has(item.id) ? pendingQty.get(item.id) : item.quantity;
    const qtyLabel = quantityText({ ...item, quantity: qty });
    const picks = Object.entries(item.picks || {});
    const tags = [];
    if (item.target) tags.push(html`<span class="tag">${icon("tag")}Objectif ${item.target}</span>`);
    if (!item.compare) tags.push(html`<span class="tag muted">Hors comparaison</span>`);
    for (const key of item.excluded || []) {
        tags.push(html`<span class="tag warn">Pas chez ${retailer(key).label}</span>`);
    }
    if (item.checked) tags.push(html`<span class="tag done">${icon("check")}Pris</span>`);
    const stepper = item.target
        ? ""
        : html`<div class="stepper row-stepper" role="group" aria-label="Quantité de ${q}">
            <button type="button" data-qty="${item.id}" data-delta="-1" data-focus="less-${item.id}" aria-label="Diminuer la quantité de ${q}"${attr({ disabled: qty <= 1 })}>${icon("minus")}</button>
            <span class="qty-value">${qty}</span>
            <button type="button" data-qty="${item.id}" data-delta="1" data-focus="more-${item.id}" aria-label="Augmenter la quantité de ${q}"${attr({ disabled: qty >= 99 })}>${icon("plus")}</button>
        </div>`;
    return html`<li class="list-row${item.checked ? " is-checked" : ""}" data-key="item-${item.id}" data-item="${item.id}">
        <div class="row-head">
            <button type="button" class="row-title" data-edit="${item.id}" data-focus="edit-${item.id}" aria-label="Modifier ${q}">
                <span class="row-query">${q}</span>${icon("chevron-right")}
            </button>
            ${qtyLabel ? html`<span class="row-qty" aria-hidden="true">${qtyLabel}</span>` : ""}
        </div>
        <div class="row-actions">
            ${stepper}
            <button type="button" class="row-delete" data-delete="${item.id}" data-focus="del-${item.id}" aria-label="Supprimer ${q}" title="Supprimer">${icon("trash-2")}</button>
        </div>
        ${tags.length ? html`<div class="row-tags">${tags}</div>` : ""}
        ${picks.length ? html`<ul class="row-picks" aria-label="Produits choisis pour ${q}">${picks.map(([store, pick]) => pickLine(store, pick))}</ul>` : ""}
        ${item.note ? html`<p class="row-note">${item.note}</p>` : ""}
    </li>`;
}

function aisles(items) {
    const folded = new Set(readJson(FOLDED_KEY, []));
    return groupByAisle(items, knownCategories()).map((group, i) => {
        const open = !folded.has(group.name);
        const id = `aisle-${i}`;
        const n = group.items.length;
        return html`<section class="aisle" data-key="aisle-${group.name}" data-patch>
            <h2 class="aisle-head" data-key="head">
                <button type="button" class="aisle-toggle" data-aisle="${group.name}" data-focus="aisle-${group.name}" aria-expanded="${open}" aria-controls="${id}">
                    ${icon("chevron-down")}<span class="aisle-name">${group.name}</span>
                    <span class="aisle-count">${n}<span class="visually-hidden"> ${n >= 2 ? "articles" : "article"}</span></span>
                </button>
            </h2>
            <ul class="list-rows" id="${id}" data-key="rows" data-patch${attr({ hidden: !open })}>${group.items.map(itemRow)}</ul>
        </section>`;
    });
}

function usualChips() {
    const present = new Set(state.list.map((i) => i.key));
    const chips = usual.filter((u) => !present.has(listKey(u.query)));
    if (!chips.length) return html``;
    return html`<section class="usual" aria-labelledby="usual-title" data-testid="usual">
        <h2 id="usual-title" class="usual-title">${icon("history")}Vos habituels</h2>
        <ul class="usual-chips">${chips.slice(0, 12).map(
            (u) => html`<li class="usual-chip" data-key="usual-${u.query}">
                <button type="button" class="usual-add" data-usual="${u.query}" data-focus="usual-${u.query}" aria-label="Ajouter ${u.query} à ma liste">${icon("plus")}${u.query}</button>
                <button type="button" class="usual-forget" data-forget="${u.query}" aria-label="Ne plus proposer ${u.query}" title="Ne plus proposer">${icon("x")}</button>
            </li>`,
        )}</ul>
    </section>`;
}

function emptyState() {
    const quick = usual.length ? [] : QUICK_ADD;
    return html`<div class="list-empty" data-testid="list-empty">
        <div class="list-empty-art" aria-hidden="true">${icon("shopping-cart")}</div>
        <h2 class="list-empty-title">Votre liste est vide</h2>
        <p>Ajoutez ce que vous achetez : PrixMalin cherche chaque article dans les enseignes cochées et vous dit où votre panier coûte le moins cher.</p>
        ${
            quick.length
                ? html`<div class="quick-add">${quick.map(
                      (q) => html`<button type="button" class="usual-add" data-quick="${q}" aria-label="Ajouter ${q} à ma liste">${icon("plus")}${q}</button>`,
                  )}</div>`
                : ""
        }
    </div>`;
}

function helpBox() {
    if (readJson(HELP_KEY, false)) return html``;
    return html`<aside class="list-help" aria-labelledby="list-help-title" data-testid="list-help">
        <h2 id="list-help-title" class="list-help-title">${icon("info")}Comment ça marche</h2>
        <p>Pour chaque article, le produit le moins cher de chaque enseigne est retenu. Pour un produit précis, utilisez le bouton <strong>+</strong> d'un produit dans les résultats de recherche. Touchez le nom d'un article pour le modifier : rayon, note, quantité visée.</p>
        <button type="button" class="btn-ghost small" data-help-ok>J'ai compris</button>
    </aside>`;
}

function body() {
    const items = state.list;
    const n = items.length;
    return html`
        <div class="list-top" data-key="top">
            <div class="list-heading">
                <h1 class="list-title">Ma liste</h1>
                <span class="list-count" data-testid="list-count">${n ? plural(n, "article") : ""}</span>
            </div>
            ${
                n
                    ? html`<div class="list-cta">
                <button type="button" class="btn-primary big" data-compare>${icon("shopping-cart")}Comparer mon panier</button>
                <a class="btn-ghost big" href="#/courses">${icon("list-checks")}En magasin</a>
            </div>`
                    : ""
            }
        </div>
        <div class="list-help-box" data-key="help">${helpBox()}</div>
        <form id="list-form" class="list-form" data-key="form" autocomplete="off">
            <label class="visually-hidden" for="list-input">Article à ajouter</label>
            <input id="list-input" name="query" placeholder="Ajouter un article (ex : lait demi-écrémé)" maxlength="120" enterkeyhint="done" required>
            <label class="visually-hidden" for="list-qty">Quantité</label>
            <input id="list-qty" name="quantity" type="number" min="1" max="99" value="1" inputmode="numeric">
            <button class="btn-primary" type="submit">${icon("plus")}Ajouter</button>
        </form>
        <div class="list-usual-box" data-key="usual">${usualChips()}</div>
        <div class="list-groups" data-key="groups" data-patch data-testid="list-items">${n ? aisles(items) : emptyState()}</div>
        <div class="list-tools" data-key="tools">
            <button type="button" class="btn-ghost" data-paste>${icon("upload")}Coller une liste</button>
            <button type="button" class="btn-ghost" data-templates>${icon("star")}Listes enregistrées</button>
            ${n ? html`<button type="button" class="btn-ghost" data-share>${icon("share-2")}Partager ou imprimer</button>` : ""}
            ${n ? html`<button type="button" class="btn-ghost danger" data-clear>${icon("trash-2")}Vider la liste</button>` : ""}
        </div>`;
}

function draw() {
    const page = root && root.querySelector(".list-page");
    if (page) patch(page, body());
}

// ---------------------------------------------------------------- actions

async function addQuery(query, quantity = 1) {
    const item = await api("/api/list", { method: "POST", body: { query, quantity } });
    await loadList();
    return item;
}

async function onSubmit(e) {
    e.preventDefault();
    const form = e.target.closest("#list-form");
    if (!form) return;
    const query = form.query.value.trim();
    const quantity = Math.max(1, Math.min(99, Math.round(Number(form.quantity.value) || 1)));
    if (!query) return;
    const before = state.list.find((i) => i.key === listKey(query));
    try {
        const item = await addQuery(query, quantity);
        form.query.value = "";
        form.quantity.value = 1;
        form.query.focus();
        notify(before ? `« ${item.query} » : quantité ${item.quantity}` : `« ${item.query} » ajouté à votre liste`);
    } catch (err) {
        notify(err.message, { type: "error" });
    }
}

async function changeQuantity(id, delta) {
    const item = state.list.find((i) => i.id === id);
    if (!item) return;
    const current = pendingQty.has(id) ? pendingQty.get(id) : item.quantity;
    const quantity = Math.max(1, Math.min(99, current + delta));
    if (quantity === current) return;
    pendingQty.set(id, quantity);
    draw();
    announce(`Quantité de ${item.query} : ${quantity}`);
    try {
        await api(`/api/list/${id}`, { method: "PATCH", body: { quantity } });
        if (pendingQty.get(id) === quantity) {
            await loadList();
            if (pendingQty.get(id) === quantity) pendingQty.delete(id);
            draw();
        }
    } catch (err) {
        pendingQty.delete(id);
        draw();
        notify(err.message, { type: "error" });
    }
}

// The button to focus once the row `id` is gone: the next row, else the previous, else the form
function focusAfter(id) {
    const rows = [...root.querySelectorAll(".list-row")];
    const i = rows.findIndex((r) => r.dataset.item === String(id));
    const next = rows[i + 1] || rows[i - 1];
    return next ? `[data-focus="del-${next.dataset.item}"]` : "#list-input";
}

async function deleteItem(id) {
    const item = state.list.find((i) => i.id === id);
    if (!item) return;
    const target = focusAfter(id);
    await api(`/api/list/${id}`, { method: "DELETE" });
    await loadList();
    root?.querySelector(target)?.focus();
    notify(`« ${item.query} » supprimé`, {
        action: { label: "Annuler", onClick: () => restoreItems([id], `« ${item.query} » remis dans votre liste`) },
        duration: 6000,
    });
}

async function clearList() {
    const ids = state.list.map((i) => i.id);
    if (!ids.length) return;
    const ok = await confirmDialog({
        title: "Vider la liste",
        message: `Vider toute la liste (${plural(ids.length, "article")}) ?`,
        confirmLabel: "Vider",
        danger: true,
    });
    if (!ok) return;
    await api("/api/list", { method: "DELETE" });
    await loadList();
    root?.querySelector("#list-input")?.focus();
    notify("Liste vidée", {
        action: { label: "Annuler", onClick: () => restoreItems(ids, "Liste rétablie") },
        duration: 6000,
    });
}

async function loadUsual() {
    try {
        usual = await api("/api/list/usual");
    } catch {
        usual = [];
    }
    draw();
}

function toggleAisle(button) {
    const folded = new Set(readJson(FOLDED_KEY, []));
    const open = button.getAttribute("aria-expanded") !== "true";
    if (open) folded.delete(button.dataset.aisle);
    else folded.add(button.dataset.aisle);
    writeJson(FOLDED_KEY, [...folded]);
    draw();
}

async function onClick(e) {
    const t = e.target.closest("button");
    if (!t || !root || !root.contains(t)) return;
    const d = t.dataset;
    try {
        if (d.qty) await changeQuantity(Number(d.qty), Number(d.delta));
        else if (d.delete) await deleteItem(Number(d.delete));
        else if (d.edit) openEditSheet(state.list.find((i) => i.id === Number(d.edit)));
        else if (d.aisle !== undefined) toggleAisle(t);
        else if (d.usual || d.quick) {
            const item = await addQuery(d.usual || d.quick);
            notify(`« ${item.query} » ajouté à votre liste`);
            root?.querySelector("#list-input")?.focus();
            if (d.usual) await loadUsual();
        } else if (d.forget) {
            await api(`/api/list/usual?query=${encodeURIComponent(d.forget)}`, { method: "DELETE" });
            announce(`${d.forget} ne sera plus proposé`);
            root?.querySelector("#list-input")?.focus();
            await loadUsual();
        } else if ("helpOk" in d) {
            writeJson(HELP_KEY, true);
            root.querySelector("#list-input")?.focus();
            draw();
        } else if ("compare" in d) {
            compareNow();
            navigate("/panier");
        } else if ("clear" in d) await clearList();
        else if ("paste" in d) openPasteSheet();
        else if ("templates" in d) openTemplatesSheet();
        else if ("share" in d) openShareSheet();
    } catch (err) {
        notify(err.message, { type: "error" });
    }
}

// ---------------------------------------------------------------- view

export function render(container) {
    root = container;
    setHtml(root, html`<div class="list-page" data-testid="list-page"></div>`);
    draw();
    root.addEventListener("click", onClick);
    root.addEventListener("submit", onSubmit);
    cleanups = [on("list:changed", draw), on("usual:changed", loadUsual), watchList()];
    loadCategories().then(draw);
    loadUsual();
}

export function destroy() {
    cleanups.forEach((off) => off());
    cleanups = [];
    pendingQty.clear();
    root = null;
}
