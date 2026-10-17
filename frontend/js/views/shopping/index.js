// Stub (P5: liste à cocher en magasin). Hidden until it is built.

import { html, setHtml } from "../../core/html.js";

export const enabled = false;
export const title = "En magasin";

export function render(el) {
    setHtml(el, html`<p class="muted">${title} : bientôt disponible.</p>`);
}
