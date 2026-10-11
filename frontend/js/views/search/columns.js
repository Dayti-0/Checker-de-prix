// View « Par enseigne »: one column per retailer (B27, B29, B39).
//
// Columns keep the display order of the retailers; a retailer that failed or
// found nothing leaves the grid for the compact bar above it (parts.js). A
// column shows its relevant products (5 first, « Voir N de plus »), then its
// « Produits proches » (folded) and how many products were read.

import { retailerBadge } from "../../components/retailer-badge.js";
import { plural } from "../../core/fmt.js";
import { html } from "../../core/html.js";
import { closeBlock, failureActions } from "./parts.js";
import { productRow } from "./product-row.js";
import { freshnessText, seconds, slowAfter } from "./summary.js";

export const PAGE_SIZE = 5;

const SKELETON = html`<div class="skeleton" aria-hidden="true"><div class="s-img"></div><div><div class="s-line"></div><div class="s-line short"></div></div></div>`;

function head(col, view, status) {
    const count = col.state === "loading" ? "recherche en cours" : plural(col.relevant.length, "produit");
    return html`<div class="column-head" data-key="head">
        <h2 class="column-title" aria-label="${col.label}, ${count}">${retailerBadge(col.key, col.label)}</h2>
        <span class="column-status">${status}</span>
    </div>`;
}

function loadingColumn(col, view) {
    const usual = view.usual(col.key);
    const slow = view.now - (col.result.started || view.now) > slowAfter(usual);
    const status = html`<span class="spinner"></span> ${slow ? "Plus long que d'habitude…" : `Recherche…${usual ? ` ${seconds(usual)}` : ""}`}`;
    return html`<section class="column loading" data-key="${col.key}" data-store="${col.key}" data-patch aria-busy="true">
        ${head(col, view, status)}
        <div class="column-body" data-key="skeleton">${SKELETON}${SKELETON}${SKELETON}</div>
    </section>`;
}

function notice(col, view) {
    const { result } = col;
    if (result.stale) {
        return html`<div class="notice warn" data-key="notice">${result.message || "Prix anciens : le site n'a pas répondu."}
            ${failureActions(col.key, col.label, result, view.now).length > 0 && html`<div class="actions">${failureActions(col.key, col.label, result, view.now)}</div>`}</div>`;
    }
    if (result.status === "store_required") {
        return html`<div class="notice warn" data-key="notice">${result.message || "Magasin à choisir"}
            <div class="actions">${failureActions(col.key, col.label, result, view.now)}</div></div>`;
    }
    if (!col.relevant.length) {
        const text = view.filtered && col.allRelevant.length ? "Aucun produit avec ces filtres." : `Aucun produit « ${view.query} » ici.`;
        return html`<div class="notice" data-key="notice">${text}</div>`;
    }
    return null;
}

function okColumn(col, view) {
    const { result } = col;
    const fresh = result.stale ? "" : freshnessText(result.fetched_at, view.now);
    const status =
        result.status === "store_required"
            ? "Magasin à choisir"
            : `${plural(col.relevant.length, "produit")}${fresh ? ` · ${fresh}` : ""}`;
    const expanded = Boolean(view.expanded[col.key]);
    const rows = expanded ? col.relevant : col.relevant.slice(0, PAGE_SIZE);
    const sub = result.store_label || (col.retailer.store && col.retailer.store.name);
    const read = (result.products || []).length;
    return html`<section class="column" data-key="${col.key}" data-store="${col.key}" data-patch>
        ${head(col, view, status)}
        ${sub && html`<div class="column-sub" data-key="sub">${sub}</div>`}
        ${notice(col, view)}
        ${
            rows.length > 0 &&
            html`<ul class="products" data-key="list" data-patch>${rows.map((p) => productRow(p, view.rowOptions(p)))}</ul>`
        }
        ${
            col.relevant.length > rows.length &&
            html`<button class="more-btn" type="button" data-key="more" data-action="more" data-store-key="${col.key}" data-focus="more:${col.key}" aria-label="Voir ${col.relevant.length - rows.length} de plus chez ${col.label}">Voir ${col.relevant.length - rows.length} de plus</button>`
        }
        ${closeBlock(col.key, col.close, Boolean(view.closeOpen[col.key]), view.closeRowOptions)}
        ${read > 0 && html`<p class="column-foot" data-key="foot">${plural(read, "produit lu", "produits lus")}</p>`}
    </section>`;
}

// columns: [{ key, label, retailer, result, state, relevant, allRelevant, close }]
// of the retailers shown in the grid (the others are in the bar)
export function columnsMarkup(columns, view) {
    return html`<div class="columns" data-key="columns" data-patch>${columns.map((col) =>
        col.state === "loading" ? loadingColumn(col, view) : okColumn(col, view),
    )}</div>`;
}
