// Settings › Localisation: postal code and town (area of P4).

import { api } from "../../../core/api.js";
import { html, setHtml } from "../../../core/html.js";
import { emit, on, setSettings, state } from "../../../core/store.js";
import { notify } from "../../../core/ui.js";

export const id = "location";
export const title = "Localisation";
export const order = 10;
export const enabled = true;

// Towns of the postal code to choose from, kept while the page is hidden
let communes = [];

export function render(el) {
    setHtml(
        el,
        html`
        <form id="location-form" class="row">
            <input id="postal-input" inputmode="numeric" pattern="[0-9]{5}" maxlength="5" placeholder="Code postal (ex : 34000)" aria-label="Code postal" required>
            <button class="btn-primary" type="submit">Valider</button>
        </form>
        <div id="commune-choice"></div>
        <p id="location-info" class="muted small"></p>`,
    );
    const input = el.querySelector("#postal-input");
    // Last value written: a refresh does not erase what the user is typing
    let shownPostal = null;

    function renderLocation() {
        if (!state.settings) return;
        const loc = state.settings.location;
        const postal = loc ? loc.postal_code : "";
        if (postal !== shownPostal) {
            input.value = postal;
            shownPostal = postal;
        }
        el.querySelector("#location-info").textContent = loc
            ? loc.lat != null
                ? `Localisation : ${loc.city || loc.postal_code}`
                : `Code postal ${loc.postal_code} enregistré (ville introuvable : la recherche de magasins Intermarché ne marchera pas).`
            : "Nécessaire pour trouver votre magasin Intermarché.";
    }

    function renderCommunes() {
        setHtml(
            el.querySelector("#commune-choice"),
            communes.length
                ? html`<div class="commune-list">${communes.map((c) => html`<button class="btn-ghost small" type="button" data-commune="${c.city}">${c.city}</button>`)}</div>`
                : html``,
        );
    }

    async function saveLocation(postalCode, city) {
        if (!/^\d{5}$/.test(postalCode)) {
            notify("Le code postal doit contenir 5 chiffres", { type: "error" });
            return;
        }
        try {
            const res = await api("/api/settings/location", { method: "POST", body: { postal_code: postalCode, city } });
            communes = res.communes.length > 1 && !city ? res.communes : [];
            renderCommunes();
            emit("location:changed", res.settings.location);
            setSettings(res.settings);
            notify(`Localisation enregistrée : ${res.settings.location.city || postalCode}`);
        } catch (err) {
            notify(err.message, { type: "error" });
        }
    }

    el.querySelector("#location-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        await saveLocation(input.value.trim());
    });
    el.querySelector("#commune-choice").addEventListener("click", (e) => {
        const btn = e.target.closest("[data-commune]");
        if (!btn) return;
        communes = [];
        renderCommunes();
        saveLocation(input.value.trim(), btn.dataset.commune);
    });

    renderLocation();
    renderCommunes();
    return on("settings:changed", renderLocation);
}
