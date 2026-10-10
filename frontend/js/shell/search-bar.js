// Search form (#search-form, #q) and retailer filters (#store-filters) above
// the views. Each view tells whether it shows them (`shell` of the view module).

import { mountStoreFilters } from "../components/store-filters.js";
import { currentView } from "../core/router.js";
import { on, requestSearch } from "../core/store.js";

function applyVisibility() {
    const shell = currentView()?.shell || {};
    document.getElementById("search-form").hidden = !shell.search;
    document.getElementById("store-filters").hidden = !shell.filters;
}

export function initSearchBar() {
    const form = document.getElementById("search-form");
    form.addEventListener("submit", (e) => {
        e.preventDefault();
        const query = document.getElementById("q").value.trim();
        if (query) requestSearch(query);
    });
    mountStoreFilters(document.getElementById("store-filters"));
    on("route:changed", applyVisibility);
    applyVisibility();
}
