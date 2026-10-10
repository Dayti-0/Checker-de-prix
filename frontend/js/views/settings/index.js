// #/reglages?enseigne=intermarche : settings page (area of P1).
//
// The page shows the sections of sections/*.js (fixed list, each section is
// filled by its lot), sorted by `order`. A section module exports
// { id, title, order, enabled, render(el) }; render may return a cleanup
// function. `enseigne` scrolls to the card of that retailer.

import { html, setHtml } from "../../core/html.js";
import { loadSettings } from "../../core/store.js";
import { notify } from "../../core/ui.js";
import * as about from "./sections/about.js";
import * as advanced from "./sections/advanced.js";
import * as data from "./sections/data.js";
import * as display from "./sections/display.js";
import * as location from "./sections/location.js";
import * as phone from "./sections/phone.js";
import * as security from "./sections/security.js";
import * as stores from "./sections/stores.js";

export const SECTIONS = [location, stores, display, advanced, security, data, phone, about];

export const enabled = true;
export const title = "Réglages";
export const nav = { id: "settings", label: "Réglages", icon: "settings", order: 90 };
export const shell = { search: false, filters: false };

let root = null;
let cleanups = [];

// Scrolls to the card of retailer `key`; false when it is not shown (yet)
function focusRetailer(key) {
    if (!key || !root) return false;
    const card = root.querySelector(`[data-retailer="${CSS.escape(key)}"]`);
    if (card) card.scrollIntoView({ block: "center" });
    return Boolean(card);
}

export function render(container, params) {
    root = container;
    setHtml(root, html`<div class="settings-page"><h1 class="page-title">Réglages</h1></div>`);
    const page = root.querySelector(".settings-page");
    const shown = SECTIONS.filter((s) => s.enabled).sort((a, b) => a.order - b.order);
    for (const section of shown) {
        const el = document.createElement("section");
        el.className = "settings-section";
        el.dataset.section = section.id;
        setHtml(el, html`<h3>${section.title}</h3><div class="settings-section-body"></div>`);
        page.append(el);
        const body = el.querySelector(".settings-section-body");
        try {
            const cleanup = section.render(body);
            if (typeof cleanup === "function") cleanups.push(cleanup);
        } catch (err) {
            console.error(err);
            setHtml(body, html`<p class="notice warn">Cette section n'a pas pu s'afficher.</p>`);
        }
    }
    const focused = focusRetailer(params.enseigne);
    // Fresh state of the stores and of the browser
    loadSettings()
        .then(() => focused || focusRetailer(params.enseigne))
        .catch((err) => notify(err.message, { type: "error" }));
}

export function update(params) {
    focusRetailer(params.enseigne);
}

export function destroy() {
    cleanups.forEach((cleanup) => cleanup());
    cleanups = [];
    root = null;
}
