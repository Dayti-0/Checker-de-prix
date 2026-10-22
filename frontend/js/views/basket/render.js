// Markup of the basket page (B57, B61, B62): verdict, retailer cards, plans of
// the optimizer, the prices of each item (a table with sticky header and first
// column on a computer, one card per item on a phone, cheapest first).
//
// `view` (built by index.js) describes what to show:
//   { live, items: [{ id, query, quantity, target }], stores: [{ store, label }],
//     cell(store, id) → BasketLine | undefined, comparison, canChange }

import { retailerBadge } from "../../components/retailer-badge.js";
import { euros, plural } from "../../core/fmt.js";
import { html, safeUrl } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { brandText } from "../search/product-row.js";
import {
    cellNotes,
    cheapest,
    commonText,
    isComplete,
    itemOffers,
    planAmount,
    planMissingText,
    planTitle,
    reasonLabel,
    storeTexts,
    verdict,
} from "./model.js";

export function itemTitle(item) {
    if (item.target) return html`${item.query} <span class="item-qty">(${item.target})</span>`;
    return html`${item.query}${item.quantity > 1 ? html` <span class="item-qty">× ${item.quantity}</span>` : ""}`;
}

// ---------------------------------------------------------------- verdict

export function verdictMarkup(comparison) {
    const v = verdict(comparison);
    const cls = v.kind === "best" ? "best" : v.kind === "most" ? "partial" : "none";
    return html`<section class="verdict ${cls}" data-testid="basket-verdict" aria-labelledby="verdict-label">
        <p class="verdict-label" id="verdict-label">${icon(v.kind === "best" ? "circle-check" : "circle-alert")}${v.label}</p>
        ${
            v.store
                ? html`<p class="verdict-main">${retailerBadge(v.store, v.storeLabel)}<span class="verdict-value">${v.value}</span>${v.valueLabel ? html`<span class="verdict-unit">${v.valueLabel}</span>` : ""}</p>`
                : ""
        }
        <p class="verdict-text">${v.text}</p>
        ${v.sub ? html`<p class="verdict-sub">${v.sub}</p>` : ""}
    </section>`;
}

// What « Total estimé » and « articles communs » mean, under the cards that show them
export function totalsHelp(comparison) {
    const ranked = (comparison.stores || []).filter((s) => s.ranked);
    const parts = [];
    if (ranked.some((s) => s.estimated)) {
        parts.push("Total estimé : chaque article manquant est compté au prix médian des autres enseignes.");
    }
    if (ranked.some((s) => commonText(comparison, s))) {
        parts.push("Articles communs : ceux que toutes les enseignes classées ont, pour comparer à égalité.");
    }
    return parts.length ? html`<p class="basket-help" data-key="help">${parts.join(" ")}</p>` : "";
}

// ---------------------------------------------------------------- retailer cards

function actionMarkup(s) {
    if (s.action === "choose_store") {
        return html`<a class="btn-primary small" href="#/reglages?enseigne=${s.store}" aria-label="Choisir mon magasin ${s.label}">Choisir mon magasin</a>`;
    }
    if (s.action === "unblock") {
        return html`<button type="button" class="btn-primary small" data-setup="${s.store}" aria-label="Ouvrir le site ${s.label}">Ouvrir le site</button>`;
    }
    if (s.action === "retry") {
        return html`<button type="button" class="btn-ghost small" data-retry="${s.store}" aria-label="Réessayer ${s.label}">Réessayer</button>`;
    }
    return "";
}

function retryAfter(ts) {
    if (!ts) return "";
    const time = new Date(ts * 1000).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }).replace(":", " h ");
    return `Nouvel essai possible vers ${time}`;
}

export function storeCard(comparison, s) {
    const head = html`<div class="store-card-head">
        ${retailerBadge(s.store, s.label)}
        ${s.rank ? html`<span class="store-rank">${s.rank === 1 ? "1er" : `${s.rank}e`}<span class="visually-hidden"> du classement</span></span>` : ""}
    </div>`;
    if (s.status === "unchecked") {
        return html`<li class="store-card unchecked" data-key="${s.store}" data-store-card="${s.store}">
            <h3 class="visually-hidden">${s.label}</h3>
            ${head}
            <p class="store-reason">${icon("triangle-alert")}${reasonLabel(s.reason)}</p>
            ${s.message ? html`<p class="store-message">${s.message}</p>` : ""}
            ${s.retry_after ? html`<p class="store-message">${retryAfter(s.retry_after)}</p>` : ""}
            <div class="store-card-actions">${actionMarkup(s)}</div>
        </li>`;
    }
    const t = storeTexts(comparison, s);
    const complete = isComplete(s, comparison.item_count);
    const best = complete && comparison.best_store === s.store;
    const action = actionMarkup(s);
    return html`<li class="store-card${best ? " best" : ""}${complete ? " complete" : ""}${s.ranked ? "" : " unranked"}" data-key="${s.store}" data-store-card="${s.store}">
        <h3 class="visually-hidden">${s.label}</h3>
        ${head}
        <p class="store-count"><strong>${t.count}</strong>${complete ? html` <span class="tag ok">complet</span>` : ""}</p>
        <progress class="store-progress" value="${s.found_count}" max="${s.item_count || 1}" aria-label="Articles trouvés chez ${s.label}">${s.found_count}/${s.item_count}</progress>
        <dl class="store-totals">
            <div><dt>${complete ? "Total" : "Articles trouvés"}</dt><dd class="amount">${t.total}</dd></div>
            ${t.estimate ? html`<div class="estimate"><dt>Total estimé</dt><dd class="amount">${t.estimate}</dd></div>` : ""}
        </dl>
        ${t.missing ? html`<p class="store-missing">${t.missing}</p>` : ""}
        ${t.common ? html`<p class="store-common">${t.common}</p>` : ""}
        ${t.saving ? html`<p class="store-saving">${icon("trending-down")}${t.saving}</p>` : ""}
        ${t.unranked ? html`<p class="store-message">${t.unranked}</p>` : ""}
        ${t.notes.length ? html`<p class="store-notes">${t.notes.join(" · ")}</p>` : ""}
        ${s.message ? html`<p class="store-message">${s.message}</p>` : ""}
        ${s.retry_after ? html`<p class="store-message">${retryAfter(s.retry_after)}</p>` : ""}
        ${action ? html`<div class="store-card-actions">${action}</div>` : ""}
    </li>`;
}

// What the user can do for a retailer that failed while the others still answer
const LIVE_ACTIONS = { store_required: "choose_store", blocked: "unblock" };

// While the retailers answer: what was read so far
export function liveStoreCard(view, s, state) {
    const read = view.items.filter((i) => view.cell(s.store, i.id)).length;
    const found = view.items.filter((i) => view.cell(s.store, i.id)?.status === "found").length;
    const failed = state && state.status && state.status !== "ok" && state.status !== "empty";
    return html`<li class="store-card live${failed ? " unchecked" : ""}" data-key="${s.store}" data-store-card="${s.store}">
        <h3 class="visually-hidden">${s.label}</h3>
        <div class="store-card-head">${retailerBadge(s.store, s.label)}${!state && view.running ? html`<span class="spinner" aria-hidden="true"></span>` : ""}</div>
        ${
            failed
                ? html`<p class="store-reason">${icon("triangle-alert")}${reasonLabel(state.status)}</p>${state.message ? html`<p class="store-message">${state.message}</p>` : ""}`
                : html`<p class="store-count"><strong>${found}/${plural(view.items.length, "article")}</strong> trouvés</p>
        <progress class="store-progress" value="${read}" max="${view.items.length || 1}" aria-label="Articles lus chez ${s.label}">${read}/${view.items.length}</progress>
        <p class="store-notes">${read < view.items.length ? `${plural(read, "lu", "lus")} sur ${view.items.length}` : "Tous les articles sont lus"}</p>`
        }
        ${failed ? html`<div class="store-card-actions">${actionMarkup({ ...s, action: LIVE_ACTIONS[state.status] })}</div>` : ""}
    </li>`;
}

// ---------------------------------------------------------------- cells

function notesMarkup(line) {
    const notes = cellNotes(line);
    if (!notes.length) return "";
    return html`<span class="cell-notes">${notes.map((n) => html`<span class="note ${n.kind}">${n.text}</span>`)}</span>`;
}

function productName(line, storeLabel) {
    const p = line.product;
    const url = safeUrl(p.product_url);
    const brand = brandText(p.brand);
    const meta = [brand, p.quantity_label].filter(Boolean).join(" · ");
    const name = html`${line.picked ? html`${icon("star")}<span class="visually-hidden">Votre choix : </span>` : ""}${p.name}`;
    // One name per link: « Beurre doux, Aldi (nouvel onglet) »
    return html`<span class="cell-product">${
        url
            ? html`<a class="cell-name" href="${url}" target="_blank" rel="noopener noreferrer">${name}<span class="visually-hidden">, ${storeLabel} (nouvel onglet)</span></a>`
            : html`<span class="cell-name">${name}</span>`
    }${meta ? html`<span class="cell-meta">${meta}</span>` : ""}</span>`;
}

// `where`: "t" (table) or "c" (cards), so that the focus comes back to the one shown
function changeButton(view, item, s, line, where) {
    if (!view.canChange || !line || line.status === "unchecked") return "";
    const focus = `change-${where}-${s.store}-${item.id}`;
    if (line.status === "not_found") {
        return html`<button type="button" class="cell-btn" data-change="${item.id}" data-store="${s.store}" data-mode="manual" data-focus="${focus}" aria-label="Saisir le prix de ${item.query} chez ${s.label}">Saisir le prix</button>`;
    }
    return html`<button type="button" class="cell-btn" data-change="${item.id}" data-store="${s.store}" data-focus="${focus}" aria-label="Changer le produit ${item.query} chez ${s.label}">Changer</button>`;
}

// First line of a cell: the price (or the state) and « Changer » / « Saisir le
// prix » side by side; the button goes under them when the column is narrow
function cellTop(main, button) {
    return html`<span class="cell-top">${main}${button}</span>`;
}

// Content of a cell (table) or of an offer (card): price, button, product, notes
export function cellBody(view, item, s, line, low, where = "t") {
    if (!line) {
        return view.running
            ? html`<span class="cell-wait"><span class="spinner" aria-hidden="true"></span><span class="visually-hidden">En attente</span></span>`
            : html`<span class="cell-empty">—</span>`;
    }
    if (line.status === "found") {
        const best = low != null && line.line_total === low;
        const price = html`<span class="cell-price${best ? " low" : ""}">${euros(line.line_total)}${best ? html`<span class="visually-hidden"> (le moins cher)</span>` : ""}</span>`;
        return html`${cellTop(price, changeButton(view, item, s, line, where))}
            ${line.packs > 1 ? html`<span class="cell-packs">${line.packs} × ${euros(line.product.price)}</span>` : ""}
            ${productName(line, s.label)}
            ${notesMarkup(line)}`;
    }
    if (line.status === "excluded") {
        return cellTop(html`<span class="cell-state">Pas disponible ici</span>`, changeButton(view, item, s, line, where));
    }
    if (line.status === "not_found") {
        return html`${cellTop(html`<span class="cell-state">Introuvable</span>`, changeButton(view, item, s, line, where))}${notesMarkup(line)}${
            line.estimate != null ? html`<span class="note muted">compté ${euros(line.estimate)} dans l'estimation</span>` : ""
        }`;
    }
    const reason = view.reason(s.store);
    return html`<span class="cell-state muted">${reason ? reasonLabel(reason) : "Pas comparé"}</span>`;
}

// Lowest price of an item, once every retailer has answered for it (while the
// comparison runs, the first price read is not « le moins cher »)
function lowest(view, lines) {
    if (view.live && lines.some((l) => !l)) return null;
    return cheapest(lines);
}

// ---------------------------------------------------------------- retailers shown

// Retailers that could not be searched at all are said once, above the prices
// (their card gives the reason and the action), not in every row or card;
// while the comparison runs, the same for a retailer that failed before any
// product. { stores: searched, left: not compared }
export function searchedStores(view) {
    const failed = view.comparison
        ? view.comparison.stores.filter((s) => s.status === "unchecked")
        : view.stores.filter((s) => view.reason(s.store) && !view.items.some((i) => view.cell(s.store, i.id)?.status === "found"));
    const out = new Set(failed.map((s) => s.store));
    return { stores: view.stores.filter((s) => !out.has(s.store)), left: view.stores.filter((s) => out.has(s.store)) };
}

// « Intermarché et Courses U ne sont pas comparées : voir leur carte plus haut. »
export function leftOutNote(view) {
    const names = searchedStores(view).left.map((s) => s.label);
    if (!names.length) return "";
    const who = names.length >= 2 ? `${names.slice(0, -1).join(", ")} et ${names.at(-1)} ne sont pas comparées` : `${names[0]} n'est pas comparée`;
    // Printed without the cards: « … ne sont pas comparées. »
    return html`<p class="left-out-note" data-key="left-out">${icon("info")}<span>${who}<span class="see-cards">&nbsp;: voir leur carte plus haut</span>.</span></p>`;
}

// ---------------------------------------------------------------- table (computer)

function footCell(view, s) {
    if (view.live || !view.comparison) return html`<td class="foot-cell">…</td>`;
    const c = view.comparison.stores.find((x) => x.store === s.store);
    if (!c || c.status === "unchecked") return html`<td class="foot-cell muted">—</td>`;
    const best = view.comparison.best_store === s.store && isComplete(c, view.comparison.item_count);
    return html`<td class="foot-cell${best ? " best" : ""}">
        <span class="foot-total">${euros(c.total)}</span>
        ${c.estimated && c.estimated_total != null ? html`<span class="foot-est">estimé ${euros(c.estimated_total)}</span>` : ""}
        <span class="foot-count">${c.found_count}/${c.item_count}</span>
    </td>`;
}

export function tableMarkup(view) {
    const { stores } = searchedStores(view);
    if (!stores.length) return "";
    return html`<div class="table-scroll" tabindex="0" role="region" aria-label="Prix par article et par enseigne" data-testid="basket-table">
        <table class="basket-table cols-${Math.min(stores.length, 6)}">
            <caption class="visually-hidden">Prix de chaque article dans chaque enseigne</caption>
            <thead><tr><th scope="col" class="corner">Article</th>${stores.map((s) => html`<th scope="col">${retailerBadge(s.store, s.label)}</th>`)}</tr></thead>
            <tbody>${view.items.map((item) => {
                const lines = stores.map((s) => view.cell(s.store, item.id));
                const low = lowest(view, lines);
                return html`<tr data-key="row-${item.id}">
                    <th scope="row">${itemTitle(item)}</th>
                    ${stores.map((s, i) => {
                        const line = lines[i];
                        const best = line && line.status === "found" && line.line_total === low;
                        return html`<td class="cell ${line ? line.status : "wait"}${best ? " low" : ""}" data-cell="${s.store}:${item.id}"><div class="cell-body">${cellBody(view, item, s, line, low)}</div></td>`;
                    })}
                </tr>`;
            })}</tbody>
            <tfoot><tr><th scope="row">Total</th>${stores.map((s) => footCell(view, s))}</tr></tfoot>
        </table>
    </div>`;
}

// ---------------------------------------------------------------- cards (phone)

export function itemCardsMarkup(view) {
    const { stores } = searchedStores(view);
    if (!stores.length) return "";
    return html`<ul class="item-cards" data-testid="basket-items">${view.items.map((item) => {
        const offers = itemOffers(stores, item.id, view.cell);
        const low = lowest(view, offers.map((o) => o.line));
        return html`<li class="item-card" data-key="card-${item.id}" data-item-card="${item.id}">
            <h3 class="item-card-title">${itemTitle(item)}</h3>
            <ol class="offers">${offers.map(({ store, label, line }) => {
                const best = line && line.status === "found" && line.line_total === low;
                return html`<li class="offer ${line ? line.status : "wait"}${best ? " low" : ""}" data-offer="${store}">
                    <span class="offer-store">${retailerBadge(store, label)}</span>
                    <span class="offer-body">${cellBody(view, item, { store, label }, line, low, "c")}</span>
                </li>`;
            })}</ol>
        </li>`;
    })}</ul>`;
}

// ---------------------------------------------------------------- plans (optimizer, B61)

export function plansMarkup(comparison, items) {
    const plans = comparison.plans || [];
    if (!plans.length) return "";
    const names = new Map(items.map((i) => [i.id, i.query]));
    return html`<section class="plans" aria-labelledby="plans-title" data-testid="plans">
        <h2 id="plans-title" class="basket-h2">Où faire vos courses</h2>
        <ol class="plan-list">${plans.map((plan, i) => {
            const title = planTitle(plan);
            const amount = planAmount(plan);
            return html`<li class="plan${plan.complete ? " complete" : ""}" data-key="plan-${i}">
                <div class="plan-head">
                    <h3 class="plan-title">${title}</h3>
                    <span class="plan-total"><strong>${amount.value}</strong>${amount.qualifier ? html` <span class="muted">${amount.qualifier}</span>` : ""}</span>
                </div>
                ${plan.saving > 0 && plan.kind !== "single" ? html`<p class="plan-saving">${icon("trending-down")}${euros(plan.saving)} de moins qu'en un seul magasin</p>` : ""}
                ${plan.missing ? html`<p class="plan-missing">${planMissingText(plan, comparison)}${plan.missing_item_ids.length ? ` : ${plan.missing_item_ids.map((id) => names.get(id)).filter(Boolean).join(", ")}` : ""}</p>` : html`<p class="plan-ok">Tous les articles</p>`}
                ${
                    plan.stores.length > 1
                        ? html`<ul class="plan-stores">${plan.stores.map(
                              (ps) => html`<li>${retailerBadge(ps.store, ps.label)} <span class="plan-items">${ps.item_ids.map((id) => names.get(id)).filter(Boolean).join(", ")}</span> <span class="plan-sub">${euros(ps.total)}</span></li>`,
                          )}</ul>`
                        : ""
                }
                <a class="btn-ghost small plan-follow" href="#/courses?plan=${i}" aria-label="Suivre le plan ${title}">${icon("list-checks")}Suivre ce plan</a>
            </li>`;
        })}</ol>
        ${plans.length === 1 ? html`<p class="muted small">Un deuxième magasin n'est proposé que s'il fait économiser au moins ${euros(comparison.min_saving)}.</p>` : ""}
    </section>`;
}

