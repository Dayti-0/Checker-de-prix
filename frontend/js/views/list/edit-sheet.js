// Sheet « Modifier » of a list item (B65): name, quantity, target, aisle,
// note, « Comparer les prix » (compare), products chosen and « pas disponible ici ».
// Only the fields changed are sent (PATCH /api/list/{id}).

import { api } from "../../core/api.js";
import { attr, html, setHtml } from "../../core/html.js";
import { loadList, retailer } from "../../core/store.js";
import { announce, notify } from "../../core/ui.js";
import { loadCategories } from "./data.js";
import { pickParts } from "./model.js";
import { openSheet } from "./sheet.js";

function picksBlock(item) {
    const picks = Object.entries(item.picks || {});
    const excluded = item.excluded || [];
    if (!picks.length && !excluded.length) return html``;
    return html`<div class="edit-picks">
        <h3 class="edit-sub">Produits choisis</h3>
        <ul class="edit-pick-list">
            ${picks.map(([store, pick]) => {
                const p = pickParts(pick);
                return html`<li>
                    <span class="dot ${store}-bg" aria-hidden="true"></span>
                    <span class="edit-pick-text"><strong>${retailer(store).label}</strong> · ${p.name}${p.price ? ` · ${p.price}` : ""}${p.note ? html` <span class="muted">(${p.note})</span>` : ""}</span>
                    <button type="button" class="btn-ghost small" data-unpick="${store}" aria-label="Retirer le choix ${retailer(store).label}">Retirer</button>
                </li>`;
            })}
            ${excluded.map(
                (store) => html`<li>
                    <span class="dot ${store}-bg" aria-hidden="true"></span>
                    <span class="edit-pick-text">Pas disponible chez <strong>${retailer(store).label}</strong></span>
                    <button type="button" class="btn-ghost small" data-unpick="${store}" aria-label="Comparer de nouveau chez ${retailer(store).label}">Comparer de nouveau</button>
                </li>`,
            )}
        </ul>
    </div>`;
}

function form(item, categories) {
    const id = item.id;
    return html`<form class="edit-form" data-edit-form novalidate>
        <div class="field">
            <label for="edit-query-${id}">Article</label>
            <input id="edit-query-${id}" name="query" value="${item.query}" maxlength="120" required>
        </div>
        <div class="field-row">
            <div class="field">
                <label for="edit-qty-${id}">Quantité</label>
                <input id="edit-qty-${id}" name="quantity" type="number" min="1" max="99" inputmode="numeric" value="${item.quantity}">
            </div>
            <div class="field">
                <label for="edit-target-${id}">Quantité visée</label>
                <input id="edit-target-${id}" name="target" value="${item.target || ""}" maxlength="40" placeholder="ex : 1 kg, 6 L, 12" aria-describedby="edit-target-help-${id}">
            </div>
        </div>
        <p class="field-help" id="edit-target-help-${id}">Avec une quantité visée, le panier achète assez de paquets pour l'atteindre (la quantité est alors ignorée).</p>
        <div class="field">
            <label for="edit-cat-${id}">Rayon</label>
            <select id="edit-cat-${id}" name="category">
                <option value=""${attr({ selected: !item.category_set })}>Automatique${item.category_set ? "" : ` (${item.category})`}</option>
                ${categories.map((c) => html`<option value="${c}"${attr({ selected: item.category_set && c === item.category })}>${c}</option>`)}
            </select>
        </div>
        <div class="field">
            <label for="edit-note-${id}">Note</label>
            <input id="edit-note-${id}" name="note" value="${item.note || ""}" maxlength="200" placeholder="ex : bio si possible">
        </div>
        <label class="check-field">
            <input type="checkbox" name="compare"${attr({ checked: item.compare })}>
            <span><strong>Comparer les prix de cet article</strong><br><span class="muted">Décochez pour le garder dans la liste sans le compter dans le panier.</span></span>
        </label>
        ${picksBlock(item)}
        <p class="form-error" role="alert" data-error hidden></p>
        <div class="sheet-buttons">
            <button type="button" class="btn-ghost" data-close>Annuler</button>
            <button type="submit" class="btn-primary">Enregistrer</button>
        </div>
    </form>`;
}

// The fields of the form that differ from the item
export function changes(item, values) {
    const out = {};
    const query = values.query.trim();
    if (query && query !== item.query) out.query = query;
    const quantity = Math.max(1, Math.min(99, Math.round(Number(values.quantity) || item.quantity)));
    if (quantity !== item.quantity) out.quantity = quantity;
    const target = values.target.trim();
    if (target !== (item.target || "")) out.target = target;
    const note = values.note.trim();
    if (note !== (item.note || "")) out.note = note;
    const category = values.category;
    if (category !== (item.category_set ? item.category : "")) out.category = category;
    if (values.compare !== item.compare) out.compare = values.compare;
    return out;
}

export async function openEditSheet(item) {
    if (!item) return;
    const categories = await loadCategories();
    const sheet = openSheet({ id: "edit-sheet", title: `Modifier « ${item.query} »`, body: form(item, categories) });
    let current = item;

    sheet.content.addEventListener("click", async (e) => {
        const button = e.target.closest("[data-unpick]");
        if (!button) return;
        const store = button.dataset.unpick;
        try {
            current = await api(`/api/list/${current.id}`, { method: "PATCH", body: { remove_pick: store } });
            await loadList();
            const block = sheet.content.querySelector(".edit-picks");
            const fresh = document.createElement("div");
            setHtml(fresh, picksBlock(current));
            if (block) block.replaceWith(...fresh.childNodes);
            announce(`${retailer(store).label} : retour au choix automatique`);
            sheet.content.querySelector("[name=query]").focus();
        } catch (err) {
            notify(err.message, { type: "error" });
        }
    });

    sheet.content.addEventListener("submit", async (e) => {
        e.preventDefault();
        const f = e.target;
        const error = f.querySelector("[data-error]");
        error.hidden = true;
        if (!f.query.value.trim()) {
            error.textContent = "Donnez un nom à l'article.";
            error.hidden = false;
            f.query.focus();
            return;
        }
        const body = changes(current, {
            query: f.query.value,
            quantity: f.quantity.value,
            target: f.target.value,
            note: f.note.value,
            category: f.category.value,
            compare: f.compare.checked,
        });
        if (!Object.keys(body).length) {
            sheet.close();
            return;
        }
        const submit = f.querySelector("[type=submit]");
        submit.disabled = true;
        try {
            const saved = await api(`/api/list/${current.id}`, { method: "PATCH", body });
            await loadList();
            sheet.close();
            notify(`« ${saved.query} » modifié`);
        } catch (err) {
            error.textContent = err.message;
            error.hidden = false;
        } finally {
            submit.disabled = false;
        }
    });
    sheet.content.querySelector("[name=query]").focus();
    return sheet;
}

