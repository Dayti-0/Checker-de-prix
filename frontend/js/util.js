// Small helpers shared by every view.

export function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

export function euros(value) {
    return value == null ? "" : `${value.toFixed(2).replace(".", ",")} €`;
}

// "1,66 €/L" from the normalised unit price, else the label of the site
export function unitText(p) {
    if (p.unit_price != null && p.unit) return `${euros(p.unit_price)}/${p.unit}`;
    return p.unit_price_label || "";
}

let toastTimer = null;

// Message at the bottom of the screen (shell element #toast)
export function toast(message, isError = false) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = message;
    el.classList.toggle("error", isError);
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 3000);
}

export function debounce(fn, wait = 250) {
    let timer = null;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), wait);
    };
}
