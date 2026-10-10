// Home card: hint to choose the stores when a retailer needs one (area of P4).

import { html, setHtml } from "../../../core/html.js";
import { on, state } from "../../../core/store.js";

export const enabled = true;

export function render(el) {
    setHtml(
        el,
        html`<p id="welcome-setup" class="muted small" hidden>Astuce : indiquez votre code postal et vos magasins (⚙️) pour voir les prix Intermarché et Courses U.</p>`,
    );
    const hint = el.querySelector("#welcome-setup");
    const refresh = () => {
        hint.hidden = !state.retailers.some((r) => r.needs_store && !r.store);
    };
    refresh();
    return on("settings:changed", refresh);
}
