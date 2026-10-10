// Stub (P6: historique des prix). Hidden until it is built.

import { html, setHtml } from "../../core/html.js";

export const enabled = false;
export const title = "Historique";

export function render(el) {
    setHtml(el, html`<p class="muted">${title} : bientôt disponible.</p>`);
}
