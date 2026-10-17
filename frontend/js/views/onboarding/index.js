// #/bienvenue : first-launch assistant (area of P4, B54).
//
// Opens by itself once, when nothing is set yet (checkOnboarding(), called at
// startup by features/setup-banner.js); can be started again from Réglages.
// Three steps:
//   1. postal code, then town (the form of Réglages › Localisation);
//   2. the 3 nearest Intermarché and Courses U stores and E.Leclerc drives
//      (the retailers whose `finds_stores` is true), the nearest chosen
//      (a store already chosen stays proposed and checked: started again from
//      Réglages, the assistant never replaces it by itself);
//   3. a trial search « lait » showing the state of each retailer and how to
//      fix it.
// Then back to the home page. The end is saved in the preferences
// p4.onboarding (PATCH /api/settings/onboarding).

import { retailerBadge } from "../../components/retailer-badge.js";
import { api } from "../../core/api.js";
import { plural } from "../../core/fmt.js";
import { html, setHtml } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { navigate } from "../../core/router.js";
import { emit, loadSettings, on, state } from "../../core/store.js";
import { announce, notify } from "../../core/ui.js";
import { mountLocationForm } from "../settings/sections/location.js";
import { andList, distanceText, ofLabel, openSite, statePill, storeNoun, storeTitle } from "../status/shared.js";

export const enabled = true;
export const title = "Bienvenue";
export const shell = { search: false, filters: false };

export const STEPS = ["Votre commune", "Vos magasins", "Essai"];
export const TRIAL_QUERY = "lait";
// Stores proposed for each retailer
const PROPOSED = 3;
// Retailers whose stores PrixMalin lists (before /api/retailers is read: the usual ones)
const STORE_KEYS = ["intermarche", "coursesu", "leclerc"];

export function storeKeys(retailers = state.retailers) {
    const keys = (retailers || []).filter((r) => r.finds_stores).map((r) => r.key);
    return keys.length ? keys : STORE_KEYS;
}

function storeLabels() {
    return storeKeys().map((key) => {
        const r = (state.retailers || []).find((x) => x.key === key);
        return r ? r.label : key;
    });
}

let root = null;
let step = 1;
let cleanups = [];
// Step 2: { key: { status, stores, error, choice } } (choice: index or "")
let lists = {};
// Step 3: { key: StoreResult | "loading" | { status: "error", message } }
let trial = {};

// ---------------------------------------------------------------- startup

// Opens the assistant on the first launch (empty settings, never shown)
export async function checkOnboarding() {
    const hash = location.hash.replace(/^#\/?/, "");
    if (hash !== "") return;
    try {
        const status = await api("/api/settings/onboarding");
        if (status.needed && location.hash.replace(/^#\/?/, "") === "") {
            navigate("/bienvenue", {}, { replace: true });
        }
    } catch {
        /* the home page stays */
    }
}

// ---------------------------------------------------------------- markup

function stepper() {
    return html`<ol class="onb-steps" aria-label="Étapes de l'assistant">${STEPS.map(
        (label, i) =>
            html`<li class="${i + 1 === step ? "current" : i + 1 < step ? "done" : ""}"${i + 1 === step ? html` aria-current="step"` : ""}>
                <span class="onb-step-number" aria-hidden="true">${i + 1 < step ? icon("check") : String(i + 1)}</span>
                <span class="onb-step-label">${label}</span>
            </li>`,
    )}</ol>`;
}

function nav({ back = true, skip = null, next = "Continuer", nextDisabled = false } = {}) {
    return html`<div class="onb-nav">
        ${back && html`<button type="button" class="btn-ghost" data-action="back">${icon("arrow-left")} Retour</button>`}
        <span class="onb-nav-space"></span>
        ${skip && html`<button type="button" class="btn-ghost" data-action="skip">${skip}</button>`}
        <button type="button" class="btn-primary" data-action="next"${nextDisabled ? html` disabled` : ""}>${next}</button>
    </div>`;
}

function stepTitle() {
    return `Étape ${step} sur ${STEPS.length} : ${STEPS[step - 1].toLowerCase()}`;
}

function storeChoices(key) {
    const r = state.retailers.find((x) => x.key === key) || { key, label: key };
    const list = lists[key] || { status: "loading" };
    let body;
    if (list.status === "loading") {
        body = html`<p class="muted"><span class="spinner"></span> Recherche des ${storeNoun(key)}s proches…</p>`;
    } else if (list.status === "error") {
        body = html`<p class="notice warn small">${list.error}</p>`;
    } else if (!list.stores.length) {
        body = html`<p class="muted">Aucun ${storeNoun(key)} trouvé autour de chez vous.</p>`;
    } else {
        body = html`${list.stores.map((s, i) => {
            const distance = distanceText(s);
            const services = s.services || [];
            // E.Leclerc: a pedestrian pick-up point is not a drive (never chosen automatically)
            const pickup = services.includes("Retrait piéton") && !services.includes("Drive");
            return html`<label class="onb-store">
                <input type="radio" name="onb-${key}" value="${i}"${list.choice === i ? html` checked` : ""}>
                <span class="onb-store-text"><strong>${s.name || "Magasin choisi"}</strong>${pickup && html` <span class="muted">· retrait piéton</span>`}${distance && html` <span class="muted">· ${distance}</span>`}
                    ${s.current && html` <span class="onb-store-tag">Magasin actuel</span>`}
                    ${s.address && html`<span class="onb-store-address">${s.address}</span>`}</span>
            </label>`;
        })}
        <label class="onb-store">
            <input type="radio" name="onb-${key}" value=""${list.choice === "" ? html` checked` : ""}>
            <span class="onb-store-text">Ne pas choisir maintenant</span>
        </label>`;
    }
    return html`<fieldset class="onb-stores" data-retailer="${key}">
        <legend>${retailerBadge(key, r.label)} <span>${storeTitle(key)}</span></legend>
        ${body}
    </fieldset>`;
}

const TRIAL_KIND = { ok: "ready", empty: "ready", store_required: "store", blocked: "check", timeout: "bad", error: "bad" };
const TRIAL_LABEL = {
    ok: "Prêt",
    empty: "Prêt",
    store_required: "Magasin à choisir",
    blocked: "Vérification requise",
    timeout: "Échec",
    error: "Échec",
};

function trialRow(r) {
    const result = trial[r.key];
    let pill = statePill("unknown", "En cours");
    let text = html`<span class="spinner"></span> Recherche…`;
    let fix = "";
    if (result && result !== "loading") {
        pill = statePill(TRIAL_KIND[result.status] || "bad", TRIAL_LABEL[result.status] || "Échec");
        if (result.status === "ok") {
            text = plural(result.products.length, "produit trouvé", "produits trouvés");
        } else if (result.status === "empty") {
            text = "Aucun produit";
        } else {
            text = result.message || "La recherche a échoué.";
        }
        if (result.status === "store_required") {
            fix = html`<button type="button" class="btn-ghost small" data-action="stores" aria-label="Choisir mon magasin ${r.label}">Choisir mon magasin</button>`;
        } else if (result.status === "blocked") {
            fix = html`<button type="button" class="btn-ghost small" data-action="setup" data-key="${r.key}" aria-label="Faire la vérification sur le site ${r.label}">Faire la vérification</button>`;
        }
    }
    return html`<li class="onb-trial-row" data-retailer="${r.key}">
        <span class="onb-trial-name">${retailerBadge(r.key, r.label)}</span>
        ${pill}
        <span class="onb-trial-text">${text}</span>
        ${fix}
    </li>`;
}

function stepBody() {
    if (step === 1) {
        return html`<p>Votre code postal sert à trouver les magasins ${andList(storeLabels())} les plus proches de chez vous. Aldi et Lidl ont les mêmes prix partout en France.</p>
            <div class="onb-location"></div>
            ${nav({ back: false, skip: "Passer", nextDisabled: !(state.settings && state.settings.location) })}`;
    }
    if (step === 2) {
        if (!state.settings || !state.settings.location) {
            return html`<p class="notice warn">Sans code postal, PrixMalin ne peut pas proposer de magasins. Revenez à l'étape précédente ou choisissez-les plus tard dans les réglages.</p>
                ${nav({ next: "Continuer" })}`;
        }
        const place = state.settings.location.city || state.settings.location.postal_code;
        const kept = storeKeys().some((key) => state.settings.stores && state.settings.stores[key]);
        const intro = kept
            ? `Voici les plus proches de ${place}. Un magasin déjà choisi reste coché ; sinon le plus proche est proposé.`
            : `Voici les plus proches de ${place} : le plus proche est déjà choisi.`;
        return html`<p>Les prix ${andList(storeLabels().map(ofLabel))} dépendent du magasin. ${intro}</p>
            <div class="onb-store-lists">${storeKeys().map(storeChoices)}</div>
            ${nav({ skip: "Passer", next: "Enregistrer et continuer" })}`;
    }
    const done = state.retailers.every((r) => trial[r.key] && trial[r.key] !== "loading");
    return html`<p>Recherche d'essai « ${TRIAL_QUERY} » dans chaque enseigne : vous voyez ce qui marche et ce qu'il reste à faire.</p>
        <ul class="onb-trial">${state.retailers.map(trialRow)}</ul>
        <p><button type="button" class="btn-ghost small" data-action="retry"${done ? "" : html` disabled`}>${icon("refresh-cw")} Relancer l'essai</button></p>
        ${nav({ next: "Terminer" })}`;
}

// ---------------------------------------------------------------- steps

function draw({ focus = false } = {}) {
    if (!root) return;
    cleanups.forEach((fn) => fn());
    cleanups = [];
    setHtml(
        root,
        html`<div class="onboarding">
            <h1 class="page-title">Bienvenue dans PrixMalin</h1>
            ${stepper()}
            <section class="onb-card" aria-labelledby="onb-step-title">
                <h2 id="onb-step-title" class="onb-title" tabindex="-1">${stepTitle()}</h2>
                ${stepBody()}
            </section>
        </div>`,
    );
    if (step === 1) {
        const box = root.querySelector(".onb-location");
        cleanups.push(mountLocationForm(box, { idPrefix: "onb" }));
        // « Continuer » is possible once the postal code is saved
        cleanups.push(
            on("settings:changed", () => {
                const next = root && root.querySelector("[data-action=next]");
                if (next) next.disabled = !(state.settings && state.settings.location);
            }),
        );
    }
    if (focus) {
        root.querySelector("#onb-step-title").focus();
        announce(stepTitle());
    }
}

function go(to) {
    step = Math.max(1, Math.min(STEPS.length, to));
    if (step === 2) loadLists();
    if (step === 3) runTrial();
    draw({ focus: true });
}

async function loadLists() {
    const location = state.settings && state.settings.location;
    if (!location) return;
    await Promise.all(
        storeKeys().map(async (key) => {
            const known = lists[key];
            if (known && known.status === "done" && known.postal === location.postal_code) return;
            lists[key] = { status: "loading", stores: [], choice: "" };
            if (key === "intermarche" && location.lat == null) {
                const error = "Commune introuvable : choisissez ce magasin plus tard dans les réglages.";
                lists[key] = { status: "error", stores: [], choice: "", error };
                return;
            }
            try {
                const nearest = await api(`/api/retailers/${key}/stores`, { timeout: 120000 });
                const current = state.settings.stores && state.settings.stores[key];
                const { stores, choice } = proposedStores(nearest, current);
                lists[key] = { status: "done", stores, postal: location.postal_code, choice };
            } catch (err) {
                lists[key] = { status: "error", stores: [], choice: "", error: err.message };
            }
            if (step === 2) drawLists();
        }),
    );
}

function sameStore(a, b) {
    if (!a || !b) return false;
    return a.url || b.url ? a.url === b.url : Boolean(a.id) && a.id === b.id;
}

// Stores proposed at step 2: the PROPOSED nearest, and the store chosen
// already (`current`) when it is not among them, first. `choice`: index of the
// store checked (the current one, else the nearest), "" without store.
export function proposedStores(nearest, current) {
    let stores = (nearest || []).slice(0, PROPOSED);
    const index = stores.findIndex((s) => sameStore(s, current));
    if (index >= 0) {
        stores = stores.map((s, i) => (i === index ? { ...s, current: true } : s));
        return { stores, choice: index };
    }
    if (current) {
        const known = (nearest || []).find((s) => sameStore(s, current));
        const store = { ...current, ...(known || {}), id: (known || current).id || "", current: true };
        return { stores: [store, ...stores], choice: 0 };
    }
    return { stores, choice: stores.length ? 0 : "" };
}

// Step 2: only the lists change (the focus stays where it is)
function drawLists() {
    const box = root && root.querySelector(".onb-store-lists");
    if (!box) return;
    const active = document.activeElement;
    const focused = active && box.contains(active) && active.name ? [active.name, active.value] : null;
    setHtml(box, html`${storeKeys().map(storeChoices)}`);
    if (focused) {
        const again = box.querySelector(`input[name="${CSS.escape(focused[0])}"][value="${CSS.escape(focused[1])}"]`);
        if (again) again.focus();
    }
}

async function saveStores() {
    let saved = 0;
    for (const key of storeKeys()) {
        const list = lists[key];
        if (!list || list.status !== "done" || list.choice === "") continue;
        const store = list.stores[list.choice];
        const current = state.settings.stores && state.settings.stores[key];
        // The store already chosen stays as it is (chosen automatically or not)
        if (sameStore(store, current)) continue;
        const body = { id: store.id || null, name: store.name, address: store.address || null };
        if (store.url) body.url = store.url;
        if (store.distance_km != null) body.distance_km = store.distance_km;
        await api(`/api/retailers/${key}/store`, { method: "PUT", body });
        saved += 1;
    }
    if (saved) {
        // Back at this step, the lists are read again (« Magasin actuel » moves)
        lists = {};
        await loadSettings();
        emit("results:stale");
    }
}

async function runTrial() {
    trial = {};
    for (const r of state.retailers) trial[r.key] = "loading";
    await Promise.all(
        state.retailers.map(async (r) => {
            try {
                const path = `/api/search/${r.key}?q=${encodeURIComponent(TRIAL_QUERY)}`;
                trial[r.key] = await api(path, { timeout: 120000 });
            } catch (err) {
                trial[r.key] = { status: "error", message: err.message };
            }
            if (step === 3) drawTrial();
        }),
    );
    if (step === 3) announce("Essai terminé");
}

// Step 3: only the rows change (the focus stays where it is)
function drawTrial() {
    const listEl = root && root.querySelector(".onb-trial");
    if (!listEl) return;
    setHtml(listEl, html`${state.retailers.map(trialRow)}`);
    const retry = root.querySelector("[data-action=retry]");
    if (retry) retry.disabled = !state.retailers.every((r) => trial[r.key] && trial[r.key] !== "loading");
}

async function finish() {
    try {
        await api("/api/settings/onboarding", { method: "PATCH", body: { done: true, seen: true } });
    } catch (err) {
        notify(err.message, { type: "error" });
    }
    notify("C'est prêt : tapez un produit pour comparer les prix.");
    navigate("/");
}

// ---------------------------------------------------------------- view

export function render(el) {
    root = el;
    step = 1;
    lists = {};
    trial = {};
    api("/api/settings/onboarding", { method: "PATCH", body: { seen: true } }).catch(() => {});
    draw();
    // Fresh settings (they may have been changed on another device)
    loadSettings().catch((err) => notify(err.message, { type: "error" }));

    el.addEventListener("change", (e) => {
        const input = e.target;
        if (input.type !== "radio" || !input.name.startsWith("onb-")) return;
        const key = input.name.slice(4);
        if (lists[key]) lists[key].choice = input.value === "" ? "" : Number(input.value);
    });

    el.addEventListener("click", async (e) => {
        const target = e.target.closest("[data-action]");
        if (!target || !root || !root.contains(target)) return;
        const action = target.dataset.action;
        if (action === "back") {
            go(step - 1);
        } else if (action === "skip") {
            go(step + 1);
        } else if (action === "next") {
            if (step === 2) {
                target.disabled = true;
                try {
                    await saveStores();
                } catch (err) {
                    notify(err.message, { type: "error" });
                    target.disabled = false;
                    return;
                }
            }
            if (step === STEPS.length) finish();
            else go(step + 1);
        } else if (action === "stores") {
            go(2);
        } else if (action === "setup") {
            openSite(target.dataset.key);
        } else if (action === "retry") {
            runTrial();
            drawTrial();
        }
    });
}

export function destroy() {
    cleanups.forEach((fn) => fn());
    cleanups = [];
    root = null;
}
