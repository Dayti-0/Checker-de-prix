// Bootstrap: shell (top bar, nav, setup banner), shared data, views, router.
//
// Add a view: create js/views/<name>.js (see router.js for the view object)
// and register it below with one line.

import { registerView, refreshNav, start } from "./router.js";
import { endSetup, loadEnabled, loadList, loadSettings, store, subscribe } from "./store.js";
import { initTextSize } from "./textsize.js";
import { toast } from "./util.js";
import listView from "./views/list.js";
import searchView from "./views/search.js";
import settingsView from "./views/settings.js";

registerView(searchView);
registerView(listView);
registerView(settingsView);

// ---------------------------------------------------------------- shell

function renderLocationChip() {
    const loc = store.settings && store.settings.location;
    document.getElementById("location-label").textContent = loc ? (loc.city ? `${loc.postal_code} ${loc.city}` : loc.postal_code) : "Code postal";
    document.getElementById("location-chip").classList.toggle("configured", Boolean(loc));
}

function renderSetupBanner() {
    document.getElementById("setup-banner").hidden = !(store.browser && store.browser.setup_mode);
}

initTextSize();
subscribe("settings", renderLocationChip);
subscribe("browser", renderSetupBanner);
subscribe("*", refreshNav); // badges of the nav (e.g. number of items in the list)
document.getElementById("setup-banner-done").addEventListener("click", endSetup);

// ---------------------------------------------------------------- start

(async function init() {
    try {
        await loadSettings();
    } catch (err) {
        toast(`Serveur injoignable : ${err.message}`, true);
    }
    loadEnabled();
    await loadList();
    start({ outlet: "#view", nav: "#primary-nav", defaultPath: "/recherche" });
})();
