// One product of a search result (styles: .product… in css/results.css).
//
// `best` = { byPrice, byUnit }: the cheapest offers, highlighted.
// `addIndex`: value of data-add on the « + » button, for the caller to find
// the product again when it is clicked. Extra badges and actions come from
// js/ext/product-badges.js and js/ext/product-actions.js.

import { renderActions } from "../../ext/product-actions.js";
import { renderBadges } from "../../ext/product-badges.js";
import { euros, unitText } from "../../core/fmt.js";
import { html, safeUrl } from "../../core/html.js";

// A thumbnail that cannot be loaded is removed (the frame stays)
document.addEventListener(
    "error",
    (e) => {
        if (e.target instanceof HTMLImageElement && e.target.closest(".thumb")) e.target.remove();
    },
    true,
);

export function productRow(p, best = {}, addIndex = null) {
    const isBest = Boolean(best.byPrice) && p === best.byPrice;
    const isBestUnit = Boolean(best.byUnit) && p === best.byUnit;
    const meta = [p.brand, p.quantity_label].filter(Boolean).join(" · ");
    const imageUrl = safeUrl(p.image_url);
    const link = safeUrl(p.product_url);
    const unit = unitText(p);
    return html`
        <li class="product${isBest || isBestUnit ? " best" : ""}${p.available ? "" : " unavailable"}">
            <div class="thumb">${imageUrl ? html`<img src="${imageUrl}" alt="" loading="lazy" referrerpolicy="no-referrer">` : "🛒"}</div>
            <div class="info">
                ${link ? html`<a class="name" href="${link}" target="_blank" rel="noopener">${p.name}</a>` : html`<a class="name">${p.name}</a>`}
                ${meta && html`<div class="meta">${meta}</div>`}
                ${isBest && html`<span class="tag best">Le moins cher</span>`}${isBestUnit && !isBest && html`<span class="tag best">Meilleur prix au ${p.unit}</span>`}${p.promo && html`<span class="tag promo">${p.promo}</span>`}${!p.available && html`<span class="tag out">Indisponible</span>`}${renderBadges(p)}
            </div>
            <div class="pricing">
                ${p.price != null ? html`<div class="price">${euros(p.price)}</div>` : html`<div class="price none">Prix non affiché</div>`}
                ${unit && html`<div class="unit">${unit}</div>`}
                ${addIndex != null && html`<button class="add-btn" type="button" data-add="${addIndex}" title="Ajouter ce produit à ma liste" aria-label="Ajouter à ma liste">+</button>`}${renderActions(p)}
            </div>
        </li>`;
}
