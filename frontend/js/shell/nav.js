// Main navigation (#primary-nav): one link per view with a `nav` entry.
//
// The links are built once; afterwards only their address, active state and
// badge change, so that a click is never lost while the page updates.

import { html, setHtml } from "../core/html.js";
import { navEntries } from "../core/router.js";
import { on } from "../core/store.js";

let navEl = null;

function build(entries) {
    setHtml(
        navEl,
        html`${entries.map(
            (e) => html`<a class="nav-link" href="${e.href}" data-nav="${e.id}">${e.label} <span class="count" hidden></span></a>`,
        )}`,
    );
}

export function refreshNav() {
    if (!navEl) return;
    const entries = navEntries();
    const ids = entries.map((e) => e.id).join(",");
    if (navEl.dataset.ids !== ids) {
        build(entries);
        navEl.dataset.ids = ids;
    }
    for (const entry of entries) {
        const link = navEl.querySelector(`[data-nav="${CSS.escape(entry.id)}"]`);
        if (link.getAttribute("href") !== entry.href) link.setAttribute("href", entry.href);
        link.classList.toggle("active", entry.active);
        if (entry.active) link.setAttribute("aria-current", "page");
        else link.removeAttribute("aria-current");
        const count = link.querySelector(".count");
        const text = entry.badge == null ? "" : String(entry.badge);
        if (count.textContent !== text) count.textContent = text;
        count.hidden = entry.badge == null;
    }
}

export function initNav(selector = "#primary-nav") {
    navEl = document.querySelector(selector);
    on("*", refreshNav); // route, list (badge of « Ma liste »)...
    refreshNav();
}
