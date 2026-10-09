// One product of a search result (styles: .product… in css/search.css).
//
// `best` = { byPrice, byUnit }: the cheapest offers, highlighted.
// `addIndex`: value of data-add on the "+" button, for the caller to find the
// product again when it is clicked.

import { escapeHtml, euros, unitText } from "../util.js";

export function productRow(p, best = {}, addIndex = null) {
    const isBest = Boolean(best.byPrice) && p === best.byPrice;
    const isBestUnit = Boolean(best.byUnit) && p === best.byUnit;
    const tags = [];
    if (isBest) tags.push(`<span class="tag best">Le moins cher</span>`);
    if (isBestUnit && !isBest) tags.push(`<span class="tag best">Meilleur prix au ${escapeHtml(p.unit)}</span>`);
    if (p.promo) tags.push(`<span class="tag promo">${escapeHtml(p.promo)}</span>`);
    if (!p.available) tags.push(`<span class="tag out">Indisponible</span>`);
    const meta = [p.brand, p.quantity_label].filter(Boolean).map(escapeHtml).join(" · ");
    const image = p.image_url
        ? `<img src="${escapeHtml(p.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">`
        : "🛒";
    const unit = unitText(p);
    return `
        <li class="product${isBest || isBestUnit ? " best" : ""}${p.available ? "" : " unavailable"}">
            <div class="thumb">${image}</div>
            <div class="info">
                <a class="name" href="${escapeHtml(p.product_url)}" target="_blank" rel="noopener">${escapeHtml(p.name)}</a>
                ${meta ? `<div class="meta">${meta}</div>` : ""}
                ${tags.join("")}
            </div>
            <div class="pricing">
                ${p.price != null ? `<div class="price">${euros(p.price)}</div>` : `<div class="price none">Prix non affiché</div>`}
                ${unit ? `<div class="unit">${escapeHtml(unit)}</div>` : ""}
                ${addIndex != null ? `<button class="add-btn" data-add="${addIndex}" title="Ajouter ce produit à ma liste" aria-label="Ajouter à ma liste">+</button>` : ""}
            </div>
        </li>`;
}
