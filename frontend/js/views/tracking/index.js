// Stub (P6: produits suivis et alertes). Hidden until it is built.

import { html, setHtml } from "../../core/html.js";

export const enabled = false;
export const title = "Suivis";

export function render(el) {
    setHtml(el, html`<p class="muted">${title} : bientôt disponible.</p>`);
}
