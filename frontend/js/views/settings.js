// #/reglages?enseigne=intermarche : location, store of each retailer, browser.
// `enseigne` scrolls to the card of that retailer.

import { api } from "../api.js";
import { retailerBadge } from "../components/retailerBadge.js";
import { loadSettings, notify, openSetup, setBrowser, setSettings, store, subscribe } from "../store.js";
import { escapeHtml, toast } from "../util.js";

// Kept while the view is hidden, like the old settings dialog
const local = { intermarcheStores: null, communes: [] };

let root = null;
let unsubscribers = [];
// Last values written in the page: a refresh of the data does not erase what
// the user is typing when nothing changed on the server
let shown = { postal: null, retailers: null };

const TEMPLATE = `
    <div class="settings-page">
        <h1 class="page-title">Réglages</h1>
        <section class="settings-section">
            <h3>Localisation</h3>
            <form id="location-form" class="row">
                <input id="postal-input" inputmode="numeric" pattern="[0-9]{5}" maxlength="5" placeholder="Code postal (ex : 34000)" aria-label="Code postal" required>
                <button class="btn-primary" type="submit">Valider</button>
            </form>
            <div id="commune-choice"></div>
            <p id="location-info" class="muted small"></p>
        </section>
        <section id="retailer-settings" class="settings-section"></section>
        <section class="settings-section">
            <h3>Navigateur</h3>
            <label class="switch">
                <input type="checkbox" id="show-browser">
                <span>Afficher la fenêtre du navigateur pendant les recherches</span>
            </label>
            <p class="muted small">PrixMalin consulte les sites avec son propre navigateur. Ses cookies et vos choix de magasins sont conservés d'une fois sur l'autre. En cas de vérification anti-robot, ouvrez le site concerné et validez-la à la main une fois.</p>
            <p id="browser-status" class="muted small"></p>
        </section>
    </div>`;

const $ = (sel) => (root ? root.querySelector(sel) : null);

// ---------------------------------------------------------------- rendering

function renderSettings() {
    if (!root || !store.settings) return;
    const loc = store.settings.location;
    const postal = loc ? loc.postal_code : "";
    if (postal !== shown.postal) {
        $("#postal-input").value = postal;
        shown.postal = postal;
    }
    $("#location-info").textContent = loc
        ? (loc.lat != null ? `Localisation : ${loc.city || loc.postal_code}` : `Code postal ${loc.postal_code} enregistré (ville introuvable : la recherche de magasins Intermarché ne marchera pas).`)
        : "Nécessaire pour trouver votre magasin Intermarché.";
    $("#show-browser").checked = store.settings.show_browser;

    const retailers = `<h3>Enseignes</h3>` + store.retailers.map(renderRetailerSettings).join("");
    if (retailers !== shown.retailers) {
        $("#retailer-settings").innerHTML = retailers;
        shown.retailers = retailers;
    }
    renderBrowserStatus();
}

function renderBrowserStatus() {
    if (!root) return;
    const b = store.browser;
    $("#browser-status").textContent = b
        ? (b.error ? `Problème : ${b.error}` : b.running ? `Navigateur actif (${b.channel || "chromium"}, ${b.headless ? "invisible" : "visible"}).` : "Le navigateur démarrera à la première recherche.")
        : "";
}

function renderCommunes() {
    const el = $("#commune-choice");
    if (!el) return;
    el.innerHTML = local.communes.length
        ? `<div class="commune-list">${local.communes.map((c) => `<button class="btn-ghost small" type="button" data-commune="${escapeHtml(c.city)}">${escapeHtml(c.city)}</button>`).join("")}</div>`
        : "";
}

function renderRetailerSettings(r) {
    const configured = Boolean(r.store);
    const status = r.needs_store
        ? (configured ? `<span class="state ok">✓ ${escapeHtml(r.store.name || "Magasin choisi")}</span>` : `<span class="state todo">Magasin à choisir</span>`)
        : `<span class="state ok">Prêt</span>`;
    let extra = "";
    if (r.key === "intermarche") {
        const stores = local.intermarcheStores;
        extra = `
            ${configured && r.store.address ? `<p class="small muted">${escapeHtml(r.store.address)}</p>` : ""}
            <div class="retailer-actions">
                <button class="btn-ghost small" type="button" data-find-stores>Trouver les magasins proches</button>
                ${configured ? `<button class="btn-ghost small danger" type="button" data-remove-store="intermarche">Retirer</button>` : ""}
            </div>
            ${stores === "loading" ? `<p class="small muted"><span class="spinner"></span> Recherche des magasins…</p>` : ""}
            ${Array.isArray(stores) ? (stores.length ? `<ul class="store-list">${stores.map((s) => `
                <li><button type="button" data-pick-store="${escapeHtml(s.id)}">
                    <strong>${escapeHtml(s.name)}</strong>${s.distance_km != null ? ` · ${String(s.distance_km).replace(".", ",")} km` : ""}
                    ${s.address ? `<span class="addr">${escapeHtml(s.address)}</span>` : ""}
                </button></li>`).join("")}</ul>` : `<p class="small muted">Aucun magasin trouvé autour de chez vous.</p>`) : ""}`;
    } else if (r.key === "coursesu") {
        extra = `
            <form class="row" data-coursesu-form>
                <input name="url" type="url" placeholder="https://www.coursesu.com/drive-superu-..." value="${escapeHtml(configured && r.store.url ? r.store.url : "")}" aria-label="Adresse du magasin Courses U">
                <button class="btn-primary small" type="submit">Enregistrer</button>
            </form>
            ${configured ? `<div class="retailer-actions"><button class="btn-ghost small danger" type="button" data-remove-store="coursesu">Retirer</button></div>` : ""}`;
    }
    return `
        <div class="retailer-card" data-retailer="${escapeHtml(r.key)}">
            <div class="retailer-head">${retailerBadge(r.key, r.label)}${status}</div>
            <p class="small muted">${escapeHtml(r.store_hint)}</p>
            ${extra}
            <div class="retailer-actions"><button class="btn-ghost small" type="button" data-setup="${escapeHtml(r.key)}">Ouvrir le site</button></div>
        </div>`;
}

// Scrolls to the card of retailer `key`; false when it is not shown (yet)
function focusRetailer(key) {
    if (!key || !root) return false;
    const card = root.querySelector(`[data-retailer="${CSS.escape(key)}"]`);
    if (card) card.scrollIntoView({ block: "center" });
    return Boolean(card);
}

// ---------------------------------------------------------------- actions

async function saveLocation(postalCode, city) {
    if (!/^\d{5}$/.test(postalCode)) {
        toast("Le code postal doit contenir 5 chiffres", true);
        return;
    }
    try {
        const res = await api("/api/settings/location", { method: "POST", body: { postal_code: postalCode, city } });
        local.intermarcheStores = null;
        local.communes = res.communes.length > 1 && !city ? res.communes : [];
        renderCommunes();
        setSettings(res.settings);
        toast(`Localisation enregistrée : ${res.settings.location.city || postalCode}`);
    } catch (err) {
        toast(err.message, true);
    }
}

// The store changed: reload the retailers and search again
async function afterStoreChange(message) {
    await loadSettings();
    toast(message);
    notify("results-stale");
}

async function findIntermarcheStores() {
    if (!store.settings.location || store.settings.location.lat == null) {
        toast("Indiquez d'abord votre code postal", true);
        return;
    }
    local.intermarcheStores = "loading";
    renderSettings();
    try {
        local.intermarcheStores = await api("/api/retailers/intermarche/stores");
    } catch (err) {
        local.intermarcheStores = null;
        throw err;
    } finally {
        renderSettings();
    }
}

function bind() {
    $("#location-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        await saveLocation($("#postal-input").value.trim());
    });

    $("#commune-choice").addEventListener("click", (e) => {
        const btn = e.target.closest("[data-commune]");
        if (!btn) return;
        local.communes = [];
        renderCommunes();
        saveLocation($("#postal-input").value.trim(), btn.dataset.commune);
    });

    $("#show-browser").addEventListener("change", async (e) => {
        try {
            const settings = await api("/api/settings", { method: "PATCH", body: { show_browser: e.target.checked } });
            const browser = await api("/api/browser");
            setSettings(settings);
            setBrowser(browser);
        } catch (err) {
            e.target.checked = !e.target.checked;
            toast(err.message, true);
        }
    });

    $("#retailer-settings").addEventListener("click", async (e) => {
        const btn = e.target.closest("button");
        // The submit button of the Courses U form is handled by the "submit" listener
        if (!btn || btn.type === "submit") return;
        try {
            if (btn.hasAttribute("data-find-stores")) {
                await findIntermarcheStores();
            } else if (btn.dataset.pickStore) {
                const picked = local.intermarcheStores.find((s) => s.id === btn.dataset.pickStore);
                await api("/api/retailers/intermarche/store", { method: "PUT", body: { id: picked.id, name: picked.name, address: picked.address } });
                local.intermarcheStores = null;
                await afterStoreChange(`Magasin Intermarché : ${picked.name}`);
            } else if (btn.dataset.removeStore) {
                await api(`/api/retailers/${btn.dataset.removeStore}/store`, { method: "DELETE" });
                await afterStoreChange("Magasin retiré");
            } else if (btn.dataset.setup) {
                await openSetup(btn.dataset.setup);
            }
        } catch (err) {
            toast(err.message, true);
        }
    });

    $("#retailer-settings").addEventListener("submit", async (e) => {
        if (!e.target.matches("[data-coursesu-form]")) return;
        e.preventDefault();
        const url = e.target.elements.url.value.trim();
        try {
            const settings = await api("/api/retailers/coursesu/store", { method: "PUT", body: { url } });
            await afterStoreChange(`Magasin Courses U : ${settings.stores.coursesu.name}`);
        } catch (err) {
            toast(err.message, true);
        }
    });
}

export default {
    name: "settings",
    path: "/reglages",
    title: "Réglages",
    nav: { label: "Réglages", order: 90 },

    render(container, params) {
        root = container;
        root.innerHTML = TEMPLATE;
        shown = { postal: null, retailers: null };
        bind();
        renderSettings();
        renderCommunes();
        const focused = focusRetailer(params.enseigne);
        unsubscribers = [subscribe("settings", renderSettings), subscribe("browser", renderBrowserStatus)];
        // Fresh state of the stores and of the browser, as when the dialog opened
        loadSettings()
            .then(() => focused || focusRetailer(params.enseigne))
            .catch((err) => toast(err.message, true));
    },

    update(params) {
        focusRetailer(params.enseigne);
    },

    destroy() {
        unsubscribers.forEach((off) => off());
        unsubscribers = [];
        root = null;
    },
};
