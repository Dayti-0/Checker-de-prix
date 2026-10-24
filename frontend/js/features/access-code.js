// Access code of the phone (area of P7).
//
// A phone (or any device other than the PC) gets « 401 » from the API until
// it typed the 6-digit code shown on the PC (Réglages › Sécurité, and the
// black window of PrixMalin). On the first « api:unauthorized » this module
// opens a dialog that cannot be dismissed; once the code is accepted (POST
// /api/access, cookie valid one year) the page reloads.

import { api } from "../core/api.js";
import { on } from "../core/events.js";
import { html, setHtml } from "../core/html.js";
import { announce } from "../core/ui.js";

export const enabled = true;

let dialog = null;

// " 123 456 " → "123456"; "12a" → "12" (only the digits are kept)
export function normalizeCode(text) {
    return String(text ?? "").replace(/\D/g, "");
}

// Message under the field, or "" when the code can be sent
export function codeProblem(code) {
    if (code.length === 0) return "Saisissez le code à 6 chiffres affiché sur le PC.";
    if (code.length !== 6) return "Le code compte 6 chiffres.";
    return "";
}

function build() {
    const el = document.createElement("dialog");
    el.className = "access-dialog";
    el.setAttribute("aria-labelledby", "access-title");
    el.setAttribute("aria-describedby", "access-help");
    el.dataset.testid = "access-code";
    setHtml(
        el,
        html`
        <form class="access-form" novalidate>
            <h2 id="access-title" class="access-title">Code d'accès</h2>
            <p id="access-help" class="access-help">Pour utiliser PrixMalin sur cet appareil, saisissez le code à 6 chiffres affiché sur le PC : dans Réglages › Sécurité, ou dans la fenêtre noire de PrixMalin.</p>
            <label class="access-label" for="access-input">Code à 6 chiffres</label>
            <input id="access-input" class="access-input" name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="7" required aria-describedby="access-error">
            <p id="access-error" class="access-error" hidden></p>
            <button class="btn-primary access-submit" type="submit">Valider</button>
            <p class="access-note">Cet appareil restera autorisé pendant un an.</p>
        </form>`,
    );
    // Nothing works without the code: Échap does not close the dialog
    el.addEventListener("cancel", (e) => e.preventDefault());
    const form = el.querySelector("form");
    form.addEventListener("submit", (e) => {
        e.preventDefault();
        submit(form);
    });
    document.body.append(el);
    return el;
}

function showError(form, message) {
    const error = form.querySelector("#access-error");
    const input = form.elements.code;
    error.textContent = message;
    error.hidden = !message;
    input.setAttribute("aria-invalid", message ? "true" : "false");
    if (message) announce(message);
}

async function submit(form) {
    const input = form.elements.code;
    const button = form.querySelector("button[type=submit]");
    const code = normalizeCode(input.value);
    const problem = codeProblem(code);
    if (problem) {
        showError(form, problem);
        input.focus();
        return;
    }
    button.disabled = true;
    try {
        await api("/api/access", { method: "POST", body: { code } });
        showError(form, "");
        announce("Code accepté. Chargement de PrixMalin…");
        window.location.reload();
    } catch (err) {
        showError(form, err.message);
        input.select();
        button.disabled = false;
    }
}

export function show() {
    if (!dialog) dialog = build();
    if (dialog.open) return;
    dialog.showModal();
    dialog.querySelector("input").focus();
}

export function init() {
    on("api:unauthorized", show);
}
