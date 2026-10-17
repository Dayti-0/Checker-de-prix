// Safe HTML templates.
//
//   setHtml(el, html`<a href="${safeUrl(p.product_url)}">${p.name}</a>`)
//
// Every value put in html`` is escaped, unless it is itself an html`` result
// or raw(). Arrays are joined; null, undefined, false and true render nothing
// (so `${cond && html`...`}` works). Addresses coming from the sites go
// through safeUrl() (http/https only). attr({...}) builds attributes.
// setHtml(el, value) is the only way to fill innerHTML: it refuses plain strings.

class Html {
    constructor(value) {
        this.value = value;
    }

    toString() {
        return this.value;
    }
}

export function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function piece(value) {
    if (value == null || value === false || value === true) return "";
    if (value instanceof Html) return value.value;
    if (Array.isArray(value)) return value.map(piece).join("");
    return escapeHtml(value);
}

export function html(strings, ...values) {
    let out = strings[0];
    values.forEach((value, i) => {
        out += piece(value) + strings[i + 1];
    });
    return new Html(out);
}

// Trusted markup, used as is (never data coming from the server)
export function raw(markup) {
    return new Html(String(markup ?? ""));
}

export function isHtml(value) {
    return value instanceof Html;
}

// Only http(s) addresses are used in links and images (no "javascript:")
export function safeUrl(value) {
    const url = String(value ?? "").trim();
    return /^https?:\/\/[^\s/]/i.test(url) ? url : "";
}

// attr({ href: url, "data-id": 3, disabled: false, hidden: true }) → ` href="…" data-id="3" hidden`
export function attr(attributes) {
    let out = "";
    for (const [name, value] of Object.entries(attributes || {})) {
        if (value == null || value === false) continue;
        if (!/^[a-zA-Z_:][-a-zA-Z0-9_:.]*$/.test(name)) throw new Error(`Attribut invalide : ${name}`);
        out += value === true ? ` ${name}` : ` ${name}="${escapeHtml(value)}"`;
    }
    return new Html(out);
}

export function setHtml(el, value) {
    if (!(value instanceof Html)) throw new TypeError("setHtml() attend un résultat de html``");
    el.innerHTML = value.value;
}
