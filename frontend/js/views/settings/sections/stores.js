// Settings › Enseignes: state of each retailer, store choice, « Ouvrir le site » (area of P4).

import { retailerBadge } from "../../../components/retailer-badge.js";
import { api } from "../../../core/api.js";
import { html, setHtml } from "../../../core/html.js";
import { emit, loadSettings, on, openSetup, state } from "../../../core/store.js";
import { notify } from "../../../core/ui.js";

export const id = "stores";
export const title = "Enseignes";
export const order = 20;
export const enabled = true;

// Intermarché stores found around the user: null, "loading" or a list
let intermarcheStores = null;
on("location:changed", () => {
    intermarcheStores = null;
});

function retailerCard(r) {
    const configured = Boolean(r.store);
    const status = r.needs_store
        ? configured
            ? html`<span class="state ok">✓ ${r.store.name || "Magasin choisi"}</span>`
            : html`<span class="state todo">Magasin à choisir</span>`
        : html`<span class="state ok">Prêt</span>`;
    let extra = "";
    if (r.key === "intermarche") {
        const stores = intermarcheStores;
        extra = html`
            ${configured && r.store.address && html`<p class="small muted">${r.store.address}</p>`}
            <div class="retailer-actions">
                <button class="btn-ghost small" type="button" data-find-stores>Trouver les magasins proches</button>
                ${configured && html`<button class="btn-ghost small danger" type="button" data-remove-store="intermarche">Retirer</button>`}
            </div>
            ${stores === "loading" && html`<p class="small muted"><span class="spinner"></span> Recherche des magasins…</p>`}
            ${Array.isArray(stores) && (stores.length ? html`<ul class="store-list">${stores.map((s) => html`
                <li><button type="button" data-pick-store="${s.id}">
                    <strong>${s.name}</strong>${s.distance_km != null && ` · ${String(s.distance_km).replace(".", ",")} km`}
                    ${s.address && html`<span class="addr">${s.address}</span>`}
                </button></li>`)}</ul>` : html`<p class="small muted">Aucun magasin trouvé autour de chez vous.</p>`)}`;
    } else if (r.key === "coursesu") {
        extra = html`
            <form class="row" data-coursesu-form>
                <input name="url" type="url" placeholder="https://www.coursesu.com/drive-superu-..." value="${configured && r.store.url ? r.store.url : ""}" aria-label="Adresse du magasin Courses U">
                <button class="btn-primary small" type="submit">Enregistrer</button>
            </form>
            ${configured && html`<div class="retailer-actions"><button class="btn-ghost small danger" type="button" data-remove-store="coursesu">Retirer</button></div>`}`;
    }
    return html`
        <div class="retailer-card" data-retailer="${r.key}">
            <div class="retailer-head">${retailerBadge(r.key, r.label)}${status}</div>
            <p class="small muted">${r.store_hint}</p>
            ${extra}
            <div class="retailer-actions"><button class="btn-ghost small" type="button" data-setup="${r.key}">Ouvrir le site</button></div>
        </div>`;
}

export function render(el) {
    el.id = "retailer-settings";
    // Last markup written: unchanged data do not rebuild the cards (and the
    // address being typed in the Courses U field is kept)
    let shown = null;

    function renderStores() {
        if (!state.settings) return;
        const markup = html`${state.retailers.map(retailerCard)}`;
        if (String(markup) !== shown) {
            setHtml(el, markup);
            shown = String(markup);
        }
    }

    // The store changed: reload the retailers and search again
    async function afterStoreChange(message) {
        await loadSettings();
        notify(message);
        emit("results:stale");
    }

    async function findIntermarcheStores() {
        if (!state.settings.location || state.settings.location.lat == null) {
            notify("Indiquez d'abord votre code postal", { type: "error" });
            return;
        }
        intermarcheStores = "loading";
        renderStores();
        try {
            intermarcheStores = await api("/api/retailers/intermarche/stores");
        } catch (err) {
            intermarcheStores = null;
            throw err;
        } finally {
            renderStores();
        }
    }

    el.addEventListener("click", async (e) => {
        const btn = e.target.closest("button");
        // The button of the Courses U form is handled by the "submit" listener
        if (!btn || btn.closest("form[data-coursesu-form]")) return;
        try {
            if (btn.hasAttribute("data-find-stores")) {
                await findIntermarcheStores();
            } else if (btn.dataset.pickStore) {
                const picked = intermarcheStores.find((s) => s.id === btn.dataset.pickStore);
                await api("/api/retailers/intermarche/store", {
                    method: "PUT",
                    body: { id: picked.id, name: picked.name, address: picked.address },
                });
                intermarcheStores = null;
                await afterStoreChange(`Magasin Intermarché : ${picked.name}`);
            } else if (btn.dataset.removeStore) {
                await api(`/api/retailers/${btn.dataset.removeStore}/store`, { method: "DELETE" });
                await afterStoreChange("Magasin retiré");
            } else if (btn.dataset.setup) {
                await openSetup(btn.dataset.setup);
            }
        } catch (err) {
            notify(err.message, { type: "error" });
        }
    });

    el.addEventListener("submit", async (e) => {
        if (!e.target.matches("[data-coursesu-form]")) return;
        e.preventDefault();
        const url = e.target.elements.url.value.trim();
        try {
            const settings = await api("/api/retailers/coursesu/store", { method: "PUT", body: { url } });
            await afterStoreChange(`Magasin Courses U : ${settings.stores.coursesu.name}`);
        } catch (err) {
            notify(err.message, { type: "error" });
        }
    });

    renderStores();
    const offs = [on("settings:changed", renderStores), on("location:changed", renderStores)];
    return () => offs.forEach((off) => off());
}
