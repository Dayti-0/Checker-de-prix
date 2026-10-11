// Parts shared by the two views of the results: « Produits proches » (folded
// by default), the bar of the retailers without results (B27) and the block
// « Aucun produit » (B34).

import { retailerBadge } from "../../components/retailer-badge.js";
import { plural } from "../../core/fmt.js";
import { html } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { productRow } from "./product-row.js";
import { shorterQueries } from "./rank.js";
import { failureLabel, STATUS_LABEL } from "./summary.js";

// « Produits proches (3) »: products that contain the words of the search
// without being the product searched (« Thon à l'huile de tournesol »).
// Never counted, never « Le moins cher »; folded until the user opens them.
export function closeBlock(id, products, open, rowOptions) {
    if (!products.length) return null;
    return html`<div class="close-block" data-key="close" data-patch data-testid="close-products">
        <button class="close-toggle" type="button" data-key="toggle" data-action="close" data-close="${id}" data-focus="close:${id}" aria-expanded="${open ? "true" : "false"}" aria-controls="close-${id}">
            ${icon(open ? "chevron-down" : "chevron-right")}<span>Produits proches (${products.length})</span>
        </button>
        <div class="close-body" id="close-${id}" data-key="body" data-patch${open ? "" : " hidden"}>
            ${open && html`<p class="close-help" data-key="help">Ils contiennent les mots cherchés sans être le produit cherché (par exemple un plat cuisiné avec cet ingrédient).</p>
            <ul class="products close-list" data-key="list" data-patch>${products.map((p) => productRow(p, rowOptions(p)))}</ul>`}
        </div>
    </div>`;
}

// Buttons of a retailer without results: « Choisir » (magasin à choisir), or
// « Ouvrir le site » (vérification requise) and « Réessayer »
export function failureActions(key, label, result, now = Date.now()) {
    const actions = [];
    const status = result.stale ? result.problem : result.status;
    const hardBlock = result.retry_after && result.retry_after * 1000 > now;
    if (status === "store_required") {
        actions.push(
            html`<button class="btn-primary small" type="button" data-open-settings="${key}" data-focus="settings:${key}" aria-label="Choisir mon magasin ${label}">Choisir</button>`,
        );
    }
    if (status === "blocked" && !hardBlock) {
        actions.push(
            html`<button class="btn-primary small" type="button" data-setup="${key}" data-focus="setup:${key}" aria-label="Ouvrir le site ${label}">Ouvrir le site</button>`,
        );
    }
    // « Magasin à choisir »: « Choisir » only (searching again changes nothing before)
    if (!hardBlock && !result.stale && status !== "store_required") {
        actions.push(
            html`<button class="btn-ghost small" type="button" data-action="retry" data-store-key="${key}" data-focus="retry:${key}" aria-label="Réessayer ${label}">Réessayer</button>`,
        );
    }
    return actions;
}

// One retailer of the bar: badge, reason, actions (one line on a computer)
function barItem(item, now) {
    const { key, label, result } = item;
    const empty = item.kind === "empty";
    const reason = empty ? STATUS_LABEL.empty : failureLabel(result, now);
    const detail = !empty && ["timeout", "error"].includes(result.status) ? result.message : "";
    const hardBlock = result.retry_after && result.retry_after * 1000 > now;
    return html`<div class="column-mini${empty ? " empty" : ""}" data-key="${key}" data-store="${key}">
        ${retailerBadge(key, label)}
        <span class="mini-status">${icon(empty ? "info" : "triangle-alert")}<strong class="column-status">${reason}</strong>${
            (detail || hardBlock) && html`<span class="mini-detail">${hardBlock ? result.message : detail}</span>`
        }</span>
        <span class="mini-actions">${failureActions(key, label, result, now)}</span>
    </div>`;
}

// Bar of the retailers that gave nothing: « 2 enseignes indisponibles : … »
// items: [{ key, label, result, kind: "error" | "empty" }]
export function unavailableBar(items, now = Date.now()) {
    if (!items.length) return html``;
    const errors = items.filter((i) => i.kind !== "empty").length;
    const empties = items.length - errors;
    const parts = [];
    if (errors) parts.push(plural(errors, "enseigne indisponible", "enseignes indisponibles"));
    if (empties) parts.push(errors ? `${empties} sans produit` : plural(empties, "enseigne sans produit", "enseignes sans produit"));
    return html`<div class="retailers-bar" data-key="bar" data-patch data-testid="unavailable" role="group" aria-labelledby="unavailable-title">
        <p class="retailers-bar-title" id="unavailable-title" data-key="title">${parts.join(", ")} :</p>
        ${items.map((item) => barItem(item, now))}
    </div>`;
}

// « Aucun produit pour « chocolat noir » » with shorter searches, tips and « Ajouter quand même »
export function noResults(query, { filtered = false } = {}) {
    if (filtered) {
        return html`<section class="no-results" data-key="none" data-testid="no-results" aria-labelledby="no-results-title">
            <h2 id="no-results-title">Aucun produit avec ces filtres</h2>
            <p>Les produits trouvés pour « ${query} » ne correspondent pas aux filtres choisis.</p>
            <button class="btn-primary" type="button" data-action="clear-filters" data-focus="show-all">Afficher tous les produits</button>
        </section>`;
    }
    const shorter = shorterQueries(query);
    return html`<section class="no-results" data-key="none" data-testid="no-results" aria-labelledby="no-results-title">
        <h2 id="no-results-title">Aucun produit pour « ${query} »</h2>
        ${
            shorter.length > 0 &&
            html`<p>Essayez une recherche plus courte :</p>
            <div class="retry-queries">${shorter.map(
                (q) =>
                    html`<button class="suggestion" type="button" data-action="query" data-query="${q}" data-focus="query:${q}" aria-label="Rechercher « ${q} »">${icon("search")}${q}</button>`,
            )}</div>`
        }
        <ul class="tips">
            <li>Vérifiez l'orthographe, ou écrivez le nom courant du produit (« lessive » plutôt que le nom d'une marque).</li>
            <li>Un nom plus général trouve plus de produits : « huile » plutôt que « huile de colza bio 75 cl ».</li>
            <li>Les sites ne montrent qu'une partie des produits vendus en magasin.</li>
        </ul>
        <button class="btn-ghost" type="button" data-action="add-query" data-focus="add-query">${icon("plus")}Ajouter « ${query} » à ma liste quand même</button>
    </section>`;
}
