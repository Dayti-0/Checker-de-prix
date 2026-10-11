// Filters of the search page (B30, B31).
//
// - Retailers compared (#store-filters, above the views; mounted by the shell
//   through components/store-filters.js): a fieldset « Enseignes comparées »,
//   one chip per retailer with its monogram (A, L, C, I, U), ticked = tinted
//   with ✓, unticked = outlined with « + ». On a phone, one row that scrolls
//   sideways. The choice is shared by every view and saved on the device
//   (core/store.js: setEnabled). The last ticked retailer cannot be unticked.
// - Filters of the results (resultFiltersMarkup): chips Bio, En promo,
//   Disponible, Marque distributeur, Marque nationale, with the number of
//   products each one keeps; those that would change nothing are disabled.

import { attr, html, setHtml } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { setEnabled, state } from "../../core/store.js";
import { notify } from "../../core/ui.js";
import { RESULT_FILTERS } from "./rank.js";

export const MONOGRAMS = { aldi: "A", lidl: "L", carrefour: "C", intermarche: "I", coursesu: "U" };

export function monogram(key, label = key) {
    return MONOGRAMS[key] || String(label).charAt(0).toUpperCase();
}

function renderStores(el) {
    setHtml(
        el,
        html`<fieldset class="store-chips">
            <legend class="store-chips-legend">Enseignes comparées</legend>
            <div class="store-chips-row">${state.retailers.map((r) => {
                const on = state.enabled.has(r.key);
                return html`<label class="store-toggle${on ? " on" : ""}">
                    <input type="checkbox" value="${r.key}"${attr({ checked: on })}>
                    <span class="mono ${r.key}-bg" aria-hidden="true">${monogram(r.key, r.label)}</span>
                    <span class="store-name">${r.label}</span>
                    ${icon(on ? "check" : "plus")}
                </label>`;
            })}</div>
        </fieldset>`,
    );
    const row = el.querySelector(".store-chips-row");
    if (row) {
        edges(row);
        row.addEventListener("scroll", () => edges(row), { passive: true });
    }
}

// Fades on the edges of the row only where there is more to see
function edges(row) {
    const max = row.scrollWidth - row.clientWidth;
    row.classList.toggle("more-before", row.scrollLeft > 2);
    row.classList.toggle("more-after", max > 2 && row.scrollLeft < max - 2);
}

// Fills `el` (#store-filters) and keeps it up to date
export function mountStoreFilters(el) {
    renderStores(el);
    el.addEventListener("change", (e) => {
        const input = e.target;
        if (!(input instanceof HTMLInputElement)) return;
        const key = input.value;
        const wanted = input.checked;
        const checked = setEnabled(key, wanted);
        if (!wanted && checked) notify("Gardez au moins une enseigne cochée.");
        const scroll = el.querySelector(".store-chips-row")?.scrollLeft || 0;
        renderStores(el);
        const row = el.querySelector(".store-chips-row");
        if (row) {
            row.scrollLeft = scroll;
            edges(row);
        }
        el.querySelector(`input[value="${CSS.escape(key)}"]`)?.focus({ preventScroll: true });
    });
    window.addEventListener("resize", () => {
        const row = el.querySelector(".store-chips-row");
        if (row) edges(row);
    });
    return { refresh: () => renderStores(el) };
}

// Chips of the result filters. counts: filterCounts() of the relevant
// products, total: their number, active: ids of the active filters. Every
// chip is always there (the page does not move when the retailers answer); a
// chip that would change nothing is disabled with aria-disabled: it stays
// reachable with the keyboard (and the row, that scrolls on a phone, too).
export function resultFiltersMarkup(counts, total, active) {
    const on = new Set(active);
    return html`<div class="result-filters-row" data-key="row" data-patch role="group" aria-label="Filtrer les résultats" data-testid="result-filters">
        ${RESULT_FILTERS.map((f) => {
            const useless = !on.has(f.id) && (counts[f.id] === 0 || counts[f.id] === total);
            return html`<button class="filter-chip${on.has(f.id) ? " on" : ""}" type="button" data-key="${f.id}" data-action="filter" data-filter="${f.id}" data-focus="filter:${f.id}" aria-pressed="${on.has(f.id) ? "true" : "false"}" aria-disabled="${useless ? "true" : "false"}">
                ${icon(on.has(f.id) ? "check" : "plus")}<span>${f.label}</span><span class="chip-count">${counts[f.id]}</span>
            </button>`;
        })}
        ${
            on.size > 0 &&
            html`<button class="filter-clear" type="button" data-key="clear" data-action="clear-filters" data-focus="clear-filters">${icon("x")}Retirer les filtres</button>`
        }
    </div>`;
}
