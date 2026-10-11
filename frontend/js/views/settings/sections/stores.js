// Settings › Enseignes: one row per retailer with its state, its main action,
// a menu « ⋯ » (Changer, Retirer, Ouvrir le site) and, for Intermarché and
// Courses U, the list of the nearest stores (area of P4).
//
// Courses U: the nearest store is chosen by itself once the postal code is
// saved (« Choisi automatiquement : Super U Roujan (≈ 2 km) · Changer »); the
// user may take another one in the list, on the site (« Ouvrir le site »,
// read back after « J'ai terminé ») or paste the address of its page.

import { retailerBadge } from "../../../components/retailer-badge.js";
import { api } from "../../../core/api.js";
import { plural } from "../../../core/fmt.js";
import { html, setHtml } from "../../../core/html.js";
import { icon } from "../../../core/icons.js";
import { currentRoute } from "../../../core/router.js";
import { emit, loadSettings, on, state } from "../../../core/store.js";
import { announce, notify } from "../../../core/ui.js";
import { autoPick, distanceText, FAR_KM, loadHealth, openSite, setupState, statePill } from "../../status/shared.js";

export const id = "stores";
export const title = "Enseignes";
export const order = 20;
export const enabled = true;

const PICKER_TITLE = {
    intermarche: "Magasins Intermarché les plus proches",
    coursesu: "Magasins Courses U les plus proches",
};

// Lists of stores, kept while the page is hidden: key → { open, status, stores, error }
const pickers = {};
// Address being typed in the Courses U field
let urlDraft = "";
// Retailer whose menu « ⋯ » is open
let openMenu = null;

// A new postal code: the lists are read again (an open list stays open)
on("location:changed", () => {
    for (const [key, p] of Object.entries(pickers)) {
        if (p.status === "loading") continue; // asked after the change
        p.status = "idle";
        p.stores = [];
        p.error = "";
        if (p.open) loadNearestStores(key);
    }
});

export function pickerOf(key) {
    if (!pickers[key]) pickers[key] = { open: false, status: "idle", stores: [], error: "", pending: null };
    return pickers[key];
}

// Loads the nearest stores of `key` (Intermarché or Courses U)
export function loadNearestStores(key, { refresh = false } = {}) {
    const picker = pickerOf(key);
    if (picker.status === "loading" && picker.pending) return picker.pending;
    picker.status = "loading";
    picker.error = "";
    emit("stores:picker", key);
    picker.pending = api(`/api/retailers/${key}/stores${refresh ? "?refresh=true" : ""}`, { timeout: 120000 })
        .then((stores) => {
            picker.stores = stores;
            picker.status = "done";
        })
        .catch((err) => {
            picker.stores = [];
            picker.status = "error";
            picker.error = err.message;
        })
        .then(() => {
            picker.pending = null;
            emit("stores:picker", key);
            return picker.stores;
        });
    return picker.pending;
}

// Saves `store` (an item of /api/retailers/{key}/stores) as the store of `key`
export async function chooseStore(key, store) {
    const body = { id: store.id || null, name: store.name, address: store.address || null };
    if (store.url) body.url = store.url;
    if (store.distance_km != null) body.distance_km = store.distance_km;
    const settings = await api(`/api/retailers/${key}/store`, { method: "PUT", body });
    await loadSettings();
    emit("results:stale");
    return settings;
}

// ---------------------------------------------------------------- markup

function storeLine(store) {
    const distance = distanceText(store);
    return html`<strong>✓ ${store.name || "Magasin choisi"}</strong>${distance && html` · ${distance}`}`;
}

function detail(r, setup) {
    if (r.national) return html`<p class="retailer-detail">Prix identiques partout en France</p>`;
    const lines = [];
    if (r.store) {
        if (r.key === "coursesu" && r.store.auto) {
            const distance = distanceText(r.store);
            lines.push(html`<p class="retailer-detail">Choisi automatiquement : <strong>${r.store.name}</strong>${distance && ` (${distance})`} ·
                <button type="button" class="link-btn" data-action="pick" aria-label="Changer le magasin ${r.label}">Changer</button></p>`);
        } else {
            lines.push(html`<p class="retailer-detail">${storeLine(r.store)}</p>`);
        }
        if (r.store.address) lines.push(html`<p class="retailer-address small muted">${r.store.address}</p>`);
    } else if (r.key === "coursesu") {
        lines.push(coursesuWithoutStore());
    } else if (r.key === "intermarche") {
        lines.push(html`<p class="retailer-detail muted">Les prix dépendent du magasin : choisissez le vôtre dans la liste.</p>`);
    } else {
        lines.push(html`<p class="retailer-detail muted">${r.store_hint}</p>`);
    }
    if (setup.kind === "check") {
        lines.push(
            html`<p class="retailer-detail warn-text">Le site demande une vérification anti-robot : ouvrez-le et validez-la une fois.</p>`,
        );
    }
    return lines;
}

function coursesuWithoutStore() {
    const settings = state.settings;
    if (!settings || !settings.location) {
        return html`<p class="retailer-detail muted">Indiquez votre code postal : PrixMalin choisira le magasin le plus proche.</p>`;
    }
    if (autoPick.status === "loading") {
        return html`<p class="retailer-detail"><span class="spinner"></span> Recherche du magasin Courses U le plus proche…</p>`;
    }
    const result = autoPick.result;
    if (result && result.message && result.status !== "chosen") {
        return html`<p class="retailer-detail warn-text">${result.message}</p>`;
    }
    return html`<p class="retailer-detail muted">Les prix dépendent du magasin : choisissez le vôtre.</p>`;
}

function mainAction(r, setup) {
    if (setup.kind === "store") {
        return html`<div class="retailer-main"><button type="button" class="btn-primary small" data-action="pick" aria-label="Choisir mon magasin ${r.label}">Choisir mon magasin</button></div>`;
    }
    if (setup.kind === "check") {
        return html`<div class="retailer-main"><button type="button" class="btn-primary small" data-action="setup" aria-label="Faire la vérification sur le site ${r.label}">Faire la vérification</button></div>`;
    }
    return "";
}

function menu(r, setup) {
    const items = [];
    if (r.finds_stores) {
        items.push(
            html`<button type="button" data-action="pick" aria-label="Changer de magasin ${r.label}">${icon("store")} Changer de magasin</button>`,
        );
    }
    if (r.store) {
        items.push(
            html`<button type="button" class="danger" data-action="remove" aria-label="Retirer le magasin ${r.label}">${icon("trash-2")} Retirer le magasin</button>`,
        );
    }
    items.push(
        html`<button type="button" data-action="setup" aria-label="Ouvrir le site ${r.label}">${icon("external-link")} Ouvrir le site</button>`,
    );
    items.push(
        html`<a href="#/etat" data-action="status" aria-label="Voir l'état de ${r.label}">${icon("info")} Voir l'état</a>`,
    );
    const open = openMenu === r.key;
    return html`
        <div class="menu-wrap">
            <button type="button" class="menu-btn" data-action="menu" aria-expanded="${open ? "true" : "false"}" aria-controls="menu-${r.key}" aria-label="Autres actions pour ${r.label}"><span aria-hidden="true">⋯</span></button>
            <div id="menu-${r.key}" class="retailer-menu"${open ? "" : html` hidden`}>${items}</div>
        </div>`;
}

function storeOption(store, index) {
    const distance = distanceText(store);
    const services = store.services || [];
    return html`
        <li><button type="button" class="store-option" data-action="choose" data-index="${index}">
            <span class="store-option-head"><strong>${store.name}</strong>${distance && html`<span class="store-option-distance">${distance}</span>`}</span>
            ${store.address && html`<span class="store-option-address">${store.address}</span>`}
            ${services.length > 0 && html`<span class="services">${services.map((s) => html`<span class="service">${s}</span>`)}</span>`}
        </button></li>`;
}

function picker(r) {
    const p = pickerOf(r.key);
    const parts = [html`<p class="picker-title">${PICKER_TITLE[r.key]}</p>`];
    if (p.status === "loading") {
        parts.push(
            html`<p class="small muted"><span class="spinner"></span> Recherche des magasins proches…</p>`,
        );
    } else if (p.status === "error") {
        parts.push(html`<p class="notice warn small">${p.error}</p>`);
    } else if (p.status === "done") {
        if (p.stores.length) {
            parts.push(html`<ul class="store-options">${p.stores.map((s, i) => storeOption(s, i))}</ul>`);
            const nearest = p.stores[0];
            if (r.key === "coursesu" && nearest.distance_km != null && nearest.distance_km > FAR_KM) {
                parts.push(html`<p class="small warn-text">Aucun drive Courses U à moins de ${FAR_KM} km.</p>`);
            }
        } else {
            parts.push(html`<p class="small muted">Aucun magasin trouvé autour de chez vous.</p>`);
        }
    }
    if (r.key === "coursesu") {
        parts.push(html`
            <details class="manual-url"${urlDraft ? html` open` : ""}>
                <summary>Saisir l'adresse à la main</summary>
                <form class="url-form" data-action="url">
                    <label class="field-label" for="coursesu-url">Autre magasin : collez l'adresse de sa page</label>
                    <div class="row">
                        <input id="coursesu-url" name="url" type="url" inputmode="url" placeholder="https://www.coursesu.com/drive-superu-…" value="${urlDraft}" aria-describedby="coursesu-url-help">
                        <button class="btn-primary small" type="submit">Enregistrer</button>
                    </div>
                    <p id="coursesu-url-help" class="small muted">Exemple : https://www.coursesu.com/drive-superu-roujan</p>
                </form>
            </details>
            <p class="small muted">Ou choisissez-le sur le site de Courses U avec « Ouvrir le site » dans le menu ⋯, puis appuyez sur « J'ai terminé ».</p>`);
    }
    parts.push(
        html`<button type="button" class="btn-ghost small" data-action="close" aria-label="Fermer la liste des magasins ${r.label}">Fermer la liste</button>`,
    );
    return html`<div class="store-picker" id="picker-${r.key}">${parts}</div>`;
}

function retailerRow(r) {
    const setup = setupState(r);
    return html`
        <div class="retailer-row-head">
            <div class="retailer-title">
                <h4 class="retailer-name" id="retailer-${r.key}-name">${retailerBadge(r.key, r.label)}</h4>
                ${statePill(setup.kind, setup.label)}
            </div>
            ${menu(r, setup)}
        </div>
        ${detail(r, setup)}
        ${mainAction(r, setup)}
        ${pickerOf(r.key).open && picker(r)}`;
}

// ---------------------------------------------------------------- section

export function render(el) {
    el.id = "retailer-settings";
    setHtml(
        el,
        html`<div class="retailer-rows"></div>
        <p class="settings-links small">
            <a href="#/etat">${icon("info")} État des enseignes et test de chaque site</a>
            <a href="#/bienvenue">${icon("refresh-cw")} Relancer l'assistant de premier lancement</a>
        </p>`,
    );
    const list = el.querySelector(".retailer-rows");
    // Markup of each row: unchanged data do not rebuild it (focus and typing are kept)
    const shown = {};

    function rowElement(key) {
        let row = list.querySelector(`[data-retailer="${CSS.escape(key)}"]`);
        if (!row) {
            row = document.createElement("article");
            row.className = "retailer-row";
            row.dataset.retailer = key;
            row.setAttribute("aria-labelledby", `retailer-${key}-name`);
            list.append(row);
        }
        return row;
    }

    function renderRows() {
        if (!state.settings) return;
        for (const r of state.retailers) {
            const markup = retailerRow(r);
            if (shown[r.key] === String(markup)) continue;
            const row = rowElement(r.key);
            const focused = row.contains(document.activeElement) ? focusKey(document.activeElement) : null;
            setHtml(row, markup);
            shown[r.key] = String(markup);
            if (focused) restoreFocus(row, focused);
        }
    }

    function closeMenus() {
        if (openMenu === null) return;
        openMenu = null;
        renderRows();
    }

    function toggleMenu(key) {
        openMenu = openMenu === key ? null : key;
        renderRows();
        if (openMenu) el.querySelector(`#menu-${CSS.escape(key)}`).querySelector("button, a").focus();
    }

    async function openPicker(key) {
        const r = state.retailers.find((x) => x.key === key);
        const p = pickerOf(key);
        p.open = true;
        renderRows();
        const location = state.settings.location;
        // Intermarché needs the coordinates of the town; Courses U can do with the postal code
        if (!location || (key === "intermarche" && location.lat == null)) {
            p.status = "error";
            p.error = "Indiquez d'abord votre code postal (section Localisation ci-dessus).";
            renderRows();
            return;
        }
        if (p.status !== "done" || !p.stores.length) await loadNearestStores(key);
        const first = el.querySelector(`#picker-${CSS.escape(key)} .store-option`);
        if (first) first.focus();
        const label = r ? r.label : "";
        announce(
            p.status === "done"
                ? plural(p.stores.length, `magasin ${label} proposé`, `magasins ${label} proposés`)
                : p.error || "Aucun magasin trouvé",
        );
    }

    async function afterChange(message) {
        notify(message);
        announce(message);
    }

    el.addEventListener("click", async (e) => {
        const target = e.target.closest("[data-action]");
        if (!target || target.tagName === "FORM") return;
        const row = target.closest("[data-retailer]");
        const key = row ? row.dataset.retailer : null;
        const r = state.retailers.find((x) => x.key === key);
        const action = target.dataset.action;
        if (action === "menu") {
            toggleMenu(key);
            return;
        }
        if (action !== "status") closeMenus();
        try {
            if (action === "pick") {
                await openPicker(key);
            } else if (action === "close") {
                pickerOf(key).open = false;
                renderRows();
                row.querySelector("[data-action=menu]").focus();
            } else if (action === "choose") {
                const store = pickerOf(key).stores[Number(target.dataset.index)];
                await chooseStore(key, store);
                pickerOf(key).open = false;
                renderRows();
                await afterChange(`Magasin ${r.label} : ${store.name}`);
                row.querySelector("[data-action=menu]").focus();
            } else if (action === "remove") {
                await api(`/api/retailers/${key}/store`, { method: "DELETE" });
                await loadSettings();
                emit("results:stale");
                await afterChange(`Magasin ${r.label} retiré`);
            } else if (action === "setup") {
                await openSite(key);
            }
        } catch (err) {
            notify(err.message, { type: "error" });
        }
    });

    el.addEventListener("input", (e) => {
        if (e.target.id === "coursesu-url") urlDraft = e.target.value;
    });

    el.addEventListener("submit", async (e) => {
        if (!e.target.matches("[data-action=url]")) return;
        e.preventDefault();
        const url = e.target.elements.url.value.trim();
        try {
            const settings = await api("/api/retailers/coursesu/store", { method: "PUT", body: { url } });
            urlDraft = "";
            pickerOf("coursesu").open = false;
            await loadSettings();
            emit("results:stale");
            await afterChange(`Magasin Courses U : ${settings.stores.coursesu.name}`);
        } catch (err) {
            notify(err.message, { type: "error" });
        }
    });

    // Escape closes the menu (focus back on its button); a click elsewhere too
    el.addEventListener("keydown", (e) => {
        if (e.key !== "Escape") return;
        if (openMenu === null) return;
        const key = openMenu;
        closeMenus();
        el.querySelector(`[data-retailer="${CSS.escape(key)}"] [data-action=menu]`).focus();
    });
    const outside = (e) => {
        if (!e.target.closest(".menu-wrap")) closeMenus();
    };
    document.addEventListener("click", outside);

    // #/reglages?enseigne=intermarche: the list of that retailer opens by itself
    function openFromRoute() {
        const route = currentRoute();
        const key = route && route.params.enseigne;
        const r = key && state.retailers.find((x) => x.key === key);
        if (r && r.finds_stores && !r.store && state.settings.location && !pickerOf(key).open) openPicker(key);
    }

    renderRows();
    loadHealth();
    if (state.settings) openFromRoute();
    const offs = [
        on("settings:changed", () => {
            renderRows();
            openFromRoute();
        }),
        on("status:changed", renderRows),
        on("coursesu:auto", renderRows),
        on("stores:picker", renderRows),
        on("route:changed", openFromRoute),
        on("browser:changed", () => {
            // After « J'ai terminé » the state of the sites may have changed
            if (state.browser && !state.browser.setup_mode) loadHealth();
        }),
    ];
    return () => {
        offs.forEach((off) => off());
        document.removeEventListener("click", outside);
        openMenu = null;
    };
}

// Key of the focused control, to focus it again after its row is rebuilt
function focusKey(element) {
    const target = element.closest("[data-action], input");
    if (!target) return null;
    if (target.id) return `#${CSS.escape(target.id)}`;
    const index = target.dataset.index;
    return `[data-action="${target.dataset.action}"]${index != null ? `[data-index="${index}"]` : ""}`;
}

function restoreFocus(row, selector) {
    const target = row.querySelector(selector);
    if (target) target.focus();
}
