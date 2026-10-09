// Retailers to compare (ticked chips). The choice is shared by every view
// and saved in localStorage ("prixmalin.enabled").

import { setEnabled, store } from "../store.js";
import { escapeHtml } from "../util.js";
import { retailerDot } from "./retailerBadge.js";

function render(el) {
    el.innerHTML = store.retailers.map((r) => `
        <label class="store-toggle ${store.enabled.has(r.key) ? "on" : ""}">
            <input type="checkbox" value="${escapeHtml(r.key)}" ${store.enabled.has(r.key) ? "checked" : ""}>
            ${retailerDot(r.key)}${escapeHtml(r.label)}
        </label>`).join("");
}

// Fills `el` (a .store-filters element) and calls onChange(key, checked)
// after each change. The last ticked retailer cannot be unticked.
export function mountStoreFilters(el, onChange) {
    render(el);
    el.addEventListener("change", (e) => {
        const key = e.target.value;
        const checked = setEnabled(key, e.target.checked);
        e.target.checked = checked;
        render(el);
        if (onChange) onChange(key, checked);
    });
    return { refresh: () => render(el) };
}
