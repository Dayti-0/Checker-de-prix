// Home card: suggestions of products to search (area of P2).
// A card exports `enabled` and render(el); render may return a cleanup function.

import { html, setHtml } from "../../../core/html.js";
import { requestSearch } from "../../../core/store.js";

export const enabled = true;

const SUGGESTIONS = ["Farine", "Huile de tournesol", "Eau minérale", "Vinaigre", "Lait demi-écrémé", "Sucre"];

export function render(el) {
    setHtml(
        el,
        html`
        <div class="suggestions">
            ${SUGGESTIONS.map((s) => html`<button type="button" class="suggestion">${s}</button>`)}
        </div>`,
    );
    el.addEventListener("click", (e) => {
        const button = e.target.closest(".suggestion");
        if (!button) return;
        document.getElementById("q").value = button.textContent;
        requestSearch(button.textContent);
    });
}
