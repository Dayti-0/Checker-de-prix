const searchForm = document.getElementById("search-form");
const searchInput = document.getElementById("search-input");
const searchBtn = document.getElementById("search-btn");
const loadingEl = document.getElementById("loading");
const errorsEl = document.getElementById("errors");
const resultsSection = document.getElementById("results-section");
const queryDisplay = document.getElementById("query-display");
const resultsCount = document.getElementById("results-count");
const resultsGrid = document.getElementById("results-grid");
const noResults = document.getElementById("no-results");

searchForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = searchInput.value.trim();
    if (!query) return;
    await performSearch(query);
});

async function performSearch(query) {
    // UI state: loading
    loadingEl.classList.remove("hidden");
    errorsEl.classList.add("hidden");
    resultsSection.classList.add("hidden");
    noResults.classList.add("hidden");
    searchBtn.disabled = true;

    try {
        const resp = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
        if (!resp.ok) throw new Error(`Erreur serveur (${resp.status})`);
        const data = await resp.json();

        // Show errors if any (but still show results)
        if (data.errors && data.errors.length > 0) {
            errorsEl.innerHTML = data.errors
                .map((e) => `<div class="error-banner">${escapeHtml(e)}</div>`)
                .join("");
            errorsEl.classList.remove("hidden");
        }

        // Display results
        if (data.results && data.results.length > 0) {
            renderResults(data.query, data.results);
        } else {
            noResults.classList.remove("hidden");
        }
    } catch (err) {
        errorsEl.innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
        errorsEl.classList.remove("hidden");
    } finally {
        loadingEl.classList.add("hidden");
        searchBtn.disabled = false;
    }
}

function renderResults(query, results) {
    queryDisplay.textContent = query;
    resultsCount.textContent = `${results.length} produit${results.length > 1 ? "s" : ""} trouvé${results.length > 1 ? "s" : ""}`;

    // Find the best (lowest) price
    const prices = results.filter((p) => p.price != null).map((p) => p.price);
    const bestPrice = prices.length > 0 ? Math.min(...prices) : null;

    resultsGrid.innerHTML = results.map((p) => productCard(p, bestPrice)).join("");
    resultsSection.classList.remove("hidden");
}

function productCard(product, bestPrice) {
    const isBest = bestPrice !== null && product.price !== null && product.price === bestPrice;
    const storeKey = product.store_name.toLowerCase().replace(/\s+/g, "");

    const imageHtml = product.image_url
        ? `<img class="card-image" src="${escapeAttr(product.image_url)}" alt="${escapeAttr(product.name)}" loading="lazy">`
        : `<div class="card-image placeholder">Pas d'image</div>`;

    const priceHtml = product.price != null
        ? `<span class="card-price">${product.price.toFixed(2).replace(".", ",")} &euro;</span>`
        : `<span class="card-no-price">Prix non disponible</span>`;

    const unitHtml = product.price_per_unit
        ? `<span class="card-price-unit">${escapeHtml(product.price_per_unit)}</span>`
        : "";

    const linkHtml = product.product_url
        ? `<a class="card-link" href="${escapeAttr(product.product_url)}" target="_blank" rel="noopener">Voir sur ${escapeHtml(product.store_name)} &rarr;</a>`
        : "";

    return `
        <div class="product-card${isBest ? " best-price" : ""}">
            <div class="card-badge-row">
                <span class="store-badge ${storeKey}">${escapeHtml(product.store_name)}</span>
                ${isBest ? '<span class="best-label">Meilleur prix</span>' : ""}
            </div>
            ${imageHtml}
            <div class="card-body">
                <div class="card-name">${escapeHtml(product.name)}</div>
                <div class="card-pricing">
                    ${priceHtml}
                    ${unitHtml}
                </div>
                ${linkHtml}
            </div>
        </div>
    `;
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function escapeAttr(str) {
    return str.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
