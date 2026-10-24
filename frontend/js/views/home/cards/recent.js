// Home card « Recherches récentes » (area of P2, B33): the last searches of
// this device (each one can be removed), or, the first time, a few ideas.
// A card exports `enabled` and render(el); render may return a cleanup function.

import { html, setHtml } from "../../../core/html.js";
import { icon } from "../../../core/icons.js";
import { on, requestSearch } from "../../../core/store.js";
import { announce } from "../../../core/ui.js";
import { forgetSearch, recentSearches } from "../../search/memory.js";

export const enabled = true;

export const SUGGESTIONS = ["Farine", "Huile de tournesol", "Eau minérale", "Vinaigre", "Lait demi-écrémé", "Sucre"];

function draw(el) {
    const recent = recentSearches();
    if (!recent.length) {
        setHtml(
            el,
            html`<section class="recent-card" aria-labelledby="recent-title" data-testid="recent-card">
                <h2 id="recent-title" class="recent-title">Idées de recherche</h2>
                <div class="suggestions">${SUGGESTIONS.map(
                    (s) => html`<button type="button" class="suggestion" data-query="${s}">${s}</button>`,
                )}</div>
            </section>`,
        );
        return;
    }
    setHtml(
        el,
        html`<section class="recent-card" aria-labelledby="recent-title" data-testid="recent-card">
            <h2 id="recent-title" class="recent-title">${icon("history")}Recherches récentes</h2>
            <ul class="recent-chips">${recent.map(
                (r) => html`<li class="recent-chip">
                    <button type="button" class="suggestion" data-query="${r.q}">${r.q}</button>
                    <button type="button" class="recent-remove" data-forget="${r.q}" aria-label="Retirer « ${r.q} » des recherches récentes" title="Retirer">${icon("x")}</button>
                </li>`,
            )}</ul>
        </section>`,
    );
}

export function render(el) {
    draw(el);
    el.addEventListener("click", (e) => {
        const remove = e.target.closest("[data-forget]");
        if (remove) {
            const chips = [...el.querySelectorAll("[data-forget]")];
            const index = chips.indexOf(remove);
            forgetSearch(remove.dataset.forget);
            announce(`« ${remove.dataset.forget} » retiré des recherches récentes`);
            // The focus goes to the next chip (or to the title of the card)
            const next = el.querySelectorAll("[data-forget]")[Math.min(index, chips.length - 2)];
            if (next) next.focus();
            else el.querySelector(".suggestion")?.focus();
            return;
        }
        const button = e.target.closest(".suggestion");
        if (!button) return;
        document.getElementById("q").value = button.dataset.query;
        requestSearch(button.dataset.query);
    });
    return on("recent:changed", () => draw(el));
}
