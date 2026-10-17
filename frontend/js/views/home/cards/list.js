// Home card « Ma liste » (area of P5): the number of items, the verdict of the
// last basket, and the shortcuts « Comparer mon panier » and « En magasin ».
// Hidden while the list is empty. A card exports `enabled` and render(el);
// render may return a cleanup function.

import { retailerBadge } from "../../../components/retailer-badge.js";
import { api } from "../../../core/api.js";
import { plural, relativeTime } from "../../../core/fmt.js";
import { html, setHtml } from "../../../core/html.js";
import { icon } from "../../../core/icons.js";
import { navigate } from "../../../core/router.js";
import { on, state } from "../../../core/store.js";
import { verdict } from "../../basket/model.js";
import { compareNow, run } from "../../basket/runner.js";

export const enabled = true;

function lastLine(c) {
    if (!c) return "";
    const v = verdict(c);
    const when = c.created_at ? ` · comparé ${relativeTime(c.created_at)}` : "";
    if (c.outdated) return html`<p class="list-card-last muted">Votre liste a changé depuis la dernière comparaison.</p>`;
    if (v.kind === "best") {
        return html`<p class="list-card-last">${v.label} : ${retailerBadge(v.store, v.storeLabel)} <strong>${v.value}</strong><span class="muted">${when}</span></p>`;
    }
    if (v.kind === "most") return html`<p class="list-card-last">${v.text}<span class="muted">${when}</span></p>`;
    return "";
}

export function render(el) {
    let last = run.comparison;

    function draw() {
        const n = state.list.length;
        el.hidden = n === 0;
        if (!n) {
            setHtml(el, html``);
            return;
        }
        const names = state.list.slice(0, 4).map((i) => i.query);
        setHtml(
            el,
            html`<section class="list-card" aria-labelledby="list-card-title" data-testid="list-card">
                <h2 id="list-card-title" class="list-card-title">${icon("list")}Ma liste : ${plural(n, "article")}</h2>
                <p class="list-card-items">${names.join(", ")}${n > names.length ? "…" : ""}</p>
                ${lastLine(last)}
                <div class="list-card-actions">
                    <button type="button" class="btn-primary" data-card-compare>${icon("shopping-cart")}Comparer mon panier</button>
                    <a class="btn-ghost" href="#/courses">${icon("list-checks")}En magasin</a>
                    <a class="btn-ghost" href="#/liste">Voir ma liste</a>
                </div>
            </section>`,
        );
    }

    el.addEventListener("click", (e) => {
        if (!e.target.closest("[data-card-compare]")) return;
        compareNow();
        navigate("/panier");
    });
    draw();
    if (!last && state.list.length) {
        api("/api/basket/last")
            .then((c) => {
                last = c;
                draw();
            })
            .catch(() => {});
    }
    return on("list:changed", draw);
}
