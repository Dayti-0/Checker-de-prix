// Adding a product of the results to « Ma liste » (B32).
//
// The « + » of a product opens a small sheet (a modal <dialog>, at the bottom
// of the screen on a phone):
//   ○ « farine », le moins cher sera choisi      (the search only)
//   ● exactement ce produit chez Aldi            (the product chosen for Aldi)
// with the quantity. Then a message « Ajouté à « farine » · Voir la liste ·
// Annuler »; « Annuler » puts the list back as it was. A product already chosen
// in the list has a « ✓ » button: « Retirer … de ma liste ».
// Only the API of the list is used: POST /api/list, PATCH and DELETE /api/list/{id}.

import { api } from "../../core/api.js";
import { euros } from "../../core/fmt.js";
import { html, setHtml } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { navigate } from "../../core/router.js";
import { loadList, retailer, state } from "../../core/store.js";
import { notify } from "../../core/ui.js";
import { retailerBadge } from "../../components/retailer-badge.js";
import { brandText } from "./product-row.js";

const same = (a, b) => String(a).trim().toLocaleLowerCase("fr") === String(b).trim().toLocaleLowerCase("fr");

function sameProduct(a, b) {
    if (!a || !b || a.store !== b.store) return false;
    if (a.product_url || b.product_url) return a.product_url === b.product_url;
    return a.name === b.name && a.price === b.price;
}

// Line of the list for a search (same text, case and spaces ignored)
export function lineFor(query, list = state.list) {
    return (list || []).find((item) => same(item.query, query)) || null;
}

// Line of the list where `product` is the choice of its retailer
export function lineWithProduct(product, list = state.list) {
    return (list || []).find((item) => sameProduct(item.picks && item.picks[product.store], product)) || null;
}

export function isListed(product, list = state.list) {
    return Boolean(lineWithProduct(product, list));
}

// The badge of « Ma liste » in the navigation moves briefly
function bump() {
    for (const el of document.querySelectorAll('[data-nav="list"]')) {
        el.classList.remove("nav-bump");
        void el.offsetWidth; // restart the animation
        el.classList.add("nav-bump");
        setTimeout(() => el.classList.remove("nav-bump"), 900);
    }
}

// Message with « Voir la liste » and « Annuler »
function done(message, undo) {
    notify(message, { action: { label: "Annuler", onClick: undo }, duration: 6000 });
    const toast = document.getElementById("toast");
    const undoButton = toast && toast.querySelector("button");
    if (undoButton) {
        const view = document.createElement("button");
        view.type = "button";
        view.className = "toast-action";
        view.textContent = "Voir la liste";
        view.addEventListener("click", () => {
            toast.hidden = true;
            navigate("/liste");
        });
        undoButton.before(view, " ");
    }
    bump();
}

function copy(item) {
    return item ? JSON.parse(JSON.stringify(item)) : null;
}

// Puts the line of `query` back as it was (`before`: the line, or null)
async function restore(query, before, after, store) {
    if (!before) {
        if (after) await api(`/api/list/${after.id}`, { method: "DELETE" });
    } else {
        const old = store ? before.picks[store] : null;
        if (store && old) await api("/api/list", { method: "POST", body: { query: before.query, product: old } });
        else if (store && after && after.picks[store]) {
            await api(`/api/list/${after.id}`, { method: "PATCH", body: { remove_pick: store } });
        }
        if (after && after.quantity !== before.quantity) {
            await api(`/api/list/${after.id}`, { method: "PATCH", body: { quantity: before.quantity } });
        }
    }
    await loadList();
}

function undoer(query, before, after, store) {
    return async () => {
        try {
            await restore(query, before, after, store);
            notify("Ajout annulé");
        } catch (err) {
            notify(err.message, { type: "error" });
        }
    };
}

// Saves the choice of the sheet. Returns the message shown.
// `saved` runs once the list is saved, before the message (the sheet closes)
export async function addToMyList({ query, product = null, quantity = 1, saved = null }) {
    const before = copy(lineFor(query));
    const replaced = product && before && before.picks[product.store];
    const replacedOther = replaced && !sameProduct(replaced, product) ? replaced : null;
    let item = await api("/api/list", { method: "POST", body: { query, quantity, product } });
    if (item.quantity !== quantity) {
        item = await api(`/api/list/${item.id}`, { method: "PATCH", body: { quantity } });
    }
    await loadList();
    if (saved) saved();
    let message;
    if (product) {
        message = `Ajouté à « ${item.query} »`;
        if (replacedOther) message += ` · Remplace ${replacedOther.name} (${retailer(product.store).label})`;
    } else {
        message = before ? `« ${item.query} » : quantité ${item.quantity}` : `« ${item.query} » ajouté à votre liste`;
    }
    done(message, undoer(query, before, item, product ? product.store : null));
    return message;
}

// « ✓ »: the product is no longer the choice of its retailer (the line goes
// away when it was its only content)
export async function removeFromMyList(product) {
    const line = lineWithProduct(product);
    if (!line) return;
    const before = copy(line);
    const alone = Object.keys(line.picks).length === 1;
    try {
        if (alone) await api(`/api/list/${line.id}`, { method: "DELETE" });
        else await api(`/api/list/${line.id}`, { method: "PATCH", body: { remove_pick: product.store } });
        await loadList();
        const message = `${product.name} (${retailer(product.store).label}) retiré de votre liste`;
        notify(message, {
            action: {
                label: "Annuler",
                onClick: async () => {
                    try {
                        let item = await api("/api/list", {
                            method: "POST",
                            body: { query: before.query, quantity: before.quantity, product: before.picks[product.store] },
                        });
                        if (item.quantity !== before.quantity) {
                            item = await api(`/api/list/${item.id}`, { method: "PATCH", body: { quantity: before.quantity } });
                        }
                        await loadList();
                        notify("Produit remis dans votre liste");
                    } catch (err) {
                        notify(err.message, { type: "error" });
                    }
                },
            },
            duration: 6000,
        });
        bump();
    } catch (err) {
        notify(err.message, { type: "error" });
    }
}

// ---------------------------------------------------------------- the sheet

let dialog = null;
let current = null; // { product, query, opener }

function ensureDialog() {
    if (dialog) return dialog;
    dialog = document.createElement("dialog");
    dialog.className = "add-sheet";
    dialog.id = "add-sheet";
    dialog.setAttribute("aria-labelledby", "add-sheet-title");
    dialog.dataset.testid = "add-sheet";
    document.body.append(dialog);
    dialog.addEventListener("click", (e) => {
        if (e.target === dialog) closeSheet(); // click on the backdrop
        const step = e.target.closest("[data-step]");
        if (step) {
            const field = dialog.querySelector("#sheet-qty");
            field.value = String(Math.min(99, Math.max(1, (Number(field.value) || 1) + Number(step.dataset.step))));
        }
        if (e.target.closest("[data-sheet-cancel]")) closeSheet();
    });
    dialog.addEventListener("change", () => describe());
    dialog.addEventListener("submit", async (e) => {
        e.preventDefault();
        await confirm();
    });
    dialog.addEventListener("close", () => {
        let opener = current && current.opener;
        const key = current && current.focusKey;
        current = null;
        // The « + » may have been drawn again meanwhile (« ✓ »): its new button
        if (opener && !opener.isConnected && key) opener = document.querySelector(`[data-focus="${CSS.escape(key)}"]`);
        if (opener && opener.isConnected) {
            opener.focus({ preventScroll: true });
            // Never under the message at the bottom of the screen
            opener.scrollIntoView({ block: "nearest" });
        }
    });
    return dialog;
}

function closeSheet() {
    if (dialog && dialog.open) dialog.close();
}

// Text under the choices: what will change in the list
function describe() {
    if (!current) return;
    const { product, query } = current;
    const exact = dialog.querySelector("input[name=what]:checked")?.value === "product";
    const line = lineFor(query);
    const note = dialog.querySelector("#sheet-note");
    let text = "";
    if (exact && line && line.picks[product.store] && !sameProduct(line.picks[product.store], product)) {
        text = `Remplace ${line.picks[product.store].name} (${retailer(product.store).label}).`;
    } else if (line) {
        text = `« ${line.query} » est déjà dans votre liste (quantité ${line.quantity}).`;
    }
    note.textContent = text;
    note.hidden = !text;
}

async function confirm() {
    if (!current) return;
    const { product, query } = current;
    const exact = dialog.querySelector("input[name=what]:checked")?.value === "product";
    const quantity = Math.min(99, Math.max(1, Math.round(Number(dialog.querySelector("#sheet-qty").value) || 1)));
    const submit = dialog.querySelector("[type=submit]");
    submit.disabled = true;
    try {
        await addToMyList({ query, product: exact ? product : null, quantity, saved: closeSheet });
    } catch (err) {
        notify(err.message, { type: "error" });
    } finally {
        submit.disabled = false;
    }
}

export function openAddSheet(product, query, opener = document.activeElement) {
    ensureDialog();
    current = { product, query, opener, focusKey: opener && opener.dataset ? opener.dataset.focus : null };
    const line = lineFor(query);
    const label = retailer(product.store).label;
    const meta = [brandText(product.brand), product.quantity_label].filter(Boolean).join(" · ");
    setHtml(
        dialog,
        html`<form class="add-sheet-form" method="dialog" aria-describedby="sheet-product">
            <h2 id="add-sheet-title" class="sheet-title">Ajouter à ma liste</h2>
            <div class="sheet-product" id="sheet-product">
                ${retailerBadge(product.store, label)}
                <span class="sheet-product-name">${product.name}${meta && html` <span class="muted">· ${meta}</span>`}</span>
                ${product.price != null && html`<strong class="sheet-price">${euros(product.price)}</strong>`}
            </div>
            <fieldset class="sheet-choice">
                <legend class="visually-hidden">Que mettre dans la liste ?</legend>
                <label class="choice">
                    <input type="radio" name="what" value="query">
                    <span><strong>« ${query} »</strong>, le moins cher sera choisi dans chaque enseigne</span>
                </label>
                <label class="choice">
                    <input type="radio" name="what" value="product" checked>
                    <span><strong>Exactement ce produit</strong> chez ${label}</span>
                </label>
            </fieldset>
            <div class="sheet-qty">
                <label for="sheet-qty">Quantité</label>
                <div class="stepper">
                    <button type="button" data-step="-1" aria-label="Un de moins">${icon("minus")}</button>
                    <input id="sheet-qty" type="number" min="1" max="99" step="1" inputmode="numeric" value="${line ? line.quantity : 1}">
                    <button type="button" data-step="1" aria-label="Un de plus">${icon("plus")}</button>
                </div>
            </div>
            <p class="sheet-note" id="sheet-note" aria-live="polite" hidden></p>
            <div class="sheet-actions">
                <button type="button" class="btn-ghost" data-sheet-cancel>Annuler</button>
                <button type="submit" class="btn-primary" autofocus>${line ? "Enregistrer" : "Ajouter"}</button>
            </div>
        </form>`,
    );
    describe();
    dialog.showModal();
}
