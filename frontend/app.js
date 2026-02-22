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

// Location modal elements
const locationBtn = document.getElementById("location-btn");
const locationLabel = document.getElementById("location-label");
const locationModal = document.getElementById("location-modal");
const locationForm = document.getElementById("location-form");
const postalInput = document.getElementById("postal-input");
const modalCancel = document.getElementById("modal-cancel");
const modalBackdrop = locationModal.querySelector(".modal-backdrop");

// Store filter checkboxes
const storeCheckboxes = document.querySelectorAll(".store-checkbox input");

// --- Search ---

searchForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = searchInput.value.trim();
    if (!query) return;
    await performSearch(query);
});

function getSelectedStores() {
    const selected = [];
    storeCheckboxes.forEach((cb) => {
        if (cb.checked) selected.push(cb.value);
    });
    return selected;
}

async function performSearch(query) {
    loadingEl.classList.remove("hidden");
    errorsEl.classList.add("hidden");
    resultsSection.classList.add("hidden");
    noResults.classList.add("hidden");
    searchBtn.disabled = true;

    try {
        const stores = getSelectedStores();
        let url = `/api/search?q=${encodeURIComponent(query)}`;
        if (stores.length > 0 && stores.length < storeCheckboxes.length) {
            url += `&stores=${encodeURIComponent(stores.join(","))}`;
        }

        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`Erreur serveur (${resp.status})`);
        const data = await resp.json();

        if (data.errors && data.errors.length > 0) {
            errorsEl.innerHTML = data.errors
                .map((e) => `<div class="error-banner">${escapeHtml(e)}</div>`)
                .join("");
            errorsEl.classList.remove("hidden");
        }

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

    const needsLocation = ["Courses U", "Intermarché"].includes(product.store_name);
    let priceHtml;
    if (product.price != null) {
        priceHtml = `<span class="card-price">${product.price.toFixed(2).replace(".", ",")} &euro;</span>`;
    } else if (needsLocation && !locationBtn.classList.contains("configured")) {
        priceHtml = `<span class="card-no-price">Configurez votre <a href="#" class="location-link">code postal</a> pour voir le prix</span>`;
    } else {
        priceHtml = `<span class="card-no-price">Prix non disponible</span>`;
    }

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

// --- Location modal ---

locationBtn.addEventListener("click", () => {
    locationModal.classList.remove("hidden");
    postalInput.focus();
});

modalCancel.addEventListener("click", closeModal);
modalBackdrop.addEventListener("click", closeModal);

function closeModal() {
    locationModal.classList.add("hidden");
}

locationForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const postalCode = postalInput.value.trim();
    if (!postalCode || postalCode.length !== 5) return;

    try {
        const resp = await fetch("/api/config/location", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ postal_code: postalCode }),
        });
        if (!resp.ok) throw new Error("Erreur lors de la configuration");

        locationLabel.textContent = postalCode;
        locationBtn.classList.add("configured");
        closeModal();
    } catch (err) {
        alert(err.message);
    }
});

// Load saved config on page load
async function loadConfig() {
    try {
        const resp = await fetch("/api/config/stores");
        if (!resp.ok) return;
        const config = await resp.json();
        if (config.postal_code) {
            locationLabel.textContent = config.postal_code;
            locationBtn.classList.add("configured");
            postalInput.value = config.postal_code;
        }
    } catch {
        // Ignore — config not yet set
    }
}

loadConfig();

// Open location modal when clicking "code postal" links in product cards
document.addEventListener("click", (e) => {
    if (e.target.classList.contains("location-link")) {
        e.preventDefault();
        locationModal.classList.remove("hidden");
        postalInput.focus();
    }
});

// --- Utilities ---

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function escapeAttr(str) {
    return str.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
