// French formatting of numbers, prices and dates.

// 1.5 → "1,50 €"
export function euros(value) {
    return value == null ? "" : `${value.toFixed(2).replace(".", ",")} €`;
}

// "1,66 €/L" from the normalised unit price, else the label of the site
export function unitText(p) {
    if (p.unit_price != null && p.unit) return `${euros(p.unit_price)}/${p.unit}`;
    return p.unit_price_label || "";
}

// plural(0, "produit") → "0 produit" ; plural(2, "article introuvable", "articles introuvables")
export function plural(n, singular, pluralForm = `${singular}s`) {
    return `${n} ${Math.abs(n) >= 2 ? pluralForm : singular}`;
}

// relativeTime(ts) → "à l'instant", "il y a 5 min", "il y a 2 h", "hier", "il y a 3 jours", "le 2 octobre"
// ts: seconds (time.time() of the server), milliseconds or a Date
export function relativeTime(ts, now = Date.now()) {
    if (ts == null || ts === "") return "";
    const ms = ts instanceof Date ? ts.getTime() : Number(ts) < 1e12 ? Number(ts) * 1000 : Number(ts);
    const minutes = Math.floor((now - ms) / 60000);
    if (minutes < 1) return "à l'instant";
    if (minutes < 60) return `il y a ${minutes} min`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `il y a ${hours} h`;
    const days = Math.floor(hours / 24);
    if (days === 1) return "hier";
    if (days < 7) return `il y a ${days} jours`;
    return `le ${new Date(ms).toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}`;
}
