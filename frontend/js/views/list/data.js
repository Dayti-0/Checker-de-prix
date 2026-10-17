// Small shared helpers of the views of P5: device memory (localStorage, never
// needed), the aisles, « Annuler » after a deletion.

import { api } from "../../core/api.js";
import { loadList } from "../../core/store.js";
import { notify } from "../../core/ui.js";

export function readJson(key, fallback) {
    try {
        return JSON.parse(localStorage.getItem(key)) ?? fallback;
    } catch {
        return fallback;
    }
}

export function writeJson(key, value) {
    try {
        localStorage.setItem(key, JSON.stringify(value));
    } catch {
        /* not saved: this page only */
    }
}

let categories = [];

// Aisles in the order of a store (GET /api/list/categories, read once)
export async function loadCategories() {
    if (!categories.length) {
        try {
            categories = await api("/api/list/categories");
        } catch {
            categories = [];
        }
    }
    return categories;
}

export function knownCategories() {
    return categories;
}

// « Annuler » after a deletion: the server puts the lines back as they were
export async function restoreItems(ids, message) {
    try {
        await api("/api/list/restore", { method: "POST", body: { ids } });
        await loadList();
        notify(message);
    } catch (err) {
        notify(err.message, { type: "error" });
    }
}
