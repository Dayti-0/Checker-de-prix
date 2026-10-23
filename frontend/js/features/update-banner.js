// « Nouvelle version disponible » (area of P7).
//
// At startup, GET /api/updates reads the result of the last check (PrixMalin
// asks GitHub at most once a day, never from this page). A newer version
// shows a banner under #setup-banner; « Plus tard » hides it for that version
// on this device (prixmalin.updateDismissed). Réglages › À propos calls
// showUpdate() after « Vérifier maintenant ».

import { api } from "../core/api.js";
import { html, safeUrl, setHtml } from "../core/html.js";

export const enabled = true;

const DISMISSED_KEY = "prixmalin.updateDismissed";

let banner = null;

export function shouldShow(state, dismissed) {
    return Boolean(state && state.available && state.latest && state.latest !== dismissed);
}

function dismissed() {
    try {
        return localStorage.getItem(DISMISSED_KEY);
    } catch {
        return null;
    }
}

function remember(version) {
    try {
        localStorage.setItem(DISMISSED_KEY, version);
    } catch {
        // private window: hidden for this page only
    }
}

export function hideUpdate() {
    if (banner) banner.remove();
    banner = null;
}

export function showUpdate(state, { force = false } = {}) {
    if (!force && !shouldShow(state, dismissed())) return;
    if (!state || !state.available) return hideUpdate();
    hideUpdate();
    banner = document.createElement("div");
    banner.className = "update-banner";
    banner.setAttribute("role", "status");
    banner.dataset.testid = "update-banner";
    const notes = safeUrl(state.url);
    setHtml(
        banner,
        html`
        <p>Nouvelle version ${state.latest} de PrixMalin disponible. Pour l'installer, fermez PrixMalin puis lancez <strong>mettre-a-jour.bat</strong> dans son dossier.</p>
        ${notes && html`<a class="sys-target" href="${notes}" target="_blank" rel="noopener noreferrer">Nouveautés de la version ${state.latest} (nouvel onglet)</a>`}
        <button class="btn-ghost small sys-target" type="button">Plus tard</button>`,
    );
    banner.querySelector("button").addEventListener("click", () => {
        remember(state.latest);
        hideUpdate();
    });
    const anchor = document.getElementById("setup-banner");
    if (anchor) anchor.after(banner);
    else document.body.prepend(banner);
}

export function init() {
    api("/api/updates")
        .then((state) => showUpdate(state))
        .catch(() => {
            // offline or code needed: nothing to show
        });
}
