// Settings › Localisation: postal code and town (area of P4).
//
// mountLocationForm(el, { idPrefix, onSaved }) is also used by the assistant
// (#/bienvenue): postal code checked in the browser (5 digits), unknown
// postal code shown under the field, towns of the postal code as radio buttons.

import { api } from "../../../core/api.js";
import { html, setHtml } from "../../../core/html.js";
import { emit, on, setSettings, state } from "../../../core/store.js";
import { announce, notify } from "../../../core/ui.js";

export const id = "location";
export const title = "Localisation";
export const order = 10;
export const enabled = true;

export const POSTAL_MESSAGE = "Saisissez 5 chiffres, par ex. 34000";

// Towns of the last postal code saved, kept while the page is hidden
let communes = [];

// Fills `el` with the postal code form; returns the cleanup function
export function mountLocationForm(el, { idPrefix = "location", onSaved = null } = {}) {
    const ids = {
        input: `${idPrefix}-postal`,
        error: `${idPrefix}-postal-error`,
        info: `${idPrefix}-info`,
        towns: `${idPrefix}-towns-label`,
    };
    setHtml(
        el,
        html`
        <form class="location-form" novalidate>
            <label class="field-label" for="${ids.input}">Code postal</label>
            <div class="row">
                <input id="${ids.input}" name="postal" inputmode="numeric" autocomplete="postal-code" pattern="[0-9]{5}" maxlength="5" placeholder="34000" required aria-describedby="${ids.error} ${ids.info}">
                <button class="btn-primary" type="submit">Valider</button>
            </div>
            <p id="${ids.error}" class="field-error" hidden></p>
        </form>
        <div class="commune-choice" hidden>
            <p id="${ids.towns}" class="field-label">Votre commune</p>
            <div class="commune-list" role="radiogroup" aria-labelledby="${ids.towns}"></div>
        </div>
        <p id="${ids.info}" class="muted small location-info"></p>`,
    );
    const form = el.querySelector("form");
    const input = form.elements.postal;
    const error = el.querySelector(`#${ids.error}`);
    const choice = el.querySelector(".commune-choice");
    const group = el.querySelector(".commune-list");
    const info = el.querySelector(`#${ids.info}`);
    // Last value written: a refresh does not erase what the user is typing
    let shownPostal = null;
    let saveTimer = null;

    function showError(message) {
        error.textContent = message || "";
        error.hidden = !message;
        input.setAttribute("aria-invalid", message ? "true" : "false");
    }

    function renderLocation() {
        if (!state.settings) return;
        const loc = state.settings.location;
        const postal = loc ? loc.postal_code : "";
        if (postal !== shownPostal) {
            input.value = postal;
            shownPostal = postal;
        }
        info.textContent = loc
            ? loc.lat != null
                ? `Localisation : ${loc.city || loc.postal_code}`
                : `Code postal ${loc.postal_code} enregistré, commune introuvable pour l'instant : la recherche des magasins proches ne marchera pas.`
            : "Sert à trouver vos magasins Intermarché et Courses U les plus proches.";
        renderCommunes();
    }

    let shownTowns = null;

    function renderCommunes() {
        const loc = state.settings && state.settings.location;
        const towns = loc ? communes.filter((c) => c.postal_code === loc.postal_code) : [];
        choice.hidden = towns.length < 2;
        const checked = Math.max(
            0,
            towns.findIndex((c) => c.city === (loc && loc.city)),
        );
        const signature = towns.map((c) => c.city).join("|");
        if (signature === shownTowns) {
            // Same towns: only the choice changes (the focus stays where it is)
            group.querySelectorAll("[role=radio]").forEach((radio, i) => {
                radio.setAttribute("aria-checked", i === checked ? "true" : "false");
                radio.tabIndex = i === checked ? 0 : -1;
            });
            return;
        }
        shownTowns = signature;
        setHtml(
            group,
            html`${towns.map(
                (c, i) =>
                    html`<button type="button" role="radio" class="commune" data-commune="${c.city}" aria-checked="${i === checked ? "true" : "false"}" tabindex="${i === checked ? "0" : "-1"}">${c.city}</button>`,
            )}`,
        );
    }

    async function saveLocation(postalCode, city) {
        try {
            const res = await api("/api/settings/location", { method: "POST", body: { postal_code: postalCode, city } });
            showError("");
            if (!city) communes = res.communes;
            setSettings(res.settings);
            emit("location:changed", res.settings.location);
            if (res.geocoding_failed) {
                notify("Code postal enregistré, mais le service de localisation ne répond pas. Réessayez plus tard.", {
                    type: "error",
                });
            } else {
                notify(`Localisation enregistrée : ${res.settings.location.city || postalCode}`);
                if (!city && communes.length > 1) {
                    announce(`${communes.length} communes pour ce code postal : choisissez la vôtre.`);
                }
            }
            if (onSaved) onSaved(res);
        } catch (err) {
            if (err.status === 422) {
                showError(err.message);
                input.focus();
            } else {
                notify(err.message, { type: "error" });
            }
        }
    }

    function check() {
        input.setCustomValidity(/^\d{5}$/.test(input.value.trim()) ? "" : POSTAL_MESSAGE);
        return input.validity.valid;
    }

    input.addEventListener("input", () => {
        check();
        if (!error.hidden) showError("");
    });

    form.addEventListener("submit", (e) => {
        e.preventDefault();
        if (!check()) {
            showError(`${POSTAL_MESSAGE}.`);
            input.reportValidity();
            return;
        }
        saveLocation(input.value.trim());
    });

    function select(button, delay = 0) {
        for (const radio of group.querySelectorAll("[role=radio]")) {
            const checked = radio === button;
            radio.setAttribute("aria-checked", checked ? "true" : "false");
            radio.tabIndex = checked ? 0 : -1;
        }
        button.focus();
        clearTimeout(saveTimer);
        saveTimer = setTimeout(() => saveLocation(input.value.trim(), button.dataset.commune), delay);
    }

    group.addEventListener("click", (e) => {
        const button = e.target.closest("[role=radio]");
        if (button) select(button);
    });
    // Arrows move the choice (radio group); it is saved after a short pause
    group.addEventListener("keydown", (e) => {
        const radios = [...group.querySelectorAll("[role=radio]")];
        const index = radios.indexOf(document.activeElement);
        if (index < 0) return;
        const moves = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
        if (e.key in moves) {
            e.preventDefault();
            select(radios[(index + moves[e.key] + radios.length) % radios.length], 600);
        } else if (e.key === " " || e.key === "Enter") {
            e.preventDefault();
            select(radios[index]);
        }
    });

    renderLocation();
    const off = on("settings:changed", renderLocation);
    return () => {
        clearTimeout(saveTimer);
        off();
    };
}

export function render(el) {
    return mountLocationForm(el);
}
