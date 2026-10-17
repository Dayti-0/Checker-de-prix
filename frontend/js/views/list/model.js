// Pure functions of « Ma liste », « Panier » and « En magasin » (tested with js_eval).

import { euros, plural } from "../../core/fmt.js";

// 1793000000 (seconds) → "03/10"
export function dayText(ts) {
    if (ts == null) return "";
    const ms = Number(ts) < 1e12 ? Number(ts) * 1000 : Number(ts);
    return new Date(ms).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });
}

// What a chosen product shows in a line of the list:
// { name, price: "0,75 €", note: "saisi le 03/10" | "prix non vérifié" | "" }
export function pickParts(pick) {
    let note = "";
    if (pick.source === "manual") note = `saisi le ${dayText(pick.picked_at)}`;
    else if (pick.verified === false) note = "prix non vérifié";
    return { name: pick.name, price: pick.price != null ? euros(pick.price) : "", note };
}

// « × 2 », or nothing for one pack (the target replaces the quantity)
export function quantityText(item) {
    if (item.target) return "";
    return item.quantity > 1 ? `× ${item.quantity}` : "";
}

// The aisles of the list in the order of a store (`order`: GET /api/list/categories),
// unknown aisles after, each with its items in the order of the list
export function groupByAisle(items, order = []) {
    const groups = new Map();
    for (const item of items) {
        const name = item.category || "Autres";
        if (!groups.has(name)) groups.set(name, []);
        groups.get(name).push(item);
    }
    const rank = (name) => {
        const i = order.indexOf(name);
        return i < 0 ? order.length : i;
    };
    return [...groups.entries()]
        .map(([name, list]) => ({ name, items: list }))
        .sort((a, b) => rank(a.name) - rank(b.name));
}

// « 3/7 · 12,40 € » (counter of the mode « En magasin »)
export function counterText(checked, total, amount) {
    const base = `${checked}/${total}`;
    return amount ? `${base} · ${euros(amount)}` : base;
}

// « 1 article introuvable » / « 2 articles introuvables » (glossary)
export function missingText(n) {
    return plural(n, "article introuvable", "articles introuvables");
}

// Ticks waiting for the network: one per item, the latest tick wins
export function mergeCheck(queue, check) {
    const others = (queue || []).filter((c) => c.id !== check.id);
    const same = (queue || []).find((c) => c.id === check.id);
    if (same && (same.checked_at || 0) > (check.checked_at || 0)) return [...others, same];
    return [...others, check];
}
