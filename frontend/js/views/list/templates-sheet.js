// Sheet « Listes enregistrées » (B68): save the list under a name (« Courses de
// la semaine »: quantities, targets, choices…), then put it back in place of
// the list (« Annuler » for 6 s) or add its items to the list.
// API: GET/POST /api/templates, DELETE /api/templates/{id}, POST /api/templates/{id}/apply {mode}.

import { api } from "../../core/api.js";
import { plural, relativeTime } from "../../core/fmt.js";
import { html } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { loadList, state } from "../../core/store.js";
import { announce, notify } from "../../core/ui.js";
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
                <button type="button" class="icon-btn small" data-remove="${t.id}" aria-label="Supprimer la liste enregistrée ${t.name}" title="Supprimer">${icon("trash-2")}</button>
            </div>
        </li>`,
    )}</ul>`;
}

function body(templates) {
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
        <div class="template-box" data-key="box" data-patch>${savedList(templates)}</div>`;
}

export function openTemplatesSheet() {
    let templates = null;
    const sheet = openSheet({ id: "templates-sheet", title: "Listes enregistrées", body: html`` });
    const draw = () => sheet.open && patch(sheet.content, body(templates));
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

    sheet.content.addEventListener("submit", async (e) => {
        e.preventDefault();
        const name = e.target.name.value.trim();
        if (!name) return;
        try {
            const saved = await api("/api/templates", { method: "POST", body: { name } });
            e.target.name.value = "";
            notify(`Liste « ${saved.name} » enregistrée (${plural(saved.item_count, "article")})`);
            await load();
        } catch (err) {
            notify(err.message, { type: "error" });
        }
    });

    sheet.content.addEventListener("click", async (e) => {
        const button = e.target.closest("button");
        if (!button) return;
        const d = button.dataset;
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
                announce(`Liste « ${template.name} » supprimée`);
                sheet.content.querySelector("#template-name")?.focus();
                await load();
            }
        } catch (err) {
            notify(err.message, { type: "error" });
        }
    });

    load();
    const field = sheet.content.querySelector("#template-name");
    if (field && !field.disabled) field.focus();
}
