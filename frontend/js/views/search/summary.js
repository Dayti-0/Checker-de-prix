// Summary of a search (B26): the best offer, then one line per retailer with
// its best relevant price, the gap to the best one and a proportional bar. A
// retailer that failed shows « — » with an icon and the reason; one still
// searching, its usual time (« ~8 s ») and, when it lasts, « Plus long que
// d'habitude… [Ignorer] ». The space of every line is kept from the start:
// nothing moves under the summary while the retailers answer.

import { euros, plural, relativeTime } from "../../core/fmt.js";
import { html } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { retailerBadge } from "../../components/retailer-badge.js";
import { brandText, unitLabel } from "./product-row.js";
import { gapText } from "./rank.js";

// Short reason of a retailer without prices (glossary of CLAUDE.md)
export const STATUS_LABEL = {
    store_required: "Magasin à choisir",
    blocked: "Vérification requise",
    timeout: "Trop lent à répondre",
    error: "Site indisponible",
    empty: "Aucun produit",
    skipped: "Ignorée cette fois",
};

// After this time, a retailer still searching is « plus long que d'habitude »
export const SLOW_AFTER_MS = 15000;

export function slowAfter(usual) {
    return Math.max(SLOW_AFTER_MS, usual ? usual * 1.5 : 0);
}

// "prix d'il y a 2 h", "prix d'hier", "prix du 2 octobre" ("" for recent prices)
export function freshnessText(fetchedAt, now = Date.now()) {
    if (!fetchedAt) return "";
    const ms = fetchedAt < 1e12 ? fetchedAt * 1000 : fetchedAt;
    if (now - ms < 5 * 60000) return "";
    const rel = relativeTime(fetchedAt, now);
    if (rel.startsWith("il y a") || rel === "hier") return `prix d'${rel}`;
    if (rel.startsWith("le ")) return `prix du ${rel.slice(3)}`;
    return "";
}

// Label of a retailer that failed: hard block until a time, else the short reason
export function failureLabel(result, now = Date.now()) {
    if (result.status === "blocked" && result.retry_after && result.retry_after * 1000 > now) return "Accès suspendu";
    return STATUS_LABEL[result.status] || "Site indisponible";
}

export function seconds(ms) {
    return `~${Math.max(1, Math.round(ms / 1000))} s`;
}

// Under the best offer when there is no saving to tell
function aloneText(summary) {
    if (summary.lines.filter((l) => l.value != null).length >= 2) return "Même prix dans les enseignes comparées.";
    if (summary.done < summary.total) return "Le seul prix trouvé pour l'instant.";
    return summary.criterion === "unit" ? `Le seul prix au ${summary.unit} trouvé.` : "Le seul prix trouvé.";
}

function bestCard(summary, view) {
    const { best, headline, savings, unit, criterion } = summary;
    if (!best) {
        const searching = summary.done < summary.total;
        return html`<div class="summary-card${searching ? " waiting" : " empty"}" data-key="best" data-testid="best-offer">
            <p class="label">${headline}</p>
            <p class="best-wait">${searching ? html`<span class="spinner"></span> Recherche des prix…` : "Aucun prix à comparer pour le moment."}</p>
        </div>`;
    }
    const what = [best.name, brandText(best.brand), best.quantity_label].filter(Boolean).join(" · ");
    const perUnit = unitLabel(best);
    const main = criterion === "unit" ? perUnit : euros(best.price);
    const second = criterion === "unit" ? euros(best.price) : perUnit;
    const saved = savings != null && `${euros(savings)}${criterion === "unit" && unit ? `/${unit}` : ""}`;
    return html`<div class="summary-card" data-key="best" data-testid="best-offer">
        <p class="label">${icon("circle-check")}${headline}</p>
        <div class="best-main">${retailerBadge(best.store, view.label(best.store))}<span class="value">${main}</span>${
            second && html`<span class="best-unit">${second}</span>`
        }</div>
        <p class="what">${what}</p>
        ${saved ? html`<p class="savings">Jusqu'à ${saved} de moins que l'offre la plus chère.</p>` : html`<p class="savings muted">${aloneText(summary)}</p>`}
    </div>`;
}

function lineBody(line, view) {
    const result = view.results[line.key] || { status: "loading" };
    if (line.state === "loading") {
        const usual = view.usual(line.key);
        const elapsed = view.now - (result.started || view.now);
        if (elapsed > slowAfter(usual)) {
            return html`<span class="line-wait slow">${icon("clock")}Plus long que d'habitude…</span>
                <button class="btn-ghost small line-action" type="button" data-action="skip" data-store-key="${line.key}" data-focus="skip:${line.key}" aria-label="Ignorer ${view.label(line.key)} pour cette recherche">Ignorer</button>`;
        }
        return html`<span class="line-wait"><span class="spinner"></span>Recherche…${usual ? ` ${seconds(usual)}` : ""}</span>`;
    }
    if (line.state === "error" || line.state === "none") {
        let reason = "Aucun produit";
        if (line.state === "error") reason = failureLabel(result, view.now);
        else if (line.noUnit) reason = `Pas de prix au ${view.unit}`;
        return html`<span class="line-price none" aria-hidden="true">—</span><span class="line-reason">${icon(line.state === "error" ? "triangle-alert" : "info")}${reason}</span>`;
    }
    const p = line.product;
    const value = view.criterion === "unit" ? unitLabel(p) : euros(p.price);
    const g = gapText(line.gap, view.criterion === "unit" ? view.unit : null);
    const fresh = result.stale ? "ancien prix" : freshnessText(result.fetched_at, view.now);
    return html`<span class="line-price">${value}</span>
        <span class="line-gap${g ? "" : " best"}">${g || "le moins cher"}</span>
        <span class="line-bar" aria-hidden="true"><span class="bar" data-bar="${line.bar}"></span></span>
        <span class="line-name">${p.name}${fresh && html` <span class="line-fresh${result.stale ? " stale" : ""}">· ${fresh}</span>`}</span>`;
}

// Markup of #summary. view: { results, keys, label(key), usual(key), now,
// done (all answered), unavailable (number) } + summarize() → summary
export function summaryMarkup(summary, view) {
    const ctx = { ...view, unit: summary.unit, criterion: summary.criterion };
    const searching = summary.done < summary.total;
    const foot = searching
        ? html`<p class="summary-progress" data-key="foot"><span class="spinner"></span> ${summary.done}/${summary.total} enseignes ont répondu…</p>`
        : html`<p class="summary-foot" data-key="foot">${plural(summary.total, "enseigne comparée", "enseignes comparées")}${
              view.unavailable ? ` · ${plural(view.unavailable, "indisponible", "indisponibles")}` : ""
          }</p>`;
    return html`<h2 class="visually-hidden" id="summary-title" data-key="title">Synthèse des prix</h2>
        ${bestCard(summary, ctx)}
        <div class="summary-lines-box" data-key="lines-box" data-patch>
            <p class="summary-lines-title" data-key="lines-title">${summary.criterion === "unit" ? `Meilleur prix au ${summary.unit} par enseigne` : "Meilleur prix par enseigne"}</p>
            <ul class="summary-lines" data-key="lines" data-patch>${summary.lines.map(
                (line) => html`<li class="summary-line ${line.state}" data-key="${line.key}" data-summary="${line.key}">
                    <span class="line-store">${retailerBadge(line.key, view.label(line.key))}</span>
                    ${lineBody(line, ctx)}
                </li>`,
            )}</ul>
            ${foot}
        </div>`;
}

// Width of the bars (no style attribute: CSP), after each update
export function applyBars(root) {
    for (const bar of root.querySelectorAll("[data-bar]")) {
        const width = `${bar.dataset.bar}%`;
        if (bar.style.width !== width) bar.style.width = width;
    }
}
