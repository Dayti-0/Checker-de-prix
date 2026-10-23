// Settings › À propos: version, updates, how to update (area of P7).
//
// GET /api/updates gives the version and the last check (no request to
// GitHub); « Vérifier maintenant » asks GitHub (POST /api/updates/check);
// the switch turns the daily check on or off (PATCH /api/updates).

import { api } from "../../../core/api.js";
import { relativeTime } from "../../../core/fmt.js";
import { attr, html, safeUrl, setHtml } from "../../../core/html.js";
import { announce, notify } from "../../../core/ui.js";
import { showUpdate } from "../../../features/update-banner.js";

export const id = "about";
export const title = "À propos";
export const order = 80;
export const enabled = true;

export const REPO_URL = "https://github.com/Dayti-0/Checker-de-prix";

// "Vous avez la dernière version (vérifié il y a 2 h)."
export function updateText(s, now = Date.now()) {
    if (s.available) return `Nouvelle version ${s.latest} disponible (vous avez la ${s.current}).`;
    if (s.error) return `${s.error} Réessayez plus tard.`;
    if (!s.checked_at) return "Aucune vérification pour l'instant.";
    const when = relativeTime(s.checked_at, now);
    return s.latest ? `Vous avez la dernière version (vérifié ${when}).` : `Aucune version publiée pour l'instant (vérifié ${when}).`;
}

function view(s) {
    const notes = safeUrl(s.url);
    return html`
        <p class="small">Version <strong data-testid="app-version">${s.current}</strong></p>
        <p class="small" id="update-state" data-testid="update-state">${updateText(s)}</p>
        <div class="sys-actions">
            <button class="btn-ghost sys-target" type="button" data-action="check">Vérifier maintenant</button>
            ${s.available && notes && html`<a class="sys-target" href="${notes}" target="_blank" rel="noopener noreferrer">Nouveautés de la version ${s.latest} (nouvel onglet)</a>`}
        </div>
        <label class="switch sys-target">
            <input type="checkbox" id="auto-updates"${attr({ checked: s.enabled })}>
            <span>Rechercher une nouvelle version une fois par jour</span>
        </label>
        <div class="sys-block">
            <p class="sys-label">Mettre à jour PrixMalin</p>
            <ol class="sys-steps">
                <li>Fermez la fenêtre noire de PrixMalin.</li>
                <li>Dans le dossier de PrixMalin, double-cliquez sur <strong>mettre-a-jour.bat</strong>.</li>
                <li>PrixMalin redémarre tout seul. Vos réglages et votre liste sont gardés.</li>
            </ol>
        </div>
        <div class="sys-block">
            <p class="muted small">PrixMalin compare les prix affichés sur les sites des enseignes, pour un usage personnel. Les prix peuvent différer en magasin.</p>
            <p class="small"><a class="sys-target" href="${REPO_URL}" target="_blank" rel="noopener noreferrer">Code source et aide de PrixMalin (nouvel onglet)</a></p>
        </div>`;
}

export function render(el) {
    let alive = true;
    setHtml(el, html`<p class="muted small">Chargement…</p>`);

    function show(state) {
        if (alive) setHtml(el, view(state));
    }

    el.addEventListener("click", async (e) => {
        const btn = e.target.closest("button[data-action=check]");
        if (!btn) return;
        btn.disabled = true;
        btn.textContent = "Vérification…";
        try {
            const state = await api("/api/updates/check", { method: "POST", timeout: 20000 });
            show(state);
            el.querySelector("button[data-action=check]")?.focus();
            announce(updateText(state));
            if (state.available) showUpdate(state, { force: true });
        } catch (err) {
            notify(err.message, { type: "error" });
            btn.disabled = false;
            btn.textContent = "Vérifier maintenant";
        }
    });

    el.addEventListener("change", async (e) => {
        if (e.target.id !== "auto-updates") return;
        const checkbox = e.target;
        try {
            show(await api("/api/updates", { method: "PATCH", body: { enabled: checkbox.checked } }));
            el.querySelector("#auto-updates")?.focus();
            announce(checkbox.checked ? "Vérification quotidienne activée." : "Vérification quotidienne désactivée.");
        } catch (err) {
            checkbox.checked = !checkbox.checked;
            notify(err.message, { type: "error" });
        }
    });

    api("/api/updates")
        .then(show)
        .catch((err) => {
            if (alive) setHtml(el, html`<p class="notice warn">${err.message}</p>`);
        });
    return () => {
        alive = false;
    };
}
