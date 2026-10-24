// Sheet « Listes enregistrées » (B68): save the list under a name (« Courses de
// la semaine »: quantities, targets, choices…), then put it back in place of
// the list (« Annuler » for 6 s) or add its items to the list. A saved list of
// the same name is replaced only after a confirmation; a deleted one can be put
// back (« Annuler » for 6 s).
// API: GET/POST /api/templates {name, replace}, DELETE /api/templates/{id},
// POST /api/templates/restore {id}, POST /api/templates/{id}/apply {mode}.

import { api } from "../../core/api.js";
import { plural, relativeTime } from "../../core/fmt.js";
import { html } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { loadList, state } from "../../core/store.js";
import { confirmDialog, notify } from "../../core/ui.js";
import { patch } from "../search/patch.js";
import { restoreItems } from "./data.js";
import { openSheet } from "./sheet.js";

function savedList(templates) {
    if (templates === null) return html`<p class="muted" data-key="wait"><span class="spinner"></span> Chargement…</p>`;
    if (!templates.length) {
        return html`<p class="muted" data-key="none">Aucune liste enregistrée pour l'instant.</p>`;
    }
    return html`<ul class="template-list" data-key="list" data-patch>${templates.map(
        (t) => html`<li class="template" data-key="t-${t.id}">
            <div class="template-info">
                <strong class="template-name">${t.name}</strong>
                <span class="muted small">${plural(t.item_count, "article")} · enregistrée ${relativeTime(t.updated_at || t.created_at)}</span>
            </div>
            <div class="template-actions">
                <button type="button" class="btn-ghost small" data-apply="${t.id}" data-mode="replace" aria-label="Remplacer ma liste par ${t.name}">Remplacer ma liste</button>
                <button type="button" class="btn-ghost small" data-apply="${t.id}" data-mode="merge" aria-label="Ajouter ${t.name} à ma liste">Ajouter à ma liste</button>
            </div>
            <button type="button" class="icon-btn small template-remove" data-remove="${t.id}" aria-label="Supprimer la liste enregistrée ${t.name}" title="Supprimer">${icon("trash-2")}</button>
        </li>`,
    )}</ul>`;
}

// « Liste « … » supprimée [Annuler] », in the sheet (a toast under the sheet could not be reached)
function undoRow(removed) {
    if (!removed) return "";
    return html`<p class="template-undo" data-key="undo-${removed.id}" role="status">
        <span>Liste « ${removed.name} » supprimée</span>
        <button type="button" class="btn-ghost small" data-undo="${removed.id}" data-focus="undo-template" aria-label="Annuler la suppression de ${removed.name}">Annuler</button>
    </p>`;
}

function body(templates, removed = null) {
    const n = state.list.length;
    return html`<form class="template-save" data-key="save" data-template-form>
            <label for="template-name">Enregistrer ma liste actuelle${n ? ` (${plural(n, "article")})` : ""}</label>
            <div class="inline-field">
                <input id="template-name" name="name" maxlength="60" placeholder="Courses de la semaine" required${n ? "" : " disabled"}>
                <button type="submit" class="btn-primary"${n ? "" : " disabled"}>Enregistrer</button>
            </div>
            ${n ? "" : html`<p class="field-help">Votre liste est vide : ajoutez des articles pour l'enregistrer.</p>`}
        </form>
        <h3 class="edit-sub" data-key="title">Mes listes</h3>
        <div class="template-box" data-key="box" data-patch>${undoRow(removed)}${savedList(templates)}</div>`;
}

export function openTemplatesSheet() {
    let templates = null;
    // The saved list just deleted, offered back for 6 s
    let removed = null;
    let undoTimer = null;
    const sheet = openSheet({ id: "templates-sheet", title: "Listes enregistrées", body: html`` });
    const draw = () => sheet.open && patch(sheet.content, body(templates, removed));

    function forgetRemoved() {
        clearTimeout(undoTimer);
        const focused = document.activeElement && document.activeElement.matches("[data-undo]");
        removed = null;
        draw();
        if (focused) sheet.content.querySelector("#template-name")?.focus();
    }
    draw();

    async function load() {
        try {
            templates = await api("/api/templates");
        } catch (err) {
            templates = [];
            notify(err.message, { type: "error" });
        }
        draw();
    }

    // « Remplacer la liste enregistrée « Courses de la semaine » ? »
    function confirmReplace(name) {
        const n = state.list.length;
        return confirmDialog({
            title: "Remplacer la liste enregistrée",
            message: `Remplacer la liste enregistrée « ${name} » par votre liste actuelle (${plural(n, "article")}) ?`,
            confirmLabel: "Remplacer",
            danger: true,
        });
    }

    sheet.content.addEventListener("submit", async (e) => {
        e.preventDefault();
        const field = e.target.name;
        const name = field.value.trim();
        if (!name) return;
        // Same name in any case: asked before (the server refuses it otherwise)
        const same = (templates || []).find((t) => t.name.toLocaleLowerCase("fr") === name.toLocaleLowerCase("fr"));
        let replace = false;
        if (same) {
            if (!(await confirmReplace(same.name))) return field.focus();
            replace = true;
        }
        try {
            let saved;
            try {
                saved = await api("/api/templates", { method: "POST", body: { name, replace } });
            } catch (err) {
                // Saved meanwhile on another device
                if (err.code !== "template_exists" || !(await confirmReplace(name))) throw err;
                replace = true;
                saved = await api("/api/templates", { method: "POST", body: { name, replace } });
            }
            field.value = "";
            const what = replace ? "remplacée" : "enregistrée";
            notify(`Liste « ${saved.name} » ${what} (${plural(saved.item_count, "article")})`);
            await load();
        } catch (err) {
            notify(err.message, { type: "error" });
        }
    });

    sheet.content.addEventListener("click", async (e) => {
        const button = e.target.closest("button");
        if (!button) return;
        const d = button.dataset;
        if (d.undo && removed) {
            const back = removed;
            try {
                await api("/api/templates/restore", { method: "POST", body: { id: back.id } });
                forgetRemoved();
                await load();
                notify(`Liste « ${back.name} » rétablie`);
                sheet.content.querySelector("#template-name")?.focus();
            } catch (err) {
                forgetRemoved();
                notify(err.message, { type: "error" });
            }
            return;
        }
        const template = templates && templates.find((t) => String(t.id) === (d.apply || d.remove));
        if (!template) return;
        try {
            if (d.apply) {
                const before = state.list.map((i) => i.id);
                await api(`/api/templates/${template.id}/apply`, { method: "POST", body: { mode: d.mode } });
                await loadList();
                sheet.close();
                if (d.mode === "replace") {
                    const undo = before.length
                        ? {
                              label: "Annuler",
                              onClick: async () => {
                                  try {
                                      await api("/api/list", { method: "DELETE" });
                                      await restoreItems(before, "Liste précédente rétablie");
                                  } catch (err) {
                                      notify(err.message, { type: "error" });
                                  }
                              },
                          }
                        : null;
                    notify(`Votre liste est maintenant « ${template.name} »`, { action: undo, duration: 6000 });
                } else {
                    notify(`« ${template.name} » ajoutée à votre liste`);
                }
            } else if (d.remove) {
                await api(`/api/templates/${template.id}`, { method: "DELETE" });
                clearTimeout(undoTimer);
                removed = { id: template.id, name: template.name };
                await load();
                sheet.content.querySelector("[data-undo]")?.focus();
                undoTimer = setTimeout(forgetRemoved, 6000);
            }
        } catch (err) {
            notify(err.message, { type: "error" });
        }
    });

    load();
    const field = sheet.content.querySelector("#template-name");
    if (field && !field.disabled) field.focus();
}
