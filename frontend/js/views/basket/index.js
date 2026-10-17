// #/panier : comparison of the basket (area of P5: B57, B59, B60, B61, B62, B71).
//
// From top to bottom: actions (« Actualiser les prix » / « Arrêter »), state of
// the comparison (progress « 12/40 recherches », date, list changed since…),
// verdict (« Panier le moins cher » only for a complete basket, else « Aucune
// enseigne n'a tout : Aldi en a le plus (3/4) »), one card per retailer
// (articles found, total, estimated total, common items, reason and action of
// a retailer that could not be searched), plans of the optimizer (« Suivre ce
// plan » → #/courses), the price of each item at each retailer (table on a
// computer, one card per item on a phone) with « Changer » / « Saisir le prix ».
// The comparison runs in runner.js (live, cell by cell) and survives a trip to
// another view. The page is updated in place (patch.js): focus and scroll stay.

import { api } from "../../core/api.js";
import { plural, relativeTime } from "../../core/fmt.js";
import { html, setHtml } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { on, retailer, state } from "../../core/store.js";
import { announce, notify } from "../../core/ui.js";
import { watchList } from "../list/sync.js";
import { patch } from "../search/patch.js";
import { openSite } from "../status/shared.js";
import { openChangeSheet } from "./change-sheet.js";
import { progressText, verdict } from "./model.js";
import { itemCardsMarkup, liveStoreCard, plansMarkup, storeCard, tableMarkup, verdictMarkup } from "./render.js";
import { compareNow, loadLast, recompare, run, stop, subscribe, tickedStores } from "./runner.js";

export const enabled = true;
export const title = "Panier";
export const shell = { search: false, filters: true };

let root = null;
let cleanups = [];
let frame = 0;
let announcedStart = false;
let checkTimer = null;

// ---------------------------------------------------------------- what to show

function listItem(id) {
    return state.list.find((i) => i.id === id) || null;
}

export function buildView() {
    const c = run.comparison;
    const live = run.status === "running" || run.status === "stopped" || (run.status === "error" && run.items.length > 0);
    if (live) {
        return {
            live: true,
            running: run.status === "running",
            items: run.items.map((i) => {
                const item = listItem(i.id);
                return { id: i.id, query: i.query, quantity: item ? item.quantity : 1, target: item ? item.target : null };
            }),
            stores: run.stores,
            cell: (store, id) => run.cells[`${store}:${id}`],
            reason: (store) => {
                const st = run.storeStates[store];
                return st && st.status !== "ok" && st.status !== "empty" ? st.status : null;
            },
            comparison: null,
            canChange: false,
        };
    }
    if (!c) return null;
    const lines = new Map();
    for (const s of c.stores) for (const l of s.lines) lines.set(`${s.store}:${l.item_id}`, l);
    const first = c.stores[0];
    return {
        live: false,
        running: false,
        items: (first ? first.lines : []).map((l) => ({ id: l.item_id, query: l.query, quantity: l.quantity, target: l.target })),
        stores: c.stores.map((s) => ({ store: s.store, label: s.label })),
        cell: (store, id) => lines.get(`${store}:${id}`),
        reason: (store) => (c.stores.find((s) => s.store === store) || {}).reason || null,
        comparison: c,
        canChange: !run.updating && !c.outdated,
    };
}

function storesChanged(c) {
    if (!c) return false;
    const compared = c.stores.map((s) => s.store).sort().join(",");
    return compared !== [...tickedStores()].sort().join(",");
}

// ---------------------------------------------------------------- markup

function topMarkup(view) {
    const n = view ? view.items.length : state.list.filter((i) => i.compare).length;
    const m = view ? view.stores.length : tickedStores().length;
    let action;
    if (run.status === "running") {
        action = html`<button type="button" class="btn-ghost" data-stop data-focus="basket-action">${icon("x")}Arrêter</button>`;
    } else if (view) {
        action = html`<button type="button" class="btn-ghost" data-refresh data-focus="basket-action">${icon("refresh-cw")}Actualiser les prix</button>`;
    } else if (state.list.length) {
        action = html`<button type="button" class="btn-primary" data-start data-focus="basket-action">${icon("shopping-cart")}Comparer mon panier</button>`;
    }
    return html`<div class="basket-top" data-key="top">
        <div class="basket-heading">
            <h1 class="basket-title">Mon panier</h1>
            <span class="basket-sub">${n ? `${plural(n, "article")} · ${plural(m, "enseigne")}` : ""}</span>
        </div>
        <div class="basket-actions">${action || ""}<a class="btn-ghost" href="#/liste">${icon("list")}Modifier ma liste</a></div>
    </div>`;
}

function notice(key, text, label) {
    return html`<div class="notice warn basket-notice" data-key="${key}">
        <p>${text}</p>
        <div class="actions"><button type="button" class="btn-primary small" data-start>${label}</button></div>
    </div>`;
}

function statusMarkup() {
    const c = run.comparison;
    if (run.status === "running") {
        return html`<div class="basket-progress" data-key="status" data-testid="basket-progress">
            <span class="progress-text"><span class="spinner" aria-hidden="true"></span> Comparaison en cours : ${progressText(run.done, run.total)}</span>
            <progress value="${run.done}" max="${run.total || 1}" aria-label="Recherches faites">${run.done}/${run.total}</progress>
        </div>`;
    }
    if (run.status === "stopped") {
        return notice("status", `Comparaison arrêtée : ${progressText(run.done, run.total)} faites.`, "Reprendre");
    }
    if (run.status === "error") return notice("status", run.error || "La comparaison a échoué.", "Réessayer");
    if (!c) return html``;
    let warning = "";
    if (c.outdated) warning = notice("outdated", "Votre liste a changé depuis cette comparaison.", "Comparer à nouveau");
    else if (storesChanged(c)) {
        warning = notice("stores", "Les enseignes cochées ont changé depuis cette comparaison.", "Comparer à nouveau");
    }
    const when = c.created_at ? `Comparé ${relativeTime(c.created_at)}` : "";
    return html`<div class="basket-status" data-key="status">
        <p class="basket-when">${run.updating ? html`<span class="spinner" aria-hidden="true"></span> Mise à jour…` : when}</p>
        ${warning}
    </div>`;
}

function waitingVerdict() {
    const running = run.status === "running";
    return html`<section class="verdict waiting" data-testid="basket-verdict" aria-labelledby="verdict-label">
        <p class="verdict-label" id="verdict-label">${icon("clock")}${running ? "Comparaison en cours" : "Comparaison incomplète"}</p>
        <p class="verdict-text">${
            running
                ? "Chaque article est cherché dans chaque enseigne : les prix s'affichent au fur et à mesure."
                : "Toutes les recherches n'ont pas été faites : relancez la comparaison pour voir le verdict."
        }</p>
    </section>`;
}

function skippedMarkup(c) {
    const ids = c ? c.skipped_item_ids || [] : run.skipped || [];
    const names = ids.map((id) => listItem(id)?.query).filter(Boolean);
    if (!names.length) return "";
    return html`<p class="basket-skipped" data-key="skipped">Hors comparaison : ${names.join(", ")}.</p>`;
}

function emptyMarkup() {
    return html`<div class="list-empty" data-key="empty">
        <div class="list-empty-art" aria-hidden="true">${icon("shopping-cart")}</div>
        <h2 class="list-empty-title">Votre liste est vide</h2>
        <p>Ajoutez des articles à votre liste, puis comparez le prix du panier dans chaque enseigne.</p>
        <a class="btn-primary" href="#/liste">Ajouter des articles</a>
    </div>`;
}

function mainMarkup() {
    const view = buildView();
    if (!view) {
        if (!state.list.length) return html`${topMarkup(null)}${emptyMarkup()}`;
        return html`${topMarkup(null)}<p class="muted" data-key="wait"><span class="spinner" aria-hidden="true"></span> Chargement du dernier panier…</p>`;
    }
    const c = view.comparison;
    const cards = view.live
        ? view.stores.map((s) => liveStoreCard(view, s, run.storeStates[s.store]))
        : c.stores.map((s) => storeCard(c, s));
    return html`${topMarkup(view)}${statusMarkup()}
        <div class="basket-summary" data-key="summary" data-patch>
            <div class="verdict-box" data-key="verdict">${view.live ? waitingVerdict() : verdictMarkup(c)}</div>
            <ul class="store-cards" data-key="cards" data-patch data-testid="store-cards" aria-label="Paniers par enseigne">${cards}</ul>
        </div>
        ${!view.live ? html`<div class="plans-box" data-key="plans">${plansMarkup(c, view.items)}</div>` : ""}
        <section class="basket-detail" data-key="detail" data-patch aria-labelledby="detail-title" data-testid="basket-detail">
            <h2 id="detail-title" class="basket-h2" data-key="title">Prix par article</h2>
            <div class="detail-table" data-key="table" data-patch>${tableMarkup(view)}</div>
            <div class="detail-cards" data-key="cards" data-patch>${itemCardsMarkup(view)}</div>
            <p class="basket-legend" data-key="legend">${icon("star")} votre choix · prix en vert : le moins cher de l'article · « Changer » pour prendre un autre produit.</p>
            ${skippedMarkup(c)}
        </section>`;
}

function draw() {
    frame = 0;
    const main = root && root.querySelector(".basket-main");
    if (main) patch(main, mainMarkup());
}

function schedule() {
    if (!frame) frame = requestAnimationFrame(draw);
}

// ---------------------------------------------------------------- settings of the basket

const PREFS = html`<details class="basket-prefs" data-testid="basket-prefs">
    <summary>Réglages du panier</summary>
    <form class="prefs-form" data-prefs>
        <div class="field">
            <label for="pref-saving">Proposer un deuxième magasin s'il fait économiser au moins (€)</label>
            <input id="pref-saving" name="min_saving" type="number" min="0" max="100" step="0.5" inputmode="decimal">
        </div>
        <div class="field">
            <label for="pref-weeks">Un prix saisi en magasin compte pendant (semaines)</label>
            <input id="pref-weeks" name="manual_weeks" type="number" min="1" max="52" step="1" inputmode="numeric">
        </div>
        <button type="submit" class="btn-primary small">Enregistrer les réglages</button>
    </form>
</details>`;

async function loadPrefs(form) {
    try {
        const prefs = await api("/api/basket/prefs");
        form.min_saving.value = prefs.min_saving;
        form.manual_weeks.value = prefs.manual_weeks;
    } catch (err) {
        notify(err.message, { type: "error" });
    }
}

async function savePrefs(form) {
    const body = {
        min_saving: Math.max(0, Math.min(100, Number(String(form.min_saving.value).replace(",", ".")) || 0)),
        manual_weeks: Math.max(1, Math.min(52, Math.round(Number(form.manual_weeks.value) || 6))),
    };
    try {
        await api("/api/basket/prefs", { method: "PATCH", body });
        notify("Réglages du panier enregistrés");
        if (run.comparison && run.status !== "running") recompare();
    } catch (err) {
        notify(err.message, { type: "error" });
    }
}

// ---------------------------------------------------------------- events

function onRunChange(event) {
    if (event === "start" && run.items.length && !announcedStart) {
        announcedStart = true;
        announce(`Comparaison du panier : ${plural(run.items.length, "article")} dans ${plural(run.stores.length, "enseigne")}`);
    }
    if ((event === "done" || event === "updated") && run.comparison) {
        announcedStart = false;
        const v = verdict(run.comparison);
        // Not the words of the verdict shown (« Panier le moins cher »): said differently
        const what = v.kind === "best" ? `Le moins cher pour tout le panier : ${v.storeLabel}, ${v.value}.` : `${v.text}.`;
        announce(event === "done" ? `Comparaison terminée. ${what}` : `Panier mis à jour. ${what}`);
    }
    if (event === "stopped") announce("Comparaison arrêtée");
    schedule();
}

async function onClick(e) {
    const t = e.target.closest("button");
    if (!t || !root || !root.contains(t)) return;
    const d = t.dataset;
    if ("stop" in d) stop();
    else if ("start" in d) compareNow();
    else if ("refresh" in d) compareNow({ refresh: true });
    else if (d.retry) compareNow();
    else if (d.setup) await openSite(d.setup);
    else if (d.change) {
        const view = buildView();
        const id = Number(d.change);
        const item = view && view.items.find((i) => i.id === id);
        if (!item) return;
        openChangeSheet({ item, store: d.store, label: retailer(d.store).label, line: view.cell(d.store, id), manual: d.mode === "manual" });
    }
}

// A store was chosen, or « J'ai terminé » after an anti-robot check: compare
// again when a retailer that could not be searched may now answer
function retryUnchecked(afterSetup = false) {
    const c = run.comparison;
    if (!root || run.status !== "done" || !c || c.outdated) return;
    const ready = c.stores.some(
        (s) =>
            s.status === "unchecked" &&
            (s.action === "choose_store" ? Boolean(retailer(s.store).store) : afterSetup && s.action === "unblock"),
    );
    if (ready) compareNow();
}

// The list changed (here or on another device): is the comparison outdated?
function checkOutdated() {
    clearTimeout(checkTimer);
    checkTimer = setTimeout(async () => {
        if (!root || run.status !== "done" || run.updating || !run.comparison) return;
        try {
            const last = await api("/api/basket/last");
            const c = run.comparison;
            if (last && c && last.created_at === c.created_at && last.outdated !== c.outdated) {
                c.outdated = last.outdated;
                schedule();
            }
        } catch {
            /* next time */
        }
    }, 400);
}

// ---------------------------------------------------------------- view

export async function render(container) {
    root = container;
    setHtml(root, html`<div class="basket-page" data-testid="basket-page"><div class="basket-main"></div>${PREFS}</div>`);
    draw();
    root.addEventListener("click", onClick);
    const form = root.querySelector("[data-prefs]");
    root.querySelector(".basket-prefs").addEventListener("toggle", (e) => {
        if (e.target.open) loadPrefs(form);
    });
    form.addEventListener("submit", (e) => {
        e.preventDefault();
        savePrefs(form);
    });
    cleanups = [
        subscribe(onRunChange),
        on("list:changed", () => {
            checkOutdated();
            schedule();
        }),
        on("filters:changed", schedule),
        on("results:stale", () => retryUnchecked(true)),
        watchList(),
    ];
    if (run.status === "idle" && !run.comparison) {
        await loadLast();
        if (!root) return;
        if (!run.comparison && run.status === "idle" && state.list.some((i) => i.compare)) compareNow();
    } else if (run.status === "done" && !run.updating) {
        checkOutdated();
    }
    retryUnchecked();
    schedule();
}

export function destroy() {
    cleanups.forEach((off) => off());
    cleanups = [];
    clearTimeout(checkTimer);
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    root = null;
}
