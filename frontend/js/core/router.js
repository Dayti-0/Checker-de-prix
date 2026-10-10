// Hash router: #/recherche?q=farine, #/produit/aldi/3560070472888
//
// The table of routes is fixed (js/routes.js): [{ name, path, view }], where a
// path may hold parameters (/produit/:store/:key). A view is a module exporting:
//   enabled              false: the route is hidden and leads to the home page
//   title                string or (params) => string, for document.title
//   render(el, params)   builds the view in `el` (a new element each time,
//                        removed when the view is left with its listeners)
//   update(params)       optional: same view, new params (else destroy + render)
//   destroy()            optional: the view is left (unsubscribe, timers...)
//   nav                  optional entry of the main navigation:
//                        { id, label, icon, order, badge?: () => number|null,
//                          also?: [other paths that light it up] }
//   shell                optional { search, filters }: show the search form /
//                        the retailer filters of the page above the view
// Event "route:changed" { name, path, params } after each render.

import { emit } from "./events.js";
import { html, setHtml } from "./html.js";

let routes = [];
let outlet = null;
let defaultPath = "/";
let current = null; // { route, container, hash, params }
const lastHashByNav = {}; // nav id → last address shown under this entry

// "#/recherche?q=huile%20de%20tournesol"
export function hrefFor(path, params = {}) {
    const query = Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== null && v !== "")
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
        .join("&");
    return `#${path}${query ? `?${query}` : ""}`;
}

function compile(path) {
    const keys = [];
    const pattern = path
        .split("/")
        .map((part) => {
            if (part.startsWith(":")) {
                keys.push(part.slice(1));
                return "([^/]+)";
            }
            return part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        })
        .join("/");
    return { regex: new RegExp(`^${pattern}$`), keys };
}

function parseHash(hash) {
    const rawHash = hash.replace(/^#/, "");
    const cut = rawHash.indexOf("?");
    const pathPart = cut >= 0 ? rawHash.slice(0, cut) : rawHash;
    const query = cut >= 0 ? rawHash.slice(cut + 1) : "";
    const path = `/${pathPart.replace(/^\/+|\/+$/g, "")}`;
    return { path, params: Object.fromEntries(new URLSearchParams(query)) };
}

function match(path) {
    for (const route of routes) {
        if (route.view.enabled === false) continue;
        const found = route.compiled.regex.exec(path);
        if (found) {
            const params = {};
            route.compiled.keys.forEach((key, i) => {
                try {
                    params[key] = decodeURIComponent(found[i + 1]);
                } catch {
                    params[key] = found[i + 1];
                }
            });
            return { route, params };
        }
    }
    return null;
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
    return { name: current.route.name, path: current.route.path, params: { ...current.params } };
}

// Module of the view shown (its `shell`, `nav`...), or null
export function currentView() {
    return current ? current.route.view : null;
}

function navOwner(route) {
    return routes.find(
        (r) => r.view.enabled !== false && r.view.nav && (r === route || (r.view.nav.also || []).includes(route.path)),
    );
}

// Entries of the main navigation, by order: { id, label, icon, href, active, badge }
export function navEntries() {
    const owner = current ? navOwner(current.route) : null;
    return routes
        .filter((r) => r.view.enabled !== false && r.view.nav)
        .sort((a, b) => (a.view.nav.order ?? 0) - (b.view.nav.order ?? 0))
        .map((r) => {
            const nav = r.view.nav;
            return {
                id: nav.id || r.name,
                label: nav.label,
                icon: nav.icon || null,
                href: lastHashByNav[nav.id || r.name] || hrefFor(r.path),
                active: owner === r,
                badge: typeof nav.badge === "function" ? nav.badge() : null,
            };
        });
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
        if (container) setHtml(container, html`<div class="notice warn">Erreur d'affichage : ${err.message}</div>`);
    }
}

function changed() {
    emit("route:changed", currentRoute());
}

function handleRoute() {
    const { path, params } = parseHash(location.hash);
    const found = match(path);
    if (!found) {
        // Unknown, hidden or empty route: back to the default view
        if (!match(defaultPath)) return;
        history.replaceState(history.state, "", hrefFor(defaultPath));
        handleRoute();
        return;
    }
    const { route } = found;
    const allParams = { ...params, ...found.params };
    const hash = hrefFor(path, params);
    const owner = navOwner(route);
    if (owner && owner.view.nav.keepParams) lastHashByNav[owner.view.nav.id || owner.name] = hash;

    if (current && current.route === route) {
        if (current.hash === hash) return;
        current.hash = hash;
        current.params = allParams;
        setTitle(route.view, allParams);
        if (typeof route.view.update === "function") {
            safely(() => route.view.update(allParams));
            changed();
            return;
        }
    }

    if (current) {
        const { route: old, container: oldContainer } = current;
        if (typeof old.view.destroy === "function") safely(() => old.view.destroy());
        oldContainer.remove();
    }
    const container = document.createElement("div");
    container.className = `view view-${route.name}`;
    container.dataset.view = route.name;
    outlet.replaceChildren(container);
    current = { route, container, hash, params: allParams };
    setTitle(route.view, allParams);
    window.scrollTo(0, 0);
    safely(() => route.view.render(container, allParams), container);
    changed();
}

// Declares the table of routes (js/routes.js): the navigation can be drawn
// before the routing starts
export function defineRoutes(table) {
    routes = table.map((route) => ({ ...route, compiled: compile(route.path) }));
}

// Starts routing. Old links "/?q=farine" become "/#/recherche?q=farine".
export function start({ routes: table, outlet: outletSelector = "#view", defaultPath: path = "/" } = {}) {
    if (table) defineRoutes(table);
    outlet = document.querySelector(outletSelector);
    defaultPath = path;
    if (location.search) {
        const params = Object.fromEntries(new URLSearchParams(location.search));
        const hash =
            location.hash && location.hash !== "#" ? location.hash : params.q ? hrefFor("/recherche", params) : "#/";
        history.replaceState(history.state, "", location.pathname + hash);
    } else if (!location.hash || location.hash === "#") {
        history.replaceState(history.state, "", location.pathname + hrefFor(defaultPath));
    }
    window.addEventListener("hashchange", handleRoute);
    handleRoute();
}
