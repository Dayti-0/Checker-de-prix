// Home card « Finissez la configuration » (area of P4, B54): shown first while
// the postal code or the store of a retailer is missing; gone once every
// retailer is ready.

import { html, setHtml } from "../../../core/html.js";
import { icon } from "../../../core/icons.js";
import { on, state } from "../../../core/store.js";

export const enabled = true;
// To be shown before the other cards (the home page of P1 decides)
export const primary = true;

// What is left to set up: [{ key, text, href }]
export function missingSteps(settings = state.settings, retailers = state.retailers) {
    if (!settings) return [];
    const steps = [];
    if (!settings.location) {
        steps.push({ key: "location", text: "votre code postal", href: "#/bienvenue" });
    }
    for (const r of retailers) {
        if (r.needs_store && !r.store) {
            steps.push({ key: r.key, text: `votre magasin ${r.label}`, href: `#/reglages?enseigne=${r.key}` });
        }
    }
    return steps;
}

export function render(el) {
    function draw() {
        const steps = missingSteps();
        if (!steps.length) {
            setHtml(el, html``);
            el.hidden = true;
            return;
        }
        el.hidden = false;
        const target = steps[0].key === "location" ? "#/bienvenue" : steps[0].href;
        setHtml(
            el,
            html`<section class="setup-card" aria-labelledby="setup-card-title" data-testid="setup-card">
                <h2 id="setup-card-title" class="setup-card-title">${icon("map-pin")} Finissez la configuration</h2>
                <p>Pour voir les prix d'Intermarché et de Courses U, indiquez ${steps.map((s, i) => html`${i ? (i === steps.length - 1 ? " et " : ", ") : ""}<strong>${s.text}</strong>`)}.</p>
                <a class="btn-primary" href="${target}">${steps[0].key === "location" ? "Lancer l'assistant" : "Choisir mes magasins"}</a>
            </section>`,
        );
    }
    draw();
    return on("settings:changed", draw);
}
