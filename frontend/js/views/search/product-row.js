// One product of the results (styles: .product… in css/results.css).
//
//   productRow(p, { cheapest, bestUnit, sort, gap, showStore, listed })
//
// - cheapest / bestUnit: product keys of « Le moins cher » and « Meilleur prix
//   au kg » (the same badges in both views);
// - gap: « +0,10 €/kg, +13 % » (Tout trié), showStore: retailer badge on the row;
// - listed: the product is a choice of « Ma liste » (button « ✓ Retirer … »).
// The row is updated in place by patch.js: each part has a data-key, and the
// buttons a data-focus to keep the focus. Extra badges and actions come from
// js/ext/product-badges.js and js/ext/product-actions.js.

import { retailerBadge } from "../../components/retailer-badge.js";
import { euros, unitText } from "../../core/fmt.js";
import { html, safeUrl } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { retailer } from "../../core/store.js";
import { renderActions } from "../../ext/product-actions.js";
import { renderBadges } from "../../ext/product-badges.js";
import { hasPromo, isAvailable, productKey } from "./rank.js";

// A thumbnail that cannot be loaded is removed: the drawing under it shows
document.addEventListener(
    "error",
    (e) => {
        if (e.target instanceof HTMLImageElement && e.target.closest(".thumb")) e.target.remove();
    },
    true,
);

// "CARREFOUR CLASSIC'" → "Carrefour Classic'" (brands written in capitals only)
export function brandText(brand) {
    const b = String(brand || "").trim();
    if (!b || b !== b.toLocaleUpperCase("fr") || b.length <= 2) return b;
    return b
        .toLocaleLowerCase("fr")
        .replace(/(^|[\s\-/.])(\p{L})/gu, (_, sep, letter) => sep + letter.toLocaleUpperCase("fr"));
}

// "0,25 €/œuf" for products sold by the piece, else "1,79 €/L" or the label of the site
export function unitLabel(p) {
    if (p.unit_price != null && p.unit === "pièce" && p.count_label) return `${euros(p.unit_price)}/${p.count_label}`;
    return unitText(p);
}

// Name of the product in the texts of the buttons: « Huile de tournesol Lesieur (Carrefour, 2,65 €) »
export function productLabel(p) {
    const brand = brandText(p.brand);
    const named = brand && !p.name.toLocaleLowerCase("fr").includes(brand.toLocaleLowerCase("fr"));
    const where = [retailer(p.store).label, p.price != null ? euros(p.price) : null].filter(Boolean).join(", ");
    return `${named ? `${p.name} ${brand}` : p.name} (${where})`;
}

function thumb(p) {
    const src = safeUrl(p.image_url);
    return html`<div class="thumb" data-key="thumb">${icon("shopping-cart")}${
        src &&
        html`<img src="${src}" alt="" width="56" height="56" loading="lazy" decoding="async" referrerpolicy="no-referrer">`
    }</div>`;
}

function nameOf(p) {
    const link = safeUrl(p.product_url);
    if (!link) return html`<span class="name"><span class="name-text">${p.name}</span></span>`;
    // The icon « nouvel onglet » never goes alone to the next line
    const cut = p.name.lastIndexOf(" ");
    const head = cut > 0 ? p.name.slice(0, cut + 1) : "";
    const tail = cut > 0 ? p.name.slice(cut + 1) : p.name;
    return html`<a class="name" href="${link}" target="_blank" rel="noopener noreferrer" data-focus="link:${productKey(p)}"><span class="name-text">${head}<span class="nowrap">${tail}${icon("external-link")}</span></span><span class="visually-hidden"> (nouvel onglet)</span></a>`;
}

function priceOf(p, sort) {
    const unit = unitLabel(p);
    const available = isAvailable(p);
    const old = p.old_price != null && p.price != null && p.old_price > p.price ? p.old_price : null;
    return html`${
        p.price != null
            ? html`<span class="price${available ? "" : " struck"}">${euros(p.price)}</span>`
            : html`<span class="price none">Prix non affiché</span>`
    }${old != null && html`<span class="old-price"><span class="visually-hidden">au lieu de </span><s>${euros(old)}</s></span>`}${
        unit && html`<span class="unit${sort === "unit" ? " strong" : ""}">${unit}</span>`
    }`;
}

function tags(p, isCheapest, isBestUnit) {
    const promo = p.promo || (hasPromo(p) ? "Promo" : "");
    return html`${isCheapest && html`<span class="tag best">${icon("circle-check")}Le moins cher</span>`}${
        isBestUnit && html`<span class="tag best">${icon("circle-check")}Meilleur prix au ${p.unit}</span>`
    }${promo && html`<span class="tag promo">${promo}</span>`}${p.bio && html`<span class="tag bio">Bio</span>`}${
        !isAvailable(p) && html`<span class="tag out">Indisponible</span>`
    }${renderBadges(p)}`;
}

export function productRow(p, options = {}) {
    const { cheapest = null, bestUnit = null, sort = "price", gap = "", showStore = false, listed = false } = options;
    const key = productKey(p);
    const isCheapest = cheapest === key;
    const isBestUnit = !isCheapest && bestUnit === key;
    const available = isAvailable(p);
    const meta = [brandText(p.brand), p.quantity_label].filter(Boolean).join(" · ");
    const label = productLabel(p);
    const classes = ["product", isCheapest || isBestUnit ? "best" : "", available ? "" : "unavailable"]
        .filter(Boolean)
        .join(" ");
    const addButton = listed
        ? html`<button class="add-btn added" type="button" data-action="remove" data-product="${key}" data-focus="add:${key}" aria-label="Retirer ${label} de ma liste" title="Dans ma liste">${icon("check")}</button>`
        : html`<button class="add-btn" type="button" data-action="add" data-product="${key}" data-focus="add:${key}" aria-label="Ajouter ${label} à ma liste" title="Ajouter à ma liste"${available ? "" : " disabled"}>${icon("plus")}</button>`;
    return html`<li class="${classes}" data-key="${key}" data-patch>
            ${thumb(p)}
            <div class="info" data-key="info">${showStore && html`<span class="row-store">${retailerBadge(p.store)}</span>`}${nameOf(p)}${
                meta && html`<div class="meta">${meta}</div>`
            }<div class="tags">${tags(p, isCheapest, isBestUnit)}</div></div>
            <div class="pricing" data-key="pricing">${priceOf(p, sort)}${gap && html`<span class="gap">${gap}</span>`}</div>
            <div class="row-actions" data-key="actions">${addButton}${renderActions(p)}</div>
        </li>`;
}
