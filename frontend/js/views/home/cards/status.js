// Home card: state of the retailers (area of P4, B55).
//
// A pill per retailer once a search was made, and a warning when a retailer
// failed 3 times in a row (or needs a check), with a link to « État des
// enseignes ». Nothing before the first search.

import { html, setHtml } from "../../../core/html.js";
import { on } from "../../../core/store.js";
import { HEALTH_KIND, health, loadHealth, statePill } from "../../status/shared.js";

export const enabled = true;

// Failed searches in a row before the warning
export const ALERT_AFTER = 3;

// Warning after ALERT_AFTER failed searches in a row ("" when all is well)
export function alertText(list) {
    const broken = list.filter((h) => h.consecutive_failures >= ALERT_AFTER || h.state === "broken");
    if (!broken.length) return "";
    if (broken.length > 1) {
        return `${broken.map((h) => h.label).join(", ")} ne donnent plus de résultats depuis plusieurs recherches.`;
    }
    const h = broken[0];
    if (h.state === "blocked") {
        return `${h.label} demande une vérification anti-robot depuis ${h.consecutive_failures} recherches.`;
    }
    return `${h.label} ne donne plus de résultats depuis ${h.consecutive_failures} recherches.`;
}

export function render(el) {
    function draw() {
        const list = health.list || [];
        if (!list.some((h) => h.last_at)) {
            setHtml(el, html``);
            return;
        }
        const alert = alertText(list);
        setHtml(
            el,
            html`<section class="home-status" aria-labelledby="home-status-title">
                <h2 id="home-status-title" class="visually-hidden">État des enseignes</h2>
                ${
                    alert &&
                    html`<div class="home-status-alert" role="note"><p>${alert}</p><a href="#/etat">Voir l'état des enseignes</a></div>`
                }
                <ul class="home-status-pills">${list.map(
                    (h) =>
                        html`<li><span>${h.label}</span>${statePill(HEALTH_KIND[h.state] || "unknown", h.state_label)}</li>`,
                )}</ul>
                ${!alert && html`<p class="small"><a href="#/etat">État des enseignes</a></p>`}
            </section>`,
        );
    }
    draw();
    loadHealth();
    return on("status:changed", draw);
}
