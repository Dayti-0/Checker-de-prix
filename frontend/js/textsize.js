// A− / A+ buttons of the top bar.
// Multiplies the 16px base (CSS: html { font-size: calc(16px * var(--ui-scale)) })

const TEXT_SCALES = [0.9, 1, 1.125, 1.25, 1.4, 1.6];
const SCALE_KEY = "prixmalin.textScale";

function defaultScale() {
    return window.matchMedia("(min-width: 900px)").matches ? 1.125 : 1;
}

function currentScale() {
    let saved = null;
    try { saved = Number(localStorage.getItem(SCALE_KEY)); } catch { /* ignore */ }
    return TEXT_SCALES.includes(saved) ? saved : defaultScale();
}

function applyScale(scale, save) {
    document.documentElement.style.setProperty("--ui-scale", String(scale));
    document.getElementById("text-smaller").disabled = scale <= TEXT_SCALES[0];
    document.getElementById("text-bigger").disabled = scale >= TEXT_SCALES[TEXT_SCALES.length - 1];
    if (save) {
        try { localStorage.setItem(SCALE_KEY, String(scale)); } catch { /* ignore */ }
    }
}

function stepScale(direction) {
    const index = TEXT_SCALES.indexOf(currentScale());
    const next = TEXT_SCALES[Math.max(0, Math.min(TEXT_SCALES.length - 1, index + direction))];
    applyScale(next, true);
}

export function initTextSize() {
    document.getElementById("text-smaller").addEventListener("click", () => stepScale(-1));
    document.getElementById("text-bigger").addEventListener("click", () => stepScale(1));
    applyScale(currentScale(), false);
}
