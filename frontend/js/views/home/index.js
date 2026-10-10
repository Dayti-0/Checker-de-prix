// #/ : home page, under the search form (area of P1). Shows the cards of
// cards/*.js (fixed list, each card is filled by its lot).

import { emit } from "../../core/store.js";
import { html, setHtml } from "../../core/html.js";
import * as alerts from "./cards/alerts.js";
import * as list from "./cards/list.js";
import * as recent from "./cards/recent.js";
import * as savings from "./cards/savings.js";
import * as setup from "./cards/setup.js";
import * as status from "./cards/status.js";

// Display order of the cards
export const CARDS = { recent, list, alerts, savings, status, setup };

export const enabled = true;
export const title = "Rechercher";
export const nav = { id: "search", label: "Rechercher", icon: "search", order: 10, also: ["/recherche"] };
export const shell = { search: true, filters: true };

let cleanups = [];

export function render(el) {
    setHtml(
        el,
        html`
        <div id="welcome" class="welcome">
            <p>Tapez un produit pour comparer ses prix chez <strong>Aldi</strong>, <strong>Lidl</strong>, <strong>Carrefour</strong>, <strong>Intermarché</strong> et <strong>Courses U</strong>.</p>
        </div>`,
    );
    const welcome = el.querySelector("#welcome");
    for (const [name, card] of Object.entries(CARDS)) {
        if (!card.enabled) continue;
        const box = document.createElement("div");
        box.className = "home-card";
        box.dataset.card = name;
        welcome.append(box);
        const cleanup = card.render(box);
        if (typeof cleanup === "function") cleanups.push(cleanup);
    }
    document.getElementById("q").value = "";
    // As before: the home page forgets the last search
    emit("search:reset");
}

export function destroy() {
    cleanups.forEach((cleanup) => cleanup());
    cleanups = [];
}
