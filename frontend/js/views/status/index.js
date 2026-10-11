// #/etat : « État des enseignes » (area of P4, B55 and B56).
//
// One card per retailer (GET /api/status/retailers): its state, the last
// searches read on the site, the last error, the method used; « Tester »
// (a search « farine » read again on the site), « Voir la capture » (page
// saved when a search went wrong) and the action that fixes the state.
// « Télécharger le diagnostic » gives the report to send for help.

import { retailerBadge } from "../../components/retailer-badge.js";
import { api } from "../../core/api.js";
import { plural, relativeTime } from "../../core/fmt.js";
import { html, setHtml } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { on, retailer } from "../../core/store.js";
import { announce, notify } from "../../core/ui.js";
import { HEALTH_KIND, health, loadHealth, openSite, statePill } from "./shared.js";

export const enabled = true;
export const title = "État des enseignes";
export const shell = { search: false, filters: false };

export const TEST_QUERY = "farine";

// How each method reads the prices (BaseScraper.last_source)
export const SOURCE_LABELS = {
    api: "interface du site",
    html: "page de recherche",
    generic: "lecture de secours",
    "json-ld": "données de secours",
};

const STATE_HELP = {
    ok: "Les dernières recherches ont fonctionné.",
    degraded: "Les prix sont lus par une méthode de secours : certains produits peuvent manquer.",
    failing: "La dernière recherche a échoué. Testez de nouveau dans un instant.",
    broken: "Les 3 dernières recherches n'ont rien donné : le site a sans doute changé. Téléchargez le diagnostic pour le signaler.",
    blocked: "Le site demande une vérification anti-robot : faites-la une fois dans le navigateur PrixMalin.",
    store_required: "Les prix dépendent du magasin : choisissez le vôtre.",
    unknown: "Aucune recherche pour l'instant : appuyez sur « Tester ».",
};

// Results of « Tester », kept while the page is open: key → { status, text }
let tests = {};
let cleanup = null;

// « 2,3 s », « 850 ms »
export function duration(ms) {
    if (ms == null) return "";
    if (ms < 1000) return `${Math.round(ms)} ms`;
    return `${String(Math.round(ms / 100) / 10).replace(".", ",")} s`;
}

// « 80 % » of a share between 0 and 1
export function percent(rate) {
    return rate == null ? "" : `${Math.round(rate * 100)} %`;
}

// Text of the result of « Tester » (a StoreResult of /api/search/{key})
export function testText(result) {
    const time = duration(result.elapsed_ms);
    if (result.status === "ok") {
        const n = (result.products || []).length;
        return `${plural(n, "produit trouvé", "produits trouvés")} en ${time}`;
    }
    if (result.status === "empty") return `Aucun produit (${time})`;
    return result.message || "La recherche a échoué.";
}

function nameOf(h) {
    return h.label || retailer(h.key).label;
}

function facts(h) {
    const rows = [];
    if (h.store_name) rows.push(["Magasin", h.store_name]);
    rows.push(["Dernière recherche réussie", h.last_success ? relativeTime(h.last_success) : "aucune"]);
    if (h.searches_7d) {
        rows.push(["Réussite sur 7 jours", `${percent(h.success_rate_7d)} (${plural(h.searches_7d, "recherche")})`]);
    }
    if (h.consecutive_failures) rows.push(["Sans résultat d'affilée", plural(h.consecutive_failures, "recherche")]);
    if (h.last_source) {
        const fallback = h.primary_source && h.last_source !== h.primary_source;
        rows.push(["Méthode", `${SOURCE_LABELS[h.last_source] || h.last_source}${fallback ? " (secours)" : ""}`]);
    }
    if (h.avg_elapsed_ms) rows.push(["Durée moyenne", duration(h.avg_elapsed_ms)]);
    return html`<dl class="status-facts">${rows.map(([k, v]) => html`<div><dt>${k}</dt><dd>${v}</dd></div>`)}</dl>`;
}

function fixAction(h) {
    const name = nameOf(h);
    if (h.state === "store_required") {
        return html`<a class="btn-primary small" href="#/reglages?enseigne=${h.key}" aria-label="Choisir mon magasin ${name}">Choisir mon magasin</a>`;
    }
    if (h.state === "blocked") {
        return html`<button type="button" class="btn-primary small" data-action="setup" aria-label="Faire la vérification sur le site ${name}">Faire la vérification</button>`;
    }
    return "";
}

function snapshotLink(h) {
    const shot = (h.snapshots || [])[0];
    if (!shot) return "";
    const what = shot.kind === "png" ? "image" : "page";
    return html`<a class="btn-ghost small" href="/api/status/snapshot/${encodeURIComponent(shot.name)}" target="_blank" rel="noopener" aria-label="Voir la capture ${nameOf(h)} (${what} enregistrée ${relativeTime(shot.modified)})">${icon("eye")} Voir la capture</a>`;
}

function testResult(h) {
    const t = tests[h.key];
    if (!t) return "";
    if (t.status === "loading") {
        return html`<p class="status-test"><span class="spinner"></span> Recherche « ${TEST_QUERY} » en cours…</p>`;
    }
    const ok = t.status === "ok";
    return html`<p class="status-test ${ok ? "status-test-ok" : "status-test-bad"}">${icon(ok ? "circle-check" : "circle-alert")} Test « ${TEST_QUERY} » : ${t.text}</p>`;
}

function card(h) {
    const kind = HEALTH_KIND[h.state] || "unknown";
    const showError = h.last_error && h.state !== "ok" && h.state !== "store_required";
    const testing = tests[h.key] && tests[h.key].status === "loading";
    return html`
        <article class="status-card" data-retailer="${h.key}" aria-labelledby="status-${h.key}-name">
            <div class="status-card-head">
                <h2 class="status-name" id="status-${h.key}-name">${retailerBadge(h.key, nameOf(h))}</h2>
                ${statePill(kind, h.state_label)}
            </div>
            <p class="status-help">${h.national ? "Prix identiques partout en France. " : ""}${STATE_HELP[h.state] || ""}</p>
            ${facts(h)}
            ${showError && html`<p class="status-error"><strong>Dernière erreur :</strong> ${h.last_error}</p>`}
            ${testResult(h)}
            <div class="status-actions">
                ${fixAction(h)}
                <button type="button" class="btn-ghost small" data-action="test" aria-label="Tester ${nameOf(h)}"${testing ? html` disabled` : ""}>${icon("refresh-cw")} Tester</button>
                ${snapshotLink(h)}
            </div>
        </article>`;
}

export function render(el) {
    tests = {};
    setHtml(
        el,
        html`
        <div class="status-page">
            <h1 class="page-title">État des enseignes</h1>
            <p class="muted">Pour chaque site : les dernières recherches, la méthode utilisée et ce qu'il faut faire quand un site ne répond plus.</p>
            <div class="status-toolbar">
                <a class="btn-ghost small" href="/api/status/diagnostic.zip" download data-testid="diagnostic">${icon("download")} Télécharger le diagnostic</a>
                <button type="button" class="btn-ghost small" data-action="refresh">${icon("refresh-cw")} Actualiser</button>
                <a class="btn-ghost small" href="#/reglages">${icon("settings")} Réglages des enseignes</a>
            </div>
            <p class="small muted">Le diagnostic contient l'état des sites, les dernières recherches et les pages enregistrées, sans votre code postal ni vos magasins, et jamais les cookies du navigateur.</p>
            <div class="status-cards"></div>
        </div>`,
    );
    const list = el.querySelector(".status-cards");

    function renderCards() {
        if (health.error && !health.list) {
            setHtml(list, html`<p class="notice warn">${health.error}</p>`);
            return;
        }
        if (!health.list) {
            setHtml(list, html`<p class="muted"><span class="spinner"></span> Chargement…</p>`);
            return;
        }
        // The focused button is focused again once the cards are rebuilt
        const active = document.activeElement;
        const focus = active && list.contains(active) && active.dataset.action ? active : null;
        const focusCard = focus ? focus.closest("[data-retailer]").dataset.retailer : null;
        setHtml(list, html`${health.list.map(card)}`);
        if (focus) {
            const again = list.querySelector(
                `[data-retailer="${CSS.escape(focusCard)}"] [data-action="${CSS.escape(focus.dataset.action)}"]`,
            );
            if (again) again.focus();
        }
    }

    async function runTest(key) {
        const name = retailer(key).label;
        tests[key] = { status: "loading" };
        renderCards();
        announce(`Test de ${name} en cours`);
        try {
            const result = await api(`/api/search/${key}?q=${encodeURIComponent(TEST_QUERY)}&refresh=true`, {
                timeout: 120000,
            });
            tests[key] = { status: result.status, text: testText(result) };
        } catch (err) {
            tests[key] = { status: "error", text: err.message };
        }
        announce(`${name} : ${tests[key].text}`);
        await loadHealth();
    }

    el.addEventListener("click", (e) => {
        const target = e.target.closest("[data-action]");
        if (!target) return;
        const cardEl = target.closest("[data-retailer]");
        const key = cardEl ? cardEl.dataset.retailer : null;
        if (target.dataset.action === "test" && key) {
            runTest(key);
        } else if (target.dataset.action === "setup" && key) {
            openSite(key).catch((err) => notify(err.message, { type: "error" }));
        } else if (target.dataset.action === "refresh") {
            loadHealth().then(() => announce("État des enseignes actualisé"));
        }
    });

    renderCards();
    loadHealth();
    cleanup = on("status:changed", renderCards);
}

export function destroy() {
    if (cleanup) cleanup();
    cleanup = null;
}
