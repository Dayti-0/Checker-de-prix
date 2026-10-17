// Icons of the sprite /static/icons.svg (Lucide icons, ISC licence: frontend/vendor/README.md).
//
//   html`<button type="button">${icon("trash-2", { label: "Supprimer" })}</button>`
//
// Without label the icon is decorative (hidden from screen readers).

import { html } from "./html.js";

export const SPRITE = "/static/icons.svg";

export function icon(name, { label } = {}) {
    const href = `${SPRITE}#${name}`;
    return label
        ? html`<svg class="icon" role="img" aria-label="${label}"><use href="${href}"></use></svg>`
        : html`<svg class="icon" aria-hidden="true" focusable="false"><use href="${href}"></use></svg>`;
}
