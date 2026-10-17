// Retailers to compare (#store-filters, above the views). Its content belongs
// to the search page (area of P2): js/views/search/filters.js. The choice is
// shared by every view and saved in localStorage ("prixmalin.enabled"); each
// change emits "filters:changed" (core/store.js).

export { mountStoreFilters } from "../views/search/filters.js";
