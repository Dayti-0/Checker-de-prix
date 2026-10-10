// Settings › Navigateur: visible browser window, state of the browser (area of P3).

import { api } from "../../../core/api.js";
import { html, setHtml } from "../../../core/html.js";
import { on, setBrowser, setSettings, state } from "../../../core/store.js";
import { notify } from "../../../core/ui.js";

export const id = "advanced";
export const title = "Navigateur";
export const order = 40;
export const enabled = true;

export function render(el) {
    setHtml(
        el,
        html`
        <label class="switch">
            <input type="checkbox" id="show-browser">
            <span>Afficher la fenêtre du navigateur pendant les recherches</span>
        </label>
        <p class="muted small">PrixMalin consulte les sites avec son propre navigateur. Ses cookies et vos choix de magasins sont conservés d'une fois sur l'autre. En cas de vérification anti-robot, ouvrez le site concerné et validez-la à la main une fois.</p>
        <p id="browser-status" class="muted small"></p>`,
    );
    const checkbox = el.querySelector("#show-browser");

    function renderSwitch() {
        if (state.settings) checkbox.checked = state.settings.show_browser;
    }

    function renderStatus() {
        const b = state.browser;
        el.querySelector("#browser-status").textContent = b
            ? b.error
                ? `Problème : ${b.error}`
                : b.running
                  ? `Navigateur actif (${b.channel || "chromium"}, ${b.headless ? "invisible" : "visible"}).`
                  : "Le navigateur démarrera à la première recherche."
            : "";
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

    renderSwitch();
    renderStatus();
    const offs = [on("settings:changed", renderSwitch), on("browser:changed", renderStatus)];
    return () => offs.forEach((off) => off());
}
