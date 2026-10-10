// Banner « Le navigateur PrixMalin est ouvert … J'ai terminé » (#setup-banner),
// shown while the user acts on a retailer site (area of P4).

import { endSetup, on, state } from "../core/store.js";

export const enabled = true;

function render() {
    document.getElementById("setup-banner").hidden = !(state.browser && state.browser.setup_mode);
}

export function init() {
    on("browser:changed", render);
    document.getElementById("setup-banner-done").addEventListener("click", endSetup);
    render();
}
