// Tiny hash router: #/recherche?q=farine
//
// A view is a plain object registered with registerView():
//   {
//     name: "search",                 // unique id
//     path: "/recherche",             // route, without "#"
//     title: "Rechercher",            // or (params) => string; sets document.title
//     nav: { label, order, badge?, keepParams? },  // optional entry of the primary nav
//     render(container, params),      // build the view inside `container`
//     update?(params),                // same view, new params (else destroy + render)
//     destroy?(),                     // leave the view (unsubscribe, timers...)
//   }
// `nav.badge` is a function returning the number shown next to the label.
// `nav.keepParams`: the nav link returns to the last params of the view.
// Each render gets a fresh container, removed when the view is left, so
// event listeners added on it disappear with it.

import { escapeHtml } from "./util.js";

const views = [];
const lastHash = {};
let outlet = null;
let navEl = null;
let defaultPath = "/recherche";
let current = null; // { view, container, hash, params }

export function registerView(view) {
    if (!view || !view.name || !view.path || typeof view.render !== "function") {
        throw new Error("registerView : name, path et render() sont obligatoires");
    }
    if (views.some((v) => v.name === view.name || v.path === view.path)) {
        throw new Error(`Vue déjà enregistrée : ${view.name} (${view.path})`);
    }
    views.push(view);
    refreshNav();
}

// "#/recherche?q=huile%20de%20tournesol"
export function hrefFor(path, params = {}) {
    const query = Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== null && v !== "")
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
        .join("&");
    return `#${path}${query ? `?${query}` : ""}`;
}

function parseHash(hash) {
    const raw = hash.replace(/^#/, "");
    const cut = raw.indexOf("?");
    const pathPart = cut >= 0 ? raw.slice(0, cut) : raw;
    const query = cut >= 0 ? raw.slice(cut + 1) : "";
    const path = `/${pathPart.replace(/^\/+|\/+$/g, "")}`;
    return { path, params: Object.fromEntries(new URLSearchParams(query)) };
}

// Goes to `path`; `replace` does not add a history entry
export function navigate(path, params = {}, { replace = false } = {}) {
    const hash = hrefFor(path, params);
    if (replace) {
        history.replaceState(history.state, "", hash);
        handleRoute();
    } else if (location.hash !== hash) {
        location.hash = hash; // handled by the hashchange listener
    } else {
        handleRoute();
    }
}

export function currentRoute() {
    if (!current) return null;
    return { name: current.view.name, path: current.view.path, params: { ...current.params } };
}

// Redraws the primary nav (active link, badges). Cheap: call it when a badge changes.
export function refreshNav() {
    if (!navEl) return;
    const items = views.filter((v) => v.nav).sort((a, b) => (a.nav.order ?? 0) - (b.nav.order ?? 0));
    navEl.innerHTML = items.map((v) => {
        const active = Boolean(current && current.view === v);
        const href = (v.nav.keepParams && lastHash[v.name]) || hrefFor(v.path);
        const badge = typeof v.nav.badge === "function" ? v.nav.badge() : null;
        return `<a class="nav-link${active ? " active" : ""}" href="${escapeHtml(href)}" data-nav="${escapeHtml(v.name)}"${active ? ' aria-current="page"' : ""}>`
            + `${escapeHtml(v.nav.label)}${badge != null ? ` <span class="count">${escapeHtml(badge)}</span>` : ""}</a>`;
    }).join("");
}

function setTitle(view, params) {
    const title = typeof view.title === "function" ? view.title(params) : view.title;
    document.title = title ? `${title} · PrixMalin` : "PrixMalin";
}

function safely(fn, container) {
    try {
        fn();
    } catch (err) {
        console.error(err);
        if (container) container.innerHTML = `<div class="notice warn">Erreur d'affichage : ${escapeHtml(err.message)}</div>`;
    }
}

function handleRoute() {
    const { path, params } = parseHash(location.hash);
    const view = views.find((v) => v.path === path);
    if (!view) {
        // Unknown or empty route: back to the default view
        const fallback = views.find((v) => v.path === defaultPath);
        if (!fallback) return;
        history.replaceState(history.state, "", hrefFor(defaultPath));
        handleRoute();
        return;
    }
    const hash = hrefFor(path, params);
    lastHash[view.name] = hash;

    if (current && current.view === view) {
        if (current.hash === hash) return;
        current.hash = hash;
        current.params = params;
        setTitle(view, params);
        refreshNav();
        if (typeof view.update === "function") {
            safely(() => view.update(params));
            return;
        }
    }

    if (current) {
        const { view: old, container: oldContainer } = current;
        if (typeof old.destroy === "function") safely(() => old.destroy());
        oldContainer.remove();
    }
    const container = document.createElement("div");
    container.className = `view view-${view.name}`;
    container.dataset.view = view.name;
    outlet.replaceChildren(container);
    current = { view, container, hash, params };
    setTitle(view, params);
    refreshNav();
    window.scrollTo(0, 0);
    safely(() => view.render(container, params), container);
}

// Starts routing. Old links "/?q=farine" become "/#/recherche?q=farine".
export function start({ outlet: outletSelector = "#view", nav = "#primary-nav", defaultPath: path = "/recherche" } = {}) {
    outlet = document.querySelector(outletSelector);
    navEl = document.querySelector(nav);
    defaultPath = path;
    if (location.search) {
        const params = Object.fromEntries(new URLSearchParams(location.search));
        const hash = location.hash && location.hash !== "#" ? location.hash : hrefFor(defaultPath, params);
        history.replaceState(history.state, "", location.pathname + hash);
    }
    window.addEventListener("hashchange", handleRoute);
    handleRoute();
}
