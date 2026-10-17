// Settings › Navigateur: visible browser window, Intermarché window, troubleshooting (area of P3).

import { api } from "../../../core/api.js";
import { html, setHtml } from "../../../core/html.js";
import { on, openSetup, setBrowser, setSettings, state } from "../../../core/store.js";
import { announce, confirmDialog, notify } from "../../../core/ui.js";

export const id = "advanced";
export const title = "Navigateur";
export const order = 40;
export const enabled = true;

const BROWSER_NAMES = { chrome: "Google Chrome", msedge: "Microsoft Edge", chromium: "Chromium" };

// Finger-sized targets: at least 44 px (--control-h is only 41.6 px at the default text size)
const TARGET = "max(44px, var(--control-h))";

// Through the CSSOM: this section has no stylesheet of its own
function fingerSized(el, { inline = false } = {}) {
    el.style.minHeight = TARGET;
    if (inline) {
        el.style.display = "inline-flex";
        el.style.alignItems = "center";
    }
}

// 1791661200 → "15 h 40" (today), "demain à 1 h 10", "le 12/10 à 9 h 05"
export function clockText(ts, now = Date.now()) {
    const when = new Date(Number(ts) * 1000);
    const clock = `${when.getHours()} h ${String(when.getMinutes()).padStart(2, "0")}`;
    const day = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const days = Math.round((day(when) - day(new Date(now))) / 86400000);
    if (days === 0) return clock;
    if (days === 1) return `demain à ${clock}`;
    const date = `${String(when.getDate()).padStart(2, "0")}/${String(when.getMonth() + 1).padStart(2, "0")}`;
    return `le ${date} à ${clock}`;
}

// State line of the shared browser
export function browserText(b) {
    if (!b) return "";
    if (b.error) return `Problème : ${b.error}`;
    if (b.closed_by_user) return "Vous avez fermé la fenêtre du navigateur : les recherches continuent sans fenêtre.";
    if (!b.running) return "Le navigateur démarrera à la première recherche.";
    const name = BROWSER_NAMES[b.channel] || "le navigateur";
    return b.headless ? `Navigateur actif (${name}, sans fenêtre).` : `Navigateur actif (${name}, fenêtre visible).`;
}

// "d'Intermarché", "de Lidl"
export function of(label) {
    return /^[aeiouyàâéèêîôû]/i.test(label) ? `d'${label}` : `de ${label}`;
}

// State line of the dedicated window of a retailer (Intermarché)
export function windowText(w, blockedUntil) {
    if (blockedUntil) {
        return `${w.label} bloque temporairement cette connexion : PrixMalin ne le contactera pas avant ${clockText(blockedUntil)}.`;
    }
    if (w.error) return w.error;
    if (w.running) return `La fenêtre ${w.browser || "Chrome"} ${of(w.label)} est ouverte.`;
    if (w.closed_by_user) return `Vous avez fermé la fenêtre ${of(w.label)} : elle se rouvrira, réduite, à la prochaine recherche.`;
    return `La fenêtre ${of(w.label)} s'ouvrira, réduite, à la prochaine recherche ${w.label}.`;
}

function setupLabel(r, windows) {
    return windows.some((w) => w.store === r.key) ? `Ouvrir ${r.label} (fenêtre Chrome)` : `Ouvrir ${r.label}`;
}

export function render(el) {
    setHtml(
        el,
        html`
        <label class="switch">
            <input type="checkbox" id="show-browser">
            <span>Montrer le navigateur de PrixMalin sur l'ordinateur pendant les recherches</span>
        </label>
        <p class="muted small">PrixMalin consulte les sites avec son propre navigateur. Ses cookies et vos choix de magasins sont conservés d'une fois sur l'autre. En cas de vérification anti-robot, ouvrez le site concerné et validez-la à la main une fois.</p>
        <p id="browser-status" class="muted small" data-testid="browser-status"></p>
        <div id="dedicated-windows" data-testid="dedicated-windows"></div>
        <details class="troubleshoot" data-testid="troubleshoot">
            <summary>Dépannage</summary>
            <p class="muted small">Ouvrez un site dans le navigateur de PrixMalin pour valider une vérification anti-robot ou choisir votre magasin, puis appuyez sur « J'ai terminé ».</p>
            <div class="retailer-actions" id="setup-links"></div>
            <p class="small"><a href="#/etat" data-status-link>État des enseignes</a></p>
        </details>`,
    );
    const checkbox = el.querySelector("#show-browser");
    fingerSized(checkbox.closest("label")); // the whole label toggles the switch
    const summary = el.querySelector("summary");
    fingerSized(summary);
    summary.style.paddingBlock = ".6rem";
    summary.style.cursor = "pointer";
    fingerSized(el.querySelector("[data-status-link]"), { inline: true });

    function renderSwitch() {
        if (state.settings) checkbox.checked = state.settings.show_browser;
    }

    function renderStatus() {
        const b = state.browser;
        el.querySelector("#browser-status").textContent = browserText(b);
        const windows = (b && b.windows) || [];
        const blocked = (b && b.blocked_until) || {};
        setHtml(
            el.querySelector("#dedicated-windows"),
            html`${windows.map(
                (w) => html`
                <div class="dedicated-window" data-window="${w.store}">
                    <p class="small"><strong>${w.label}</strong> utilise une fenêtre Chrome à part : laissez-la ouverte, vous pouvez la réduire.</p>
                    <p class="muted small" data-window-status>${windowText(w, blocked[w.store])}</p>
                    ${blocked[w.store] && html`<div class="retailer-actions"><button class="btn-ghost" type="button" data-unblock="${w.store}">Réessayer ${w.label} maintenant</button></div>`}
                </div>`,
            )}`,
        );
        setHtml(
            el.querySelector("#setup-links"),
            html`${state.retailers.map(
                (r) => html`<button class="btn-ghost" type="button" data-open="${r.key}">${setupLabel(r, windows)}</button>`,
            )}`,
        );
        for (const btn of el.querySelectorAll("#dedicated-windows button, #setup-links button")) {
            fingerSized(btn);
        }
    }

    checkbox.addEventListener("change", async (e) => {
        try {
            const settings = await api("/api/settings", { method: "PATCH", body: { show_browser: e.target.checked } });
            const browser = await api("/api/browser");
            setSettings(settings);
            setBrowser(browser);
        } catch (err) {
            e.target.checked = !e.target.checked;
            notify(err.message, { type: "error" });
        }
    });

    el.addEventListener("click", async (e) => {
        const btn = e.target.closest("button");
        if (!btn) return;
        if (btn.dataset.open) {
            await openSetup(btn.dataset.open);
        } else if (btn.dataset.unblock) {
            const key = btn.dataset.unblock;
            const label = (state.retailers.find((r) => r.key === key) || { label: key }).label;
            const ok = await confirmDialog({
                title: `Réessayer ${label}`,
                message:
                    "Ne le faites que si vous avez changé de connexion Internet ou attendu plusieurs heures : chaque essai pendant un blocage le prolonge.",
                confirmLabel: "Réessayer",
            });
            if (!ok) return;
            try {
                setBrowser(await api(`/api/browser/blocks/${encodeURIComponent(key)}`, { method: "DELETE" }));
                const text = `${label} sera de nouveau consulté à la prochaine recherche.`;
                announce(text);
                notify(text);
            } catch (err) {
                notify(err.message, { type: "error" });
            }
        }
    });

    renderSwitch();
    renderStatus();
    const offs = [
        on("settings:changed", () => {
            renderSwitch();
            renderStatus();
        }),
        on("browser:changed", renderStatus),
    ];
    return () => offs.forEach((off) => off());
}
