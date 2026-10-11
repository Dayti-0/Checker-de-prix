// What the results show, in what order, and how they compare (pure functions,
// no DOM: tested with js_eval in tests/e2e/test_p2_rank.py).
//
// A product of a search (backend Product) is:
//   - the product searched when relevance >= 1: main list, number of
//     products, « Le moins cher », summary;
//   - a close product (« Produits proches », folded) when 0 < relevance < 1;
//   - unrelated (never shown) when relevance is 0.
// Prices per unit are only compared in the dominant unit of the search (kg, L
// or pièce): never €/kg against €/L.

// Sorts of the results (toolbar): price, price per kg/L, promotions first, relevance
export const SORTS = ["price", "unit", "promo", "relevance"];

export function isRelevant(p) {
    return Boolean(p) && p.relevance >= 1;
}

export function isClose(p) {
    return Boolean(p) && p.relevance > 0 && p.relevance < 1;
}

export function isAvailable(p) {
    return p.available !== false;
}

export function hasPromo(p) {
    return Boolean(p.promo) || (p.old_price != null && p.price != null && p.old_price > p.price);
}

// Identity of a product in the page (updates, focus, « + »). The link alone
// is not enough: a site may give the same page (its home page) to several
// products; the server removes the duplicates on the same fields.
export function productKey(p) {
    return [p.store, p.product_url || "", p.name, p.quantity_label || "", p.price ?? ""].join("|");
}

export function relevantOf(result) {
    return ((result && result.products) || []).filter(isRelevant);
}

export function closeOf(result) {
    return ((result && result.products) || []).filter(isClose);
}

// Unit in which most products are priced: "kg", "L", "pièce" (ties in this order) or null
export function dominantUnit(products) {
    const counts = new Map();
    for (const p of products) {
        if (p.unit_price != null && p.unit) counts.set(p.unit, (counts.get(p.unit) || 0) + 1);
    }
    const order = ["kg", "L", "pièce"];
    let best = null;
    for (const [unit, count] of counts) {
        const current = best == null ? -1 : counts.get(best);
        const better =
            count > current ||
            (count === current && (order.indexOf(unit) + 1 || 99) < (order.indexOf(best) + 1 || 99));
        if (better) best = unit;
    }
    return best;
}

// Price per unit of `p` in `unit`, else null (another unit is not comparable)
export function unitValue(p, unit) {
    return p.unit_price != null && unit && p.unit === unit ? p.unit_price : null;
}

// Value compared by a sort: the price per unit for "unit", else the price
export function valueOf(p, sort, unit) {
    return sort === "unit" ? unitValue(p, unit) : p.price;
}

const big = (v) => (v == null ? Number.POSITIVE_INFINITY : v);
const text = (a, b) => String(a || "").localeCompare(String(b || ""), "fr");

// Order of the products: available first, then the criterion of the sort, then
// a fixed order (price, retailer, name, address) so that the order is stable
// from one answer to the next. `order`: retailer keys in display order.
export function comparator({ sort = "price", unit = null, order = [] } = {}) {
    const position = (key) => {
        const i = order.indexOf(key);
        return i < 0 ? order.length : i;
    };
    const tie = (a, b) =>
        big(a.price) - big(b.price) ||
        position(a.store) - position(b.store) ||
        text(a.name, b.name) ||
        text(a.product_url, b.product_url);
    return (a, b) => {
        const available = !isAvailable(a) - !isAvailable(b);
        if (available) return available;
        if (sort === "unit") return big(unitValue(a, unit)) - big(unitValue(b, unit)) || tie(a, b);
        if (sort === "promo") return hasPromo(b) - hasPromo(a) || tie(a, b);
        if (sort === "relevance") return (b.match_score ?? 0) - (a.match_score ?? 0) || tie(a, b);
        return tie(a, b);
    };
}

export function rank(products, options = {}) {
    return [...products].sort(comparator(options));
}

// Close products: the closest first, then by price
export function rankClose(products, order = []) {
    const byPrice = comparator({ sort: "price", order });
    return [...products].sort(
        (a, b) => !isAvailable(a) - !isAvailable(b) || (b.match_score ?? 0) - (a.match_score ?? 0) || byPrice(a, b),
    );
}

// Products that can be « Le moins cher »: available, with a price
function buyable(products) {
    return products.filter((p) => isAvailable(p) && p.price != null);
}

// Cheapest relevant product (the badge « Le moins cher », the same in both views)
export function cheapest(products, order = []) {
    const list = buyable(products.filter(isRelevant));
    return list.length ? rank(list, { sort: "price", order })[0] : null;
}

// Relevant product with the lowest price per `unit`
export function bestPerUnit(products, unit, order = []) {
    const list = buyable(products.filter(isRelevant)).filter((p) => unitValue(p, unit) != null);
    return list.length ? rank(list, { sort: "unit", unit, order })[0] : null;
}

// ---------------------------------------------------------------- result filters (B31)

export const RESULT_FILTERS = [
    { id: "bio", label: "Bio", test: (p) => Boolean(p.bio) },
    { id: "promo", label: "En promo", test: hasPromo },
    { id: "available", label: "Disponible", test: isAvailable },
    { id: "store_brand", label: "Marque distributeur", test: (p) => p.store_brand === true, group: "brand" },
    { id: "national", label: "Marque nationale", test: (p) => p.store_brand === false, group: "brand" },
];

// Products that pass every active filter (the two brand filters: either of them)
export function applyFilters(products, active = []) {
    const ids = new Set(active);
    const chosen = RESULT_FILTERS.filter((f) => ids.has(f.id));
    if (!chosen.length) return [...products];
    const brand = chosen.filter((f) => f.group === "brand");
    const others = chosen.filter((f) => f.group !== "brand");
    return products.filter(
        (p) => others.every((f) => f.test(p)) && (!brand.length || brand.some((f) => f.test(p))),
    );
}

// Number of products that each filter would keep: { bio: 2, promo: 1, ... }
export function filterCounts(products) {
    return Object.fromEntries(RESULT_FILTERS.map((f) => [f.id, products.filter(f.test).length]));
}

// ---------------------------------------------------------------- gaps and summary (B26)

// Gap of `value` to the best one: { abs: 0.1, pct: 13 }, null for the best itself or without values
export function gap(value, best) {
    if (value == null || best == null || value <= best) return null;
    const abs = Math.round((value - best) * 100) / 100;
    if (abs <= 0) return null;
    return { abs, pct: best > 0 ? Math.round(((value - best) / best) * 100) : null };
}

// "+0,10 €/kg, +13 %" ("" without gap)
export function gapText(g, unit = null) {
    if (!g) return "";
    const amount = `+${g.abs.toFixed(2).replace(".", ",")} €${unit ? `/${unit}` : ""}`;
    return g.pct == null ? amount : `${amount}, +${g.pct} %`;
}

const FAILED = new Set(["store_required", "blocked", "timeout", "error", "skipped"]);

// State of one retailer for the summary and the views:
//   loading | ok (relevant products) | none (answered, nothing relevant) | error
export function retailerState(result) {
    if (!result || result.status === "loading") return "loading";
    if (FAILED.has(result.status)) return "error";
    return relevantOf(result).length ? "ok" : "none";
}

// Summary of a search.
//   results: { key: StoreResult | {status: "loading"} }; keys: retailers shown,
//   in display order; sort; filters: active result filters.
// Returns { unit, cheapest, bestUnit, best, headline, lines, savings, done, total }:
//   lines: one per retailer { key, state, product, value, gap, bar } where
//   product is its best relevant offer for the criterion of the sort and bar
//   the width (0 to 100) of its proportional bar.
export function summarize(results, keys, { sort = "price", filters = [] } = {}) {
    const products = [];
    for (const key of keys) {
        const result = results[key];
        if (result && result.status === "ok") products.push(...applyFilters(relevantOf(result), filters));
    }
    const unit = dominantUnit(products);
    const cheap = cheapest(products, keys);
    const perUnit = unit ? bestPerUnit(products, unit, keys) : null;
    const byUnit = sort === "unit" && perUnit != null;
    const criterion = byUnit ? "unit" : "price";
    const best = byUnit ? perUnit : cheap;

    const lines = keys.map((key) => {
        const result = results[key];
        const state = retailerState(result);
        const own = state === "ok" ? applyFilters(relevantOf(result), filters) : [];
        const product = byUnit ? bestPerUnit(own, unit, keys) : cheapest(own, keys);
        const value = product ? valueOf(product, criterion, unit) : null;
        // Products found, but none priced in the unit compared
        const noUnit = state === "ok" && !product && byUnit && own.length > 0;
        return { key, state: state === "ok" && !product ? "none" : state, product, value, noUnit };
    });
    const values = lines.map((l) => l.value).filter((v) => v != null);
    const top = values.length ? Math.max(...values) : null;
    const low = values.length ? Math.min(...values) : null;
    for (const line of lines) {
        line.gap = line.value == null ? null : gap(line.value, low);
        line.bar = line.value == null || !top ? 0 : Math.max(4, Math.round((line.value / top) * 100));
    }
    const done = keys.filter((k) => retailerState(results[k]) !== "loading").length;
    return {
        unit,
        cheapest: cheap,
        bestUnit: perUnit,
        best,
        criterion,
        headline: byUnit ? `Meilleur prix au ${unit}` : "Le moins cher",
        lines,
        // « Jusqu'à 1,14 € de moins que l'offre la plus chère » (best offers of 2 retailers at least)
        savings: values.length >= 2 && top - low >= 0.01 ? Math.round((top - low) * 100) / 100 : null,
        done,
        total: keys.length,
    };
}

// ---------------------------------------------------------------- no result (B34)

const STOP_WORDS = new Set([
    "de",
    "du",
    "des",
    "d",
    "la",
    "le",
    "les",
    "l",
    "un",
    "une",
    "a",
    "à",
    "au",
    "aux",
    "en",
    "et",
    "pour",
    "avec",
    "sans",
    "sur",
]);
const UNITS = new Set(["kg", "g", "gr", "l", "cl", "ml", "litre", "litres", "x", "pack", "lot"]);
const QUANTITY = /^(\d+([.,]\d+)?\s*x\s*)?\d+([.,]\d+)?(kg|g|gr|l|cl|ml)?$|^\d+l\d+$|^x\d+$/i;

function isQuantity(word, previous) {
    const w = word.toLowerCase();
    return QUANTITY.test(w) || (UNITS.has(w) && previous != null && /\d$/.test(previous));
}

// Shorter searches for « Aucun produit »: the query without its quantities,
// then each meaningful word ("chocolat noir 100 g" → ["chocolat noir", "chocolat", "noir"])
export function shorterQueries(query) {
    const words = String(query || "")
        .trim()
        .split(/\s+/)
        .filter(Boolean);
    const kept = words.filter((w, i) => !isQuantity(w, words[i - 1]) && !w.startsWith("-"));
    const out = [];
    const add = (q) => {
        const clean = q.trim();
        if (clean && clean.toLowerCase() !== String(query).trim().toLowerCase() && !out.includes(clean)) out.push(clean);
    };
    add(kept.join(" "));
    if (kept.length > 1) {
        for (const w of kept) {
            const bare = w.replace(/^[ldLD]['’]/, "");
            if (bare.length >= 3 && !STOP_WORDS.has(bare.toLowerCase())) add(bare);
        }
    }
    return out;
}
