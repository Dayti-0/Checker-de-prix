// Extra badges of a product row (search results). Each lot may push a
// provider: (product) => html`` (or null). Called by views/search/product-row.js.
//
//   import { productBadges } from "../../ext/product-badges.js";
//   productBadges.push((p) => p.ean && html`<span class="tag">Suivi</span>`);

export const productBadges = [];

// Result of every provider for `product` (a broken provider is skipped)
export function renderBadges(product) {
    return productBadges.map((provider) => {
        try {
            return provider(product);
        } catch (err) {
            console.error(err);
            return null;
        }
    });
}
