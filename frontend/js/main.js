// Start of the app: shell (top bar, navigation, search form), features, router.
//
// Where to add code: a view in js/views/<name>/ (route of js/routes.js), a
// home card in js/views/home/cards/, a settings section in
// js/views/settings/sections/, a banner or a header button in js/features/,
// a badge or an action on products in js/ext/. Not here.

import { defineRoutes, start } from "./core/router.js";
import { loadEnabled, loadList, loadSettings } from "./core/store.js";
import { notify } from "./core/ui.js";
import { initFeatures } from "./features/index.js";
import { DEFAULT_PATH, ROUTES } from "./routes.js";
import { initHeader } from "./shell/header.js";
import { initNav } from "./shell/nav.js";
import { initSearchBar } from "./shell/search-bar.js";
import { initTextSize } from "./shell/text-size.js";

defineRoutes(ROUTES);
initTextSize();
initHeader();
initNav("#primary-nav");
initFeatures();

(async function init() {
    try {
        await loadSettings();
    } catch (err) {
        notify(err.message, { type: "error" });
    }
    loadEnabled();
    await loadList();
    initSearchBar();
    start({ outlet: "#view", defaultPath: DEFAULT_PATH });
})();
