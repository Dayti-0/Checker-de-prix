// View « Tout trié » (B25, B38): one list of the relevant products of every
// retailer, in the order of the sort, each with its retailer and its gap to the
// best offer (« +0,10 €/kg, +13 % »). Products with the same barcode are one
// line « Même produit dans 3 enseignes : … » that unfolds. Then the
// « Produits proches » of every retailer, folded.

import { euros, plural } from "../../core/fmt.js";
import { html } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { retailer } from "../../core/store.js";
import { storeCount } from "./group.js";
import { closeBlock } from "./parts.js";
import { productRow } from "./product-row.js";

export const PAGE_SIZE = 20;

function groupLine(g, open, view) {
    const n = storeCount(g);
    const prices = g.products
        .filter((p) => p.price != null)
        .map((p) => `${retailer(p.store).label} ${euros(p.price)}`)
        .join(" · ");
    const name = g.products[0].name;
    return html`<div class="same-product" data-key="same">
        ${icon("store")}<span>Même produit dans ${n} enseignes : ${prices}</span>
        <button class="link-btn" type="button" data-action="group" data-group="${g.key}" data-focus="group:${g.key}" aria-expanded="${open ? "true" : "false"}" aria-label="${open ? "Masquer" : "Voir"} les ${g.products.length} offres de ${name}">${open ? "Masquer" : `Voir les ${g.products.length} offres`}</button>
    </div>`;
}

function groupMarkup(g, view) {
    if (g.products.length === 1) return productRow(g.products[0], view.rowOptions(g.products[0], true));
    const open = Boolean(view.groupsOpen[g.key]);
    const [lead, ...others] = g.products;
    return html`<li class="offer-group" data-key="${g.key}" data-patch>
        <ul class="products" data-key="lead" data-patch>${productRow(lead, view.rowOptions(lead, true))}</ul>
        ${groupLine(g, open, view)}
        ${open && html`<ul class="products group-others" data-key="others" data-patch>${others.map((p) => productRow(p, view.rowOptions(p, true)))}</ul>`}
    </li>`;
}

// groups: group() of the ranked relevant products; pending: offers held back
// while the user reads further down (« 3 nouvelles offres »)
export function offersMarkup({ groups, count, stores, close, pending }, view) {
    const shown = view.expanded.all ? groups : groups.slice(0, PAGE_SIZE);
    return html`<section class="offers" data-key="offers" data-patch aria-labelledby="offers-title" data-testid="offers">
        <div class="offers-head" data-key="head">
            <h2 class="offers-title" id="offers-title">Meilleures offres</h2>
            <span class="offers-count">${count ? `${plural(count, "produit")} dans ${plural(stores, "enseigne")}` : ""}</span>
        </div>
        ${
            pending > 0 &&
            html`<button class="new-offers" type="button" data-key="pending" data-action="show-pending" data-focus="show-pending" data-testid="new-offers">${icon("refresh-cw")}${plural(pending, "nouvelle offre", "nouvelles offres")}</button>`
        }
        ${shown.length > 0 && html`<ol class="products offer-list" data-key="list" data-patch>${shown.map((g) => groupMarkup(g, view))}</ol>`}
        ${
            groups.length > shown.length &&
            html`<button class="more-btn" type="button" data-key="more" data-action="more" data-store-key="all" data-focus="more:all">Voir ${groups.length - shown.length} de plus</button>`
        }
        ${closeBlock("all", close, Boolean(view.closeOpen.all), view.closeRowOptions)}
    </section>`;
}
