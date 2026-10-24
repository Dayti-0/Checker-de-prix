// Sheet « Partager ou imprimer » (B69): the list as text (GET /api/list/export),
// by aisle, or by retailer following the last basket (a plan or one retailer).
// The page is often opened in HTTP from a phone (no secure context): the
// share menu and the clipboard may be missing, the text is then selected in
// the box, and WhatsApp, SMS, the files and the printing always work.

import { api } from "../../core/api.js";
import { attr, html } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { notify } from "../../core/ui.js";
import { planAmountText, planTitle } from "../basket/model.js";
import { patch } from "../search/patch.js";
import { openSheet } from "./sheet.js";

// Ways of grouping the list, from the last basket: [{ value, label }]
export function groupings(comparison) {
    const out = [{ value: "", label: "Par rayon" }];
    if (!comparison || comparison.outdated) return out;
    // The title and the amount of the plan as the basket shows them
    (comparison.plans || []).forEach((plan, i) => {
        out.push({ value: `plan:${i}`, label: `${planTitle(plan)} (${planAmountText(plan)})` });
    });
    for (const store of comparison.stores || []) {
        if (store.ranked) out.push({ value: `store:${store.store}`, label: `Chez ${store.label}` });
    }
    return out;
}

// Query string of the export for a grouping value ("plan:0", "store:aldi" or "")
export function exportQuery(value, format = "txt", download = false) {
    const params = new URLSearchParams({ format });
    const [kind, key] = String(value || "").split(":");
    if (kind === "plan") params.set("plan", key);
    if (kind === "store") params.set("store", key);
    if (download) params.set("download", "true");
    return params.toString();
}

async function exportText(value) {
    const resp = await fetch(`/api/list/export?${exportQuery(value)}`, { headers: { "X-PrixMalin": "1" } });
    if (!resp.ok) throw new Error("La liste n'a pas pu être préparée. Réessayez dans un instant.");
    return resp.text();
}

function body(options, value, text) {
    const canShare = typeof navigator.share === "function";
    const message = encodeURIComponent(text || "");
    return html`<div class="share-body">
        ${
            options.length > 1
                ? html`<div class="field" data-key="by">
            <label for="share-by">Organiser la liste</label>
            <select id="share-by" name="by">${options.map((o) => html`<option value="${o.value}"${attr({ selected: o.value === value })}>${o.label}</option>`)}</select>
        </div>`
                : ""
        }
        <div class="field" data-key="text">
            <label for="share-text">Texte de la liste</label>
            <textarea id="share-text" class="share-text" rows="9" readonly>${text ?? "Préparation…"}</textarea>
        </div>
        <div class="share-actions" data-key="actions">
            ${canShare ? html`<button type="button" class="btn-primary" data-native>${icon("share-2")}Partager…</button>` : ""}
            <button type="button" class="btn-ghost" data-copy>Copier le texte</button>
            <a class="btn-ghost" href="https://wa.me/?text=${message}" target="_blank" rel="noopener noreferrer">WhatsApp</a>
            <a class="btn-ghost" href="sms:?&body=${message}">SMS</a>
        </div>
        <div class="share-actions" data-key="files">
            <a class="btn-ghost" href="/api/list/export?${exportQuery(value, "txt", true)}" download="ma-liste.txt">${icon("download")}Fichier texte</a>
            <a class="btn-ghost" href="/api/list/export?${exportQuery(value, "csv", true)}" download="ma-liste.csv">${icon("download")}Tableur (CSV)</a>
            <button type="button" class="btn-ghost" data-print>${icon("printer")}Imprimer</button>
        </div>
    </div>`;
}

export async function openShareSheet() {
    let options = groupings(null);
    let value = "";
    let text = null;
    const sheet = openSheet({ id: "share-sheet", title: "Partager ou imprimer", body: html`` });
    const draw = () => sheet.open && patch(sheet.content, body(options, value, text));
    draw();

    async function refresh() {
        try {
            text = await exportText(value);
        } catch (err) {
            text = "";
            notify(err.message, { type: "error" });
        }
        draw();
    }

    sheet.content.addEventListener("change", (e) => {
        if (e.target.name !== "by") return;
        value = e.target.value;
        text = null;
        draw();
        refresh();
    });
    sheet.content.addEventListener("click", async (e) => {
        const button = e.target.closest("button");
        if (!button || text == null) return;
        if ("native" in button.dataset) {
            try {
                await navigator.share({ title: "Ma liste de courses", text });
            } catch {
                /* cancelled by the user */
            }
        } else if ("copy" in button.dataset) {
            const box = sheet.content.querySelector("#share-text");
            if (navigator.clipboard && window.isSecureContext) {
                try {
                    await navigator.clipboard.writeText(text);
                    notify("Texte copié");
                    return;
                } catch {
                    /* below: the text is selected */
                }
            }
            box.focus();
            box.select();
            let copied = false;
            try {
                copied = document.execCommand("copy");
            } catch {
                copied = false;
            }
            notify(copied ? "Texte copié" : "Texte sélectionné : copiez-le avec un appui long ou Ctrl+C");
        } else if ("print" in button.dataset) {
            sheet.close();
            window.print();
        }
    });

    try {
        const last = await api("/api/basket/last");
        options = groupings(last);
    } catch {
        options = groupings(null);
    }
    draw();
    await refresh();
}
