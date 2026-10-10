// Retailers to compare (ticked chips, #store-filters of the page). The choice
// is shared by every view and saved in localStorage ("prixmalin.enabled");
// each change emits "filters:changed" (core/store.js).

import { attr, html, setHtml } from "../core/html.js";
import { setEnabled, state } from "../core/store.js";
import { retailerDot } from "./retailer-badge.js";

function render(el) {
    setHtml(
        el,
        html`${state.retailers.map(
            (r) => html`
        <label class="store-toggle ${state.enabled.has(r.key) ? "on" : ""}">
            <input type="checkbox" value="${r.key}"${attr({ checked: state.enabled.has(r.key) })}>
            ${retailerDot(r.key)}${r.label}
        </label>`,
        )}`,
    );
}

// Fills `el` and keeps it up to date. The last ticked retailer cannot be unticked.
export function mountStoreFilters(el) {
    render(el);
    el.addEventListener("change", (e) => {
        const key = e.target.value;
        const checked = setEnabled(key, e.target.checked);
        e.target.checked = checked;
        render(el);
    });
    return { refresh: () => render(el) };
}
