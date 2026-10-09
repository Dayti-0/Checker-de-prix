// Retailer colours (CSS classes .{key}-bg in css/base.css)

import { retailer } from "../store.js";
import { escapeHtml } from "../util.js";

// Coloured label: <span class="badge aldi-bg">Aldi</span>
export function retailerBadge(key, label = retailer(key).label) {
    return `<span class="badge ${escapeHtml(key)}-bg">${escapeHtml(label)}</span>`;
}

// Coloured dot, for filters and list picks
export function retailerDot(key) {
    return `<span class="dot ${escapeHtml(key)}-bg"></span>`;
}
