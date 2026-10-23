// Sheet « Coller une liste » (B67): a list typed or pasted (from a note, a
// message…), read by the server (POST /api/list/parse: « 2 lait demi-écrémé »,
// « farine 1kg », « - beurre », « • œufs x12 »…), shown as a preview, then
// added in one go (POST /api/list/bulk, items already in the list are merged).

import { api } from "../../core/api.js";
import { plural } from "../../core/fmt.js";
import { html } from "../../core/html.js";
import { loadList } from "../../core/store.js";
import { notify } from "../../core/ui.js";
import { patch } from "../search/patch.js";
import { openSheet } from "./sheet.js";

const BODY = html`<form class="paste-form" data-paste-form>
    <div class="field">
        <label for="paste-text">Votre liste, un article par ligne</label>
        <textarea id="paste-text" name="text" rows="7" maxlength="20000" placeholder="2 lait demi-écrémé&#10;farine 1kg&#10;- beurre&#10;• œufs x12" aria-describedby="paste-help"></textarea>
    </div>
    <p class="field-help" id="paste-help">Les quantités (« 2 lait », « œufs x12 », « farine 1kg ») sont reconnues. Un article déjà dans votre liste voit sa quantité augmenter.</p>
    <div class="paste-preview" data-preview aria-live="polite"></div>
    <div class="sheet-buttons">
        <button type="button" class="btn-ghost" data-close>Annuler</button>
        <button type="submit" class="btn-primary" data-paste-submit disabled>Ajouter</button>
    </div>
</form>`;

function preview(lines, ignored) {
    if (!lines.length && !ignored.length) return html``;
    return html`${lines.length ? html`<h3 class="edit-sub" data-key="title">Aperçu : ${plural(lines.length, "article")}</h3>
        <ul class="paste-lines" data-key="lines">${lines.map(
            (l) => html`<li>
                <span class="paste-query">${l.query}</span>
                <span class="paste-meta">${[l.target ? `objectif ${l.target}` : l.quantity > 1 ? `× ${l.quantity}` : "", l.category].filter(Boolean).join(" · ")}</span>
                ${l.existing ? html`<span class="tag">déjà dans la liste</span>` : ""}
            </li>`,
        )}</ul>` : ""}
        ${ignored.length ? html`<p class="field-help paste-ignored" data-key="ignored">Non repris : ${ignored.join(", ")}. Écrivez le nom avec des lettres ou des chiffres.</p>` : ""}`;
}

export function openPasteSheet() {
    const sheet = openSheet({ id: "paste-sheet", title: "Coller une liste", body: BODY });
    const form = sheet.content.querySelector("form");
    const box = form.querySelector("[data-preview]");
    const submit = form.querySelector("[data-paste-submit]");
    let lines = [];
    let ignored = [];
    let timer = null;
    let token = 0;

    async function read() {
        const text = form.text.value;
        const mine = ++token;
        let read = [];
        if (text.trim()) {
            try {
                read = await api("/api/list/parse", { method: "POST", body: { text } });
            } catch (err) {
                notify(err.message, { type: "error" });
                return;
            }
        }
        if (mine !== token || !sheet.open) return;
        // The pieces the list would refuse are shown, never sent
        lines = read.filter((l) => !l.ignored);
        ignored = read.filter((l) => l.ignored).map((l) => l.query);
        patch(box, preview(lines, ignored));
        submit.disabled = !lines.length;
        submit.textContent = lines.length ? `Ajouter ${plural(lines.length, "article")}` : "Ajouter";
    }

    form.text.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(read, 250);
    });
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        clearTimeout(timer);
        await read();
        if (!lines.length) return;
        submit.disabled = true;
        try {
            const items = lines.map((l) => ({ query: l.query, quantity: l.quantity, target: l.target }));
            await api("/api/list/bulk", { method: "POST", body: { items } });
            await loadList();
            sheet.close();
            notify(`${plural(items.length, "article ajouté", "articles ajoutés")} à votre liste`);
        } catch (err) {
            notify(err.message, { type: "error" });
            submit.disabled = false;
        }
    });
    form.text.focus();
}
