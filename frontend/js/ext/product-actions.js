// Extra actions of a product row (search results), next to the « + » button.
// Each lot may push a provider: (product) => html`` (or null). Called by
// views/search/product-row.js.

export const productActions = [];

// Result of every provider for `product` (a broken provider is skipped)
export function renderActions(product) {
    return productActions.map((provider) => {
        try {
            return provider(product);
        } catch (err) {
            console.error(err);
            return null;
        }
    });
}
