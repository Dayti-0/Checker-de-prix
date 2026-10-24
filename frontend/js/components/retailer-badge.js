// Retailer colours (classes .{key}-bg of css/components.css).

import { html } from "../core/html.js";
import { retailer } from "../core/store.js";

// Coloured label: <span class="badge aldi-bg">Aldi</span>
export function retailerBadge(key, label = retailer(key).label) {
    return html`<span class="badge ${key}-bg">${label}</span>`;
}

// Coloured dot, for filters and list picks
export function retailerDot(key) {
    return html`<span class="dot ${key}-bg"></span>`;
}
