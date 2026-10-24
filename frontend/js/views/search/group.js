// Same product at several retailers (B38): products sharing a barcode (EAN)
// become one line of « Tout trié ». Never a fuzzy grouping: without an EAN a
// product stays alone. Pure function, tested with js_eval.

import { productKey } from "./rank.js";

// products: already ranked (the best first). Returns the groups in the order
// of their best product: [{ key, ean, products: [best, ...others in rank order] }]
export function group(products) {
    const byEan = new Map();
    const groups = [];
    for (const p of products) {
        const existing = p.ean ? byEan.get(p.ean) : null;
        if (existing) {
            existing.products.push(p);
            continue;
        }
        const g = { key: p.ean ? `ean:${p.ean}` : productKey(p), ean: p.ean || null, products: [p] };
        if (p.ean) byEan.set(p.ean, g);
        groups.push(g);
    }
    return groups;
}

// Number of retailers of a group
export function storeCount(g) {
    return new Set(g.products.map((p) => p.store)).size;
}
