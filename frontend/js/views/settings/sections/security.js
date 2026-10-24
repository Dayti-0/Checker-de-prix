// Settings › Sécurité: access from the phone and its access code (area of P7).
//
// On the PC: the switch « Autoriser l'accès depuis le téléphone » (takes
// effect at the next start), the 6-digit code to type once on each phone and
// « Changer le code » (every phone must type the new one). On a phone: a line
// that says it has access; these settings change on the PC only.

import { api } from "../../../core/api.js";
import { attr, html, setHtml } from "../../../core/html.js";
import { announce, confirmDialog, notify } from "../../../core/ui.js";

export const id = "security";
export const title = "Sécurité";
export const order = 50;
export const enabled = true;

// Text of the state of the network access
export function lanText(s) {
    if (s.forced_host) return `L'adresse d'écoute est fixée au lancement (${s.forced_host}) : ce réglage n'a pas d'effet.`;
    if (s.restart_needed) {
        return s.allow_lan
            ? "Le téléphone pourra se connecter au prochain démarrage de PrixMalin."
            : "Le téléphone ne pourra plus se connecter au prochain démarrage de PrixMalin. D'ici là, il est déjà refusé.";
    }
    return s.allow_lan
        ? "Un téléphone sur le même Wi-Fi peut ouvrir PrixMalin, avec le code ci-dessous."
        : "PrixMalin ne s'ouvre que sur ce PC.";
}

function body(s) {
    if (!s.local) {
        return html`<p class="small" data-testid="security-remote">Cet appareil a accès à PrixMalin. Le code d'accès et ces réglages se changent sur le PC.</p>`;
    }
    return html`
        <label class="switch sys-target">
            <input type="checkbox" id="allow-lan"${attr({ checked: s.allow_lan })}>
            <span>Autoriser l'accès depuis le téléphone</span>
        </label>
        <p class="muted small" id="lan-state" data-testid="lan-state">${lanText(s)}</p>
        ${s.allow_lan && html`
        <div class="sys-code-block">
            <p class="sys-label" id="access-code-label">Code d'accès du téléphone</p>
            <p class="sys-code" data-testid="access-code-value" aria-labelledby="access-code-label">${s.code}</p>
            <p class="muted small">À saisir une fois sur chaque téléphone ou tablette. Ne le montrez qu'aux personnes de confiance.</p>
            <button class="btn-ghost sys-target" type="button" data-action="new-code">Changer le code</button>
        </div>`}`;
}

export function render(el) {
    let alive = true;
    setHtml(el, html`<p class="muted small">Chargement…</p>`);

    function show(state) {
        if (!alive) return;
        setHtml(el, body(state));
    }

    async function load() {
        try {
            show(await api("/api/security"));
        } catch (err) {
            if (alive) setHtml(el, html`<p class="notice warn">${err.message}</p>`);
        }
    }

    el.addEventListener("change", async (e) => {
        if (e.target.id !== "allow-lan") return;
        const checkbox = e.target;
        try {
            const state = await api("/api/security", { method: "PATCH", body: { allow_lan: checkbox.checked } });
            show(state);
            el.querySelector("#allow-lan")?.focus();
            announce(lanText(state));
        } catch (err) {
            checkbox.checked = !checkbox.checked;
            notify(err.message, { type: "error" });
        }
    });

    el.addEventListener("click", async (e) => {
        const btn = e.target.closest("button[data-action=new-code]");
        if (!btn) return;
        const ok = await confirmDialog({
            title: "Changer le code d'accès",
            message: "Changer le code d'accès ? Les téléphones déjà autorisés devront saisir le nouveau code.",
            confirmLabel: "Changer le code",
        });
        if (!ok) return;
        try {
            const state = await api("/api/security/code", { method: "POST" });
            show(state);
            el.querySelector("button[data-action=new-code]")?.focus();
            const text = `Nouveau code d'accès : ${state.code}`;
            announce(text);
            notify(text);
        } catch (err) {
            notify(err.message, { type: "error" });
        }
    });

    load();
    return () => {
        alive = false;
    };
}
