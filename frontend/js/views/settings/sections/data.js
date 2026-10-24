// Settings › Mes données: backup file, restore, daily copies of the database (area of P7).
//
// « Enregistrer une sauvegarde » downloads GET /api/backup (settings, list…);
// « Restaurer » sends a backup file (POST /api/restore) to replace the data or
// to add what is missing (merge, the default). The daily copies of the
// database are made by PrixMalin itself (7 kept).

import { api } from "../../../core/api.js";
import { plural, relativeTime } from "../../../core/fmt.js";
import { html, setHtml } from "../../../core/html.js";
import { loadList, loadSettings } from "../../../core/store.js";
import { announce, confirmDialog, notify } from "../../../core/ui.js";

export const id = "data";
export const title = "Mes données";
export const order = 60;
export const enabled = true;

export const MAX_BYTES = 10 * 1024 * 1024;

// "PrixMalin copie aussi sa base chaque jour (7 copies gardées) : la dernière il y a 2 h."
export function copiesText(info, now = Date.now()) {
    if (!info || !info.count) return "PrixMalin copie aussi sa base chaque jour (7 copies gardées) : aucune copie pour l'instant.";
    return `PrixMalin copie aussi sa base chaque jour (${plural(info.keep, "copie gardée", "copies gardées")}) : la dernière ${relativeTime(info.last_at, now)}.`;
}

// Message after a restore
export function restoredText(result) {
    const done = result.mode === "merge" ? "Sauvegarde ajoutée à vos données." : "Sauvegarde restaurée.";
    return result.ignored && result.ignored.length
        ? `${done} ${plural(result.ignored.length, "partie inconnue de cette version a été ignorée", "parties inconnues de cette version ont été ignorées")}.`
        : done;
}

function view() {
    return html`
        <div class="sys-block">
            <p class="small">Enregistrez vos réglages et votre liste de courses dans un fichier, pour les garder de côté ou les remettre sur un autre PC.</p>
            <div class="sys-actions">
                <a class="btn-primary sys-target" href="/api/backup" download data-testid="backup-download">Enregistrer une sauvegarde</a>
            </div>
        </div>
        <form class="sys-block restore-form" novalidate data-testid="restore-form">
            <label class="sys-label" for="restore-file">Restaurer une sauvegarde</label>
            <div class="sys-file-row">
                <input id="restore-file" class="sys-file" name="file" type="file" accept=".json,application/json">
                <label class="btn-ghost sys-target sys-file-button" for="restore-file">Choisir un fichier</label>
                <span class="small sys-file-name" id="restore-name" data-testid="restore-name">Aucun fichier choisi</span>
            </div>
            <fieldset class="sys-modes">
                <legend>Vos données actuelles</legend>
                <label><input type="radio" name="mode" value="merge" checked> Les garder et ajouter ce qui manque</label>
                <label><input type="radio" name="mode" value="replace"> Les remplacer par la sauvegarde</label>
            </fieldset>
            <div class="sys-actions"><button class="btn-ghost sys-target" type="submit">Restaurer ce fichier</button></div>
            <p class="small" id="restore-result" data-testid="restore-result" hidden></p>
        </form>
        <div class="sys-block">
            <p class="muted small" id="copies-info" data-testid="copies-info"></p>
            <p class="muted small sys-path" id="data-dir" hidden></p>
        </div>`;
}

export function render(el) {
    let alive = true;
    setHtml(el, view());
    const form = el.querySelector("form");
    const result = el.querySelector("#restore-result");

    function say(message, { error = false } = {}) {
        result.textContent = message;
        result.hidden = !message;
        result.classList.toggle("access-error", error);
        if (message) announce(message);
    }

    async function loadInfo() {
        try {
            const info = await api("/api/backup/info");
            if (!alive) return;
            el.querySelector("#copies-info").textContent = copiesText(info);
            const dir = el.querySelector("#data-dir");
            dir.textContent = info.data_dir ? `Dossier des données : ${info.data_dir}` : "";
            dir.hidden = !info.data_dir;
        } catch {
            // the section stays usable without it
        }
    }

    // The button of the browser speaks its own language: a French one instead
    form.elements.file.addEventListener("change", () => {
        const file = form.elements.file.files[0];
        el.querySelector("#restore-name").textContent = file ? file.name : "Aucun fichier choisi";
        say("");
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const file = form.elements.file.files[0];
        const mode = form.elements.mode.value;
        if (!file) return say("Choisissez d'abord un fichier de sauvegarde.", { error: true });
        if (file.size > MAX_BYTES) return say("Ce fichier est trop gros pour une sauvegarde de PrixMalin.", { error: true });
        let backup;
        try {
            backup = JSON.parse(await file.text());
        } catch {
            return say("Ce fichier n'est pas une sauvegarde de PrixMalin.", { error: true });
        }
        if (mode === "replace") {
            const ok = await confirmDialog({
                title: "Remplacer vos données",
                message: "Remplacer vos réglages et votre liste actuels par ceux de la sauvegarde ?",
                confirmLabel: "Remplacer",
                danger: true,
            });
            if (!ok) return;
        }
        const button = form.querySelector("button[type=submit]");
        button.disabled = true;
        try {
            const answer = await api("/api/restore", { method: "POST", body: { mode, backup } });
            say(restoredText(answer));
            notify(restoredText(answer));
            await Promise.all([loadSettings(), loadList()]).catch(() => {});
            form.reset();
            el.querySelector("#restore-name").textContent = "Aucun fichier choisi";
        } catch (err) {
            say(err.message, { error: true });
        } finally {
            button.disabled = false;
        }
    });

    loadInfo();
    return () => {
        alive = false;
    };
}
