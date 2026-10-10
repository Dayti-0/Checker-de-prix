// Stub (P6: fiche d'un produit, #/produit/:store/:key). Hidden until it is built.

import { html, setHtml } from "../../core/html.js";

export const enabled = false;
export const title = "Produit";

export function render(el) {
    setHtml(el, html`<p class="muted">${title} : bientôt disponible.</p>`);
}
