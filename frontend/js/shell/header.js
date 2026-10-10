// Top bar: the location chip (« 34000 Montpellier », or « Code postal »).

import { on, state } from "../core/store.js";

function renderLocationChip() {
    const loc = state.settings && state.settings.location;
    document.getElementById("location-label").textContent = loc
        ? loc.city
            ? `${loc.postal_code} ${loc.city}`
            : loc.postal_code
        : "Code postal";
    document.getElementById("location-chip").classList.toggle("configured", Boolean(loc));
}

export function initHeader() {
    on("settings:changed", renderLocationChip);
}
