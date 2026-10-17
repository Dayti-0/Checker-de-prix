// #/courses : mode « En magasin » (area of P5, B64).
//
//   #/courses             choose: a plan of the last basket, a retailer, or the
//                         whole list by aisle
//   #/courses?plan=0      the plan « Aldi + Lidl »: by retailer, then by aisle
//   #/courses?store=aldi  at one retailer
//   #/courses?vue=liste   the whole list by aisle, without prices
//
// One big box per item (the whole row can be tapped), the product and the price
// retained by the basket; ticked items go to « Déjà pris », crossed out. A bar
// stuck at the bottom shows « 3/7 · 12,40 € » and « Terminer » (untick
// everything, or remove the items taken). Ticks work without network in an open
// tab (queue.js); the screen stays on when the browser allows it (wake lock).

import { retailerBadge } from "../../components/retailer-badge.js";
import { api } from "../../core/api.js";
import { euros, plural } from "../../core/fmt.js";
import { attr, html, setHtml } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { navigate } from "../../core/router.js";
import { on } from "../../core/store.js";
import { announce, notify } from "../../core/ui.js";
import { compareNow } from "../basket/runner.js";
import { readJson, restoreItems, writeJson } from "../list/data.js";
import { counterText } from "../list/model.js";
import { openSheet } from "../list/sheet.js";
import { watchList } from "../list/sync.js";
import { planTitle } from "../basket/model.js";
import { patch } from "../search/patch.js";
import { flush, pending, queueCheck } from "./queue.js";

export const enabled = true;
export const title = "En magasin";
export const shell = { search: false, filters: false };

const LAST_KEY = "prixmalin.trip";
const RETRY_MS = 5000;

let root = null;
let params = {};
let trip = null;
let last = undefined; // last basket for the chooser (undefined: not read yet)
let cleanups = [];
let retryTimer = null;
let wakeLock = null;
let offline = false;

// ---------------------------------------------------------------- data

function tripQuery(p) {
    const q = new URLSearchParams();
    if (p.plan !== undefined && p.plan !== "") q.set("plan", p.plan);
    else if (p.store) q.set("store", p.store);
    return q.toString();
}

function wantsTrip(p) {
    return (p.plan !== undefined && p.plan !== "") || Boolean(p.store) || p.vue === "liste";
}

// Ticks waiting for the network win over what the server said
function applyPending(t) {
    const waiting = new Map(pending().map((c) => [c.id, c.checked]));
    for (const s of t.stores) {
        for (const a of s.aisles) {
            for (const it of a.items) {
                if (waiting.has(it.item.id)) it.item.checked = waiting.get(it.item.id);
            }
        }
    }
    return t;
}

async function loadTrip() {
    try {
        const t = await api(`/api/list/trip?${tripQuery(params)}`);
        if (!root) return;
        trip = applyPending(t);
    } catch (err) {
        notify(err.message, { type: "error" });
    }
    draw();
}

function allItems(t) {
    return t ? t.stores.flatMap((s) => s.aisles.flatMap((a) => a.items)) : [];
}

// { count, checked, total, checkedTotal } of a part of the trip
function sums(items) {
    let total = 0;
    let checkedTotal = 0;
    let checked = 0;
    for (const it of items) {
        const amount = it.status === "found" && it.line_total != null ? it.line_total : 0;
        total += amount;
        if (it.item.checked) {
            checked += 1;
            checkedTotal += amount;
        }
    }
    return { count: items.length, checked, total: Math.round(total * 100) / 100, checkedTotal: Math.round(checkedTotal * 100) / 100 };
}

// ---------------------------------------------------------------- markup: chooser

function chooserMarkup() {
    const remembered = readJson(LAST_KEY, null);
    const c = last;
    let fromBasket;
    if (c === undefined) {
        fromBasket = html`<p class="muted"><span class="spinner" aria-hidden="true"></span> Lecture du dernier panier…</p>`;
    } else if (!c) {
        fromBasket = html`<div class="notice trip-note">
            <p>Comparez d'abord votre panier : la liste montrera alors le produit et le prix retenus dans chaque enseigne.</p>
            <div class="actions"><button type="button" class="btn-primary small" data-compare>Comparer mon panier</button></div>
        </div>`;
    } else {
        const ranked = c.stores.filter((s) => s.ranked);
        fromBasket = html`${c.outdated ? html`<div class="notice warn trip-note"><p>Votre liste a changé depuis la dernière comparaison : produits et prix peuvent ne plus correspondre.</p><div class="actions"><button type="button" class="btn-primary small" data-compare>Comparer à nouveau</button></div></div>` : ""}
            <h2 class="trip-h2">Suivre un plan du panier</h2>
            <ul class="trip-choices">${(c.plans || []).map(
                (plan, i) => html`<li><a class="trip-choice" href="#/courses?plan=${i}">
                    <span class="trip-choice-title">${planTitle(plan)}</span>
                    <span class="trip-choice-meta">${euros(plan.estimated ? plan.estimated_total : plan.total)}${plan.estimated ? " estimé" : ""} · ${plan.complete ? "tous les articles" : plural(plan.missing, "article introuvable", "articles introuvables")}</span>
                    ${icon("chevron-right")}
                </a></li>`,
            )}</ul>
            ${
                ranked.length
                    ? html`<h2 class="trip-h2">Ou une seule enseigne</h2>
            <ul class="trip-choices">${ranked.map(
                (s) => html`<li><a class="trip-choice" href="#/courses?store=${s.store}">
                    ${retailerBadge(s.store, s.label)}
                    <span class="trip-choice-meta">${s.found_count}/${plural(s.item_count, "article")} · ${euros(s.total)}</span>
                    ${icon("chevron-right")}
                </a></li>`,
            )}</ul>`
                    : ""
            }`;
    }
    return html`<div class="trip-page chooser" data-key="chooser" data-patch data-testid="trip-chooser">
        <h1 class="trip-title">En magasin</h1>
        <p class="trip-intro">Cochez les articles au fur et à mesure. Choisissez où vous faites vos courses : chaque article montre le produit et le prix retenus, rayon par rayon.</p>
        ${remembered && remembered.hash ? html`<p><a class="btn-primary" href="${remembered.hash}">${icon("list-checks")}Reprendre : ${remembered.label}</a></p>` : ""}
        ${fromBasket}
        <h2 class="trip-h2">Sans comparaison</h2>
        <ul class="trip-choices"><li><a class="trip-choice" href="#/courses?vue=liste">
            <span class="trip-choice-title">Ma liste par rayon</span>
            <span class="trip-choice-meta">sans produit ni prix</span>
            ${icon("chevron-right")}
        </a></li></ul>
    </div>`;
}

// ---------------------------------------------------------------- markup: the trip

function tripTitle(t) {
    if (t.plan !== null && t.plan !== undefined) {
        const names = t.stores.filter((s) => s.store).map((s) => s.label);
        return names.length > 1 ? names.join(" + ") : `Chez ${names[0] || "…"}`;
    }
    if (t.store) return `Chez ${(t.stores.find((s) => s.store === t.store) || t.stores[0] || { label: t.store }).label}`;
    return "Ma liste par rayon";
}

function row(it, storeLabel) {
    const item = it.item;
    const id = item.id;
    const qty = item.target ? `(${item.target})` : item.quantity > 1 ? `× ${item.quantity}` : "";
    const name = qty ? `${item.query} ${qty}` : item.query;
    let detail = "";
    if (it.status === "found" && it.product) {
        const packs = it.packs > 1 ? ` · ${it.packs} × ${euros(it.product.price)}` : "";
        detail = `${it.picked ? "★ " : ""}${it.product.name}${it.product.quantity_label ? ` (${it.product.quantity_label})` : ""}${packs}`;
    } else if (it.status === "not_found") {
        detail = `Introuvable chez ${storeLabel} : à chercher ailleurs`;
    } else if (it.status === "excluded") {
        detail = `Pas disponible chez ${storeLabel}`;
    } else if (it.status === "unchecked") {
        detail = "Prix pas encore lu";
    }
    const note = item.note ? item.note : "";
    const price = it.status === "found" && it.line_total != null ? euros(it.line_total) : "";
    return html`<li class="trip-row${item.checked ? " is-checked" : ""}" data-key="r-${id}">
        <label class="trip-check">
            <input type="checkbox" data-check="${id}" data-focus="check-${id}" aria-label="${name}"${detail || note ? attr({ "aria-describedby": `trip-d-${id}` }) : ""}${attr({ checked: item.checked })}>
            <span class="trip-box" aria-hidden="true">${icon("check")}</span>
            <span class="trip-text">
                <span class="trip-query">${item.query}${qty ? html` <span class="trip-qty">${qty}</span>` : ""}</span>
                ${detail || note ? html`<span class="trip-detail" id="trip-d-${id}">${detail}${detail && note ? " · " : ""}${note ? html`<em>${note}</em>` : ""}</span>` : ""}
            </span>
            ${price ? html`<span class="trip-price">${price}</span>` : ""}
        </label>
    </li>`;
}

function storeSection(s, many) {
    const items = s.aisles.flatMap((a) => a.items);
    const sum = sums(items);
    const label = s.label;
    const todo = s.aisles
        .map((a) => ({ name: a.name, items: a.items.filter((it) => !it.item.checked) }))
        .filter((a) => a.items.length);
    const done = items.filter((it) => it.item.checked);
    const id = `trip-${s.store || "autres"}`;
    return html`<section class="trip-store" data-key="s-${s.store || "other"}" data-patch aria-labelledby="${id}">
        ${
            many || s.store
                ? html`<h2 class="trip-store-head" id="${id}" data-key="head">${s.store ? retailerBadge(s.store, label) : html`<span>${label}</span>`}
                <span class="trip-store-sum">${sum.checked}/${sum.count}${sum.total ? ` · ${euros(sum.total)}` : ""}</span></h2>`
                : html`<h2 class="visually-hidden" id="${id}" data-key="head">${label}</h2>`
        }
        <div class="trip-aisles" data-key="todo" data-patch>${todo.map(
            (a) => html`<div class="trip-aisle" data-key="a-${a.name}" data-patch>
                <h3 class="trip-aisle-name" data-key="name">${a.name}</h3>
                <ul class="trip-rows" data-key="rows" data-patch>${a.items.map((it) => row(it, label))}</ul>
            </div>`,
        )}${!todo.length ? html`<p class="trip-all-done" data-key="all">${icon("circle-check")}Tout est pris ici.</p>` : ""}</div>
        ${
            done.length
                ? html`<div class="trip-aisle done" data-key="done" data-patch>
            <h3 class="trip-aisle-name" data-key="name">Déjà pris (${done.length})</h3>
            <ul class="trip-rows" data-key="rows" data-patch>${done.map((it) => row(it, label))}</ul>
        </div>`
                : ""
        }
    </section>`;
}

function tripMarkup() {
    if (!trip) {
        return html`<div class="trip-page" data-key="trip" data-patch data-testid="trip"><p class="muted" data-key="wait"><span class="spinner" aria-hidden="true"></span> Chargement de la liste…</p></div>`;
    }
    const items = allItems(trip);
    const sum = sums(items);
    const waiting = pending().length;
    const many = trip.stores.length > 1;
    return html`<div class="trip-page" data-key="trip" data-patch data-testid="trip">
        <div class="trip-top" data-key="top">
            <a class="btn-ghost small" href="#/courses">${icon("chevron-left")}Changer de magasin</a>
            <h1 class="trip-title">${tripTitle(trip)}</h1>
            ${trip.basket_at ? html`<p class="trip-sub">Produits et prix du panier comparé le ${new Date(trip.basket_at * 1000).toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}</p>` : ""}
        </div>
        ${trip.unknown ? html`<div class="notice warn trip-note" data-key="unknown"><p>Ce choix n'est plus dans le dernier panier : comparez à nouveau votre panier.</p><div class="actions"><button type="button" class="btn-primary small" data-compare>Comparer mon panier</button></div></div>` : ""}
        ${trip.outdated && !trip.unknown ? html`<div class="notice warn trip-note" data-key="outdated"><p>Votre liste a changé depuis la comparaison : produits et prix peuvent ne plus correspondre.</p><div class="actions"><button type="button" class="btn-primary small" data-compare>Comparer à nouveau</button></div></div>` : ""}
        ${offline || waiting ? html`<p class="notice warn trip-offline" data-key="offline" role="status">${icon("wifi-off")}Hors connexion : ${plural(waiting, "coche sera envoyée", "coches seront envoyées")} au retour du réseau.</p>` : ""}
        ${!items.length ? html`<div class="list-empty" data-key="empty"><h2 class="list-empty-title">Votre liste est vide</h2><a class="btn-primary" href="#/liste">Ajouter des articles</a></div>` : ""}
        <div class="trip-stores" data-key="stores" data-patch>${trip.stores.filter((s) => s.aisles.length).map((s) => storeSection(s, many))}</div>
        <div class="trip-bar" data-key="bar" data-testid="trip-bar">
            <p class="trip-counter"><strong>${counterText(sum.checked, sum.count, sum.checkedTotal)}</strong><span class="visually-hidden"> : ${plural(sum.checked, "article pris", "articles pris")} sur ${sum.count}</span>${sum.total ? html`<span class="trip-counter-sub">sur ${euros(sum.total)}</span>` : ""}</p>
            <button type="button" class="btn-primary" data-finish${attr({ disabled: !sum.checked })}>Terminer</button>
        </div>
    </div>`;
}

function draw() {
    if (!root) return;
    patch(root, wantsTrip(params) ? tripMarkup() : chooserMarkup());
}

// ---------------------------------------------------------------- ticks

async function sync() {
    const ok = await flush();
    offline = !ok;
    clearTimeout(retryTimer);
    if (!ok && root) retryTimer = setTimeout(sync, RETRY_MS);
    draw();
}

function toggle(id, checked) {
    const it = allItems(trip).find((x) => x.item.id === id);
    if (!it) return;
    it.item.checked = checked;
    queueCheck(id, checked);
    draw();
    const sum = sums(allItems(trip));
    announce(`${it.item.query} ${checked ? "pris" : "décoché"}, ${sum.checked} sur ${sum.count}`);
    sync();
}

function finishSheet() {
    const taken = allItems(trip).filter((it) => it.item.checked);
    const sheet = openSheet({
        id: "finish-sheet",
        title: "Terminer les courses",
        body: html`<p>${plural(taken.length, "article pris", "articles pris")} sur ${allItems(trip).length}.</p>
            <div class="finish-choices">
                <button type="button" class="btn-primary" data-mode="remove">Retirer ${taken.length >= 2 ? `les ${taken.length} articles pris` : "l'article pris"} de ma liste</button>
                <button type="button" class="btn-ghost" data-mode="uncheck">Tout décocher et garder la liste</button>
                <button type="button" class="btn-ghost" data-close>Continuer mes courses</button>
            </div>`,
    });
    sheet.content.addEventListener("click", async (e) => {
        const mode = e.target.closest("[data-mode]")?.dataset.mode;
        if (!mode) return;
        await flush();
        try {
            await api("/api/list/finish", { method: "POST", body: { mode } });
            sheet.close();
            if (mode === "remove") {
                const ids = taken.map((it) => it.item.id);
                notify(`${plural(ids.length, "article retiré", "articles retirés")} de votre liste`, {
                    action: { label: "Annuler", onClick: () => restoreItems(ids, "Articles remis dans votre liste").then(loadTrip) },
                    duration: 6000,
                });
            } else {
                notify("Tous les articles sont décochés");
            }
            await loadTrip();
        } catch (err) {
            notify(err.message, { type: "error" });
        }
    });
}

// ---------------------------------------------------------------- screen kept on

async function keepAwake() {
    if (!root || !wantsTrip(params) || !("wakeLock" in navigator) || document.visibilityState !== "visible") return;
    try {
        wakeLock = await navigator.wakeLock.request("screen");
    } catch {
        wakeLock = null; // refused (no secure context, battery saver…)
    }
}

function letSleep() {
    if (wakeLock) wakeLock.release().catch(() => {});
    wakeLock = null;
}

function onVisible() {
    if (document.visibilityState === "visible") {
        keepAwake();
        sync();
    }
}

// ---------------------------------------------------------------- view

function remember() {
    if (!trip || trip.unknown) return;
    writeJson(LAST_KEY, { hash: location.hash, label: tripTitle(trip) });
}

async function show(p) {
    params = p || {};
    trip = null;
    draw();
    if (wantsTrip(params)) {
        await sync();
        await loadTrip();
        remember();
        keepAwake();
    } else {
        letSleep();
        try {
            last = await api("/api/basket/last");
        } catch {
            last = null;
        }
        draw();
    }
}

function onClick(e) {
    const b = e.target.closest("button");
    if (!b || !root || !root.contains(b)) return;
    if ("finish" in b.dataset) finishSheet();
    else if ("compare" in b.dataset) {
        compareNow();
        navigate("/panier");
    }
}

function onChange(e) {
    const box = e.target.closest("[data-check]");
    if (box) toggle(Number(box.dataset.check), box.checked);
}

export function render(container, p) {
    root = container;
    setHtml(root, html``);
    root.addEventListener("click", onClick);
    root.addEventListener("change", onChange);
    document.documentElement.classList.add("has-trip-bar");
    const online = () => sync();
    window.addEventListener("online", online);
    document.addEventListener("visibilitychange", onVisible);
    cleanups = [
        () => window.removeEventListener("online", online),
        () => document.removeEventListener("visibilitychange", onVisible),
        on("api:online", online),
        on("list:changed", () => {
            if (wantsTrip(params) && !pending().length) loadTrip();
        }),
        watchList(),
    ];
    show(p);
}

export function update(p) {
    show(p);
}

export function destroy() {
    cleanups.forEach((off) => off());
    cleanups = [];
    clearTimeout(retryTimer);
    letSleep();
    document.documentElement.classList.remove("has-trip-bar");
    root = null;
    trip = null;
    last = undefined;
}

