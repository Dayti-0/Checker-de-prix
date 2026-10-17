// Pure functions of the basket page (tested with js_eval): verdict, offers of
// an item sorted by price, notes of a cell, texts of the retailer cards.

import { euros, plural, relativeTime } from "../../core/fmt.js";
import { dayText, missingText } from "../list/model.js";

// Reason of a retailer that could not be searched (glossary of the app)
export const REASONS = {
    store_required: "Magasin à choisir",
    blocked: "Vérification requise",
    timeout: "Trop lent à répondre",
    error: "Erreur du site",
};

export function reasonLabel(reason) {
    return REASONS[reason] || "Pas comparée";
}

// « prix d'il y a 2 h », « prix d'hier », « prix du 2 octobre » (age of a price)
export function priceAge(ts, now = Date.now()) {
    const t = relativeTime(ts, now);
    if (t.startsWith("il y a")) return `prix d'${t}`;
    if (t === "hier") return "prix d'hier";
    if (t.startsWith("le ")) return `prix du ${t.slice(3)}`;
    return "";
}

// « 12/40 recherches »
export function progressText(done, total) {
    return `${done}/${plural(total, "recherche")}`;
}

function storeOf(comparison, key) {
    return (comparison.stores || []).find((s) => s.store === key) || null;
}

// The headline of the comparison:
// { kind: "best" | "most" | "none" | "empty", label, store, value, text, sub }
// « Panier le moins cher » only for a complete basket.
export function verdict(comparison) {
    if (!comparison || !comparison.item_count) {
        return { kind: "empty", label: "Rien à comparer", text: "Aucun article de la liste n'est à comparer." };
    }
    const n = comparison.item_count;
    if (comparison.best_store) {
        const s = storeOf(comparison, comparison.best_store);
        const others = (comparison.stores || []).filter((o) => o.complete && o.store !== s.store);
        let sub = "Seule enseigne avec tous les articles";
        if (others.length && s.saving) sub = `${euros(s.saving)} de moins que le panier complet le plus cher`;
        else if (others.length) sub = "Au même prix que les autres paniers complets";
        return {
            kind: "best",
            label: "Panier le moins cher",
            store: s.store,
            storeLabel: s.label,
            value: euros(s.total),
            text: `Panier complet : ${s.found_count}/${n} articles`,
            sub,
        };
    }
    if (comparison.most_items_store) {
        const s = storeOf(comparison, comparison.most_items_store);
        return {
            kind: "most",
            label: "Paniers incomplets",
            store: s.store,
            storeLabel: s.label,
            value: s.estimated_total != null ? euros(s.estimated_total) : euros(s.total),
            // Never a bare amount for an incomplete basket
            valueLabel: s.estimated ? "estimé" : `pour ${plural(s.found_count, "article")}`,
            text: `Aucune enseigne n'a tout : ${s.label} en a le plus (${s.found_count}/${n})`,
            sub: s.missing ? `${missingText(s.missing)} chez ${s.label}` : "",
        };
    }
    return {
        kind: "none",
        label: "Comparaison impossible",
        text: "Aucune enseigne n'a assez d'articles pour être comparée.",
    };
}

// « Sur les 3 articles communs : 4,91 € » (only when it says more than the total)
export function commonText(comparison, store) {
    const n = comparison.common_count || 0;
    if (!n || n >= comparison.item_count || store.common_total == null || !store.ranked) return "";
    return `Sur ${n >= 2 ? `les ${n} articles communs` : "l'article commun"} : ${euros(store.common_total)}`;
}

const ORDER = { found: 0, excluded: 1, not_found: 2, unchecked: 3 };

// The offers of an item at every retailer, cheapest first, then the others:
// [{ store, label, line }]
export function itemOffers(stores, itemId, cell) {
    const offers = stores.map((s) => ({ store: s.store, label: s.label, line: cell(s.store, itemId) }));
    return offers.sort((a, b) => {
        const la = a.line;
        const lb = b.line;
        const ra = la ? ORDER[la.status] : 4;
        const rb = lb ? ORDER[lb.status] : 4;
        if (ra !== rb) return ra - rb;
        if (ra === 0) return la.line_total - lb.line_total;
        return 0;
    });
}

// Lowest amount of an item among the lines found
export function cheapest(lines) {
    const totals = lines.filter((l) => l && l.status === "found" && l.line_total != null).map((l) => l.line_total);
    return totals.length ? Math.min(...totals) : null;
}

// Small notes under the price of a cell
export function cellNotes(line, now = Date.now()) {
    const notes = [];
    if (!line) return notes;
    if (line.manual) {
        notes.push({ kind: "manual", text: `saisi le ${dayText(line.pick && line.pick.picked_at)}` });
        if (line.expires_at) notes.push({ kind: "muted", text: `à mettre à jour avant le ${dayText(line.expires_at)}` });
    } else if (line.basis === "pick") {
        notes.push({ kind: "pick", text: "votre choix" });
    } else if (line.basis === "ean") {
        notes.push({ kind: "muted", text: "même code-barres" });
    }
    if (line.verified === false) notes.push({ kind: "warn", text: "prix non vérifié" });
    if (line.stale && line.message) notes.push({ kind: "warn", text: line.message });
    else if (line.fetched_at && !line.manual && now / 1000 - line.fetched_at >= 3600) {
        notes.push({ kind: "muted", text: priceAge(line.fetched_at, now) });
    }
    if (line.pick_issue === "expired") notes.push({ kind: "warn", text: "prix saisi trop ancien, non compté" });
    else if (line.pick_issue === "unavailable") notes.push({ kind: "warn", text: "votre choix est indisponible" });
    else if (line.pick_issue === "not_found") notes.push({ kind: "warn", text: "votre choix n'a pas été retrouvé" });
    return notes;
}

// « Tout chez Carrefour » / « Aldi + Lidl »
export function planTitle(plan) {
    const names = plan.stores.map((s) => s.label);
    return names.length === 1 ? `Tout chez ${names[0]}` : names.join(" + ");
}

// Texts of a retailer card: { count, total, estimate, common, saving, notes[] }
export function storeTexts(comparison, s, now = Date.now()) {
    const out = {
        count: `${s.found_count}/${plural(s.item_count, "article")}`,
        total: euros(s.total),
        estimate: s.estimated && s.estimated_total != null ? euros(s.estimated_total) : "",
        common: commonText(comparison, s),
        saving: s.saving ? `${euros(s.saving)} de moins que le panier complet le plus cher` : "",
        missing: s.missing ? missingText(s.missing) : "",
        notes: [],
    };
    if (s.excluded_count) out.notes.push(plural(s.excluded_count, "article pas disponible ici", "articles pas disponibles ici"));
    if (s.stale_count) out.notes.push(plural(s.stale_count, "prix ancien", "prix anciens"));
    if (s.manual_count) out.notes.push(plural(s.manual_count, "prix saisi", "prix saisis"));
    if (s.fetched_at && now / 1000 - s.fetched_at >= 3600) {
        out.notes.push(priceAge(s.fetched_at, now));
    }
    return out;
}
