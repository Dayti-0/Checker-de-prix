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

// Every item of the comparison counted: an item not found, not checked or
// « pas disponible ici » is missing (whatever a comparison saved before says)
export function isComplete(s, n) {
    return Boolean(s) && s.status !== "unchecked" && s.found_count > 0 && s.found_count === n;
}

// What a basket does not count, by reason (glossary of the app):
// ["1 article introuvable", "4 articles non vérifiés", "1 article pas disponible ici"]
// `here`: what follows « pas disponible » (" ici" in a card, "" after « Chez Lidl : »)
export function absentParts(s, here = " ici") {
    const parts = [];
    if (s.not_found_count) parts.push(missingText(s.not_found_count));
    if (s.unchecked_count) parts.push(plural(s.unchecked_count, "article non vérifié", "articles non vérifiés"));
    if (s.excluded_count) {
        parts.push(plural(s.excluded_count, `article pas disponible${here}`, `articles pas disponibles${here}`));
    }
    if (!parts.length && s.missing) parts.push(missingText(s.missing));
    return parts;
}

// The headline of the comparison:
// { kind: "best" | "most" | "none" | "empty", label, store, value, text, sub }
// « Panier le moins cher » only for a complete basket.
export function verdict(comparison) {
    if (!comparison || !comparison.item_count) {
        return { kind: "empty", label: "Rien à comparer", text: "Aucun article de la liste n'est à comparer." };
    }
    const n = comparison.item_count;
    const best = comparison.best_store ? storeOf(comparison, comparison.best_store) : null;
    if (isComplete(best, n)) {
        const s = best;
        const others = (comparison.stores || []).filter((o) => isComplete(o, n) && o.store !== s.store);
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
    const most = storeOf(comparison, comparison.most_items_store || (best ? best.store : null));
    if (most) {
        const s = most;
        // Other retailers with as many items: « Lidl et Aldi en ont le plus »
        const tied = (comparison.stores || []).filter(
            (o) => o.store !== s.store && o.status !== "unchecked" && o.found_count === s.found_count,
        );
        const names = [s.label, ...tied.map((o) => o.label)];
        const who = tied.length ? `${names.slice(0, -1).join(", ")} et ${names.at(-1)} en ont` : `${s.label} en a`;
        const sub = [];
        if (tied.length) sub.push(s.estimated ? `Total estimé le plus bas : ${s.label}` : `Le moins cher : ${s.label}`);
        const absent = absentParts(s, "");
        if (absent.length) sub.push(`Chez ${s.label} : ${absent.join(", ")}`);
        return {
            kind: "most",
            label: "Paniers incomplets",
            store: s.store,
            storeLabel: s.label,
            value: s.estimated_total != null ? euros(s.estimated_total) : euros(s.total),
            // Never a bare amount for an incomplete basket
            valueLabel: s.estimated ? "estimé" : `pour ${plural(s.found_count, "article")}`,
            text: `Aucune enseigne n'a tout : ${who} le plus (${s.found_count}/${n})`,
            sub: sub.join(" · "),
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

// « Tout chez Carrefour » (every item), « Chez Aldi seulement » (some missing), « Aldi + Lidl »
export function planTitle(plan) {
    const names = plan.stores.map((s) => s.label);
    if (names.length > 1) return names.join(" + ");
    return plan.complete ? `Tout chez ${names[0]}` : `Chez ${names[0]} seulement`;
}

// Amount of a plan, never bare when an item is missing: { value: "15,12 €", qualifier:
// "estimé" | "pour 3 articles" | "" } (the same everywhere: plans, « En magasin », sharing)
export function planAmount(plan) {
    if (plan.estimated) return { value: euros(plan.estimated_total), qualifier: "estimé" };
    if (plan.complete) return { value: euros(plan.total), qualifier: "" };
    const n = plan.stores.reduce((sum, s) => sum + (s.item_ids || []).length, 0);
    return { value: euros(plan.total), qualifier: `pour ${plural(n, "article")}` };
}

// « 19,39 € », « 15,12 € estimé », « 9,88 € pour 3 articles »
export function planAmountText(plan) {
    const a = planAmount(plan);
    return a.qualifier ? `${a.value} ${a.qualifier}` : a.value;
}

// « 1 article introuvable » when no retailer of the plan has it, else « 2 articles manquants »
// (not checked, or « pas disponible ici »)
export function planMissingText(plan, comparison) {
    const n = plan.missing || 0;
    if (!n) return "";
    const keys = new Set(plan.stores.map((s) => s.store));
    const lines = ((comparison && comparison.stores) || []).filter((s) => keys.has(s.store)).flatMap((s) => s.lines || []);
    const ids = plan.missing_item_ids || [];
    const notFound = ids.length > 0 && ids.every((id) => lines.filter((l) => l.item_id === id).every((l) => l.status === "not_found"));
    return notFound ? missingText(n) : plural(n, "article manquant", "articles manquants");
}

// Why a retailer is not ranked
export function unrankedText(s) {
    if (s.ranked) return "";
    if (s.unchecked_count) return `Pas classée : recherche interrompue${s.reason ? ` (${reasonLabel(s.reason)})` : ""}.`;
    return "Pas classée : moins de la moitié des articles trouvés.";
}

// Texts of a retailer card: { count, total, estimate, common, saving, missing, unranked, notes[] }
export function storeTexts(comparison, s, now = Date.now()) {
    const out = {
        count: `${s.found_count}/${plural(s.item_count, "article")}`,
        total: euros(s.total),
        estimate: s.estimated && s.estimated_total != null ? euros(s.estimated_total) : "",
        common: commonText(comparison, s),
        saving: s.saving ? `${euros(s.saving)} de moins que le panier complet le plus cher` : "",
        missing: absentParts(s).join(" · "),
        unranked: unrankedText(s),
        notes: [],
    };
    if (s.stale_count) out.notes.push(plural(s.stale_count, "prix ancien", "prix anciens"));
    if (s.manual_count) out.notes.push(plural(s.manual_count, "prix saisi", "prix saisis"));
    if (s.fetched_at && now / 1000 - s.fetched_at >= 3600) {
        out.notes.push(priceAge(s.fetched_at, now));
    }
    return out;
}
