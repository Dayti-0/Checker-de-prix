// Suggestions while typing in the search field #q (B33).
//
// Sources: the recent searches of this device, the lines of « Ma liste » and
// aliments.json next to this module (common products, read the first time the field
// gets the focus). Ranking (suggest(), pure): the suggestions that start with
// the text typed first, then those with a word starting with it, then the
// others containing it; in each group the most frequent first.
//
// The field keeps its role « searchbox » (every test and screen finds it by
// it): it gets aria-autocomplete="list", aria-controls and
// aria-activedescendant pointing to the listbox #q-suggestions. A searchbox
// cannot carry aria-expanded: when the list opens, or its length changes,
// « 3 suggestions, flèches haut et bas pour choisir » is announced (after a
// pause in the typing). Keys: ↓ / ↑ move in the list, Entrée searches the
// suggestion, Échap closes the list, Suppr removes a recent search.

import { plural } from "../../core/fmt.js";
import { announce } from "../../core/ui.js";
import { html, setHtml } from "../../core/html.js";
import { icon } from "../../core/icons.js";
import { on, requestSearch, state } from "../../core/store.js";
import { forgetSearch, recentSearches } from "./memory.js";

export const LIMIT = 8;
// Pause in the typing before the number of suggestions is announced (ms)
const ANNOUNCE_DELAY = 700;
// The last recent searches come first among equals
const RECENT_BONUS = 8;
const FOODS_URL = new URL("./aliments.json", import.meta.url).href;

// "Crème fraîche " → "creme fraiche"
export function normalize(text) {
    return String(text || "")
        .normalize("NFD")
        .replace(/[̀-ͯ]/g, "")
        .toLocaleLowerCase("fr")
        .replace(/[’']/g, "'")
        .replace(/\s+/g, " ")
        .trim();
}

// 0: starts with the text, 1: a word starts with it, 2: contains it, -1: no match
export function matchLevel(candidate, typed) {
    const c = normalize(candidate);
    const t = normalize(typed);
    if (!t) return 0;
    if (c.startsWith(t)) return 0;
    if (c.split(/[\s'-]+/).some((word, i) => i > 0 && word.startsWith(t))) return 1;
    return t.length >= 3 && c.includes(t) ? 2 : -1;
}

// Suggestions for `typed`: [{ value, source: "recent" | "list" | "food" }].
// sources: { recent: [{q, n, t}] (last first), list: ["farine", ...], foods: ["Lait", ...] (most common first) }
export function suggest(typed, { recent = [], list = [], foods = [] } = {}, limit = LIMIT) {
    const seen = new Map();
    const add = (value, source, frequency) => {
        const key = normalize(value);
        if (!key) return;
        const known = seen.get(key);
        if (!known) seen.set(key, { value: String(value).trim(), source, frequency });
        else known.frequency = Math.max(known.frequency, frequency);
    };
    recent.forEach((r, i) => add(r.q, "recent", 1000 + (r.n || 1) * 10 + (RECENT_BONUS - i)));
    // Without text: the recent searches only
    if (normalize(typed)) {
        list.forEach((q) => add(q, "list", 500));
        foods.forEach((f, i) => add(f, "food", 100 - (100 * i) / Math.max(1, foods.length)));
    }
    return [...seen.values()]
        .map((s) => ({ ...s, level: matchLevel(s.value, typed) }))
        .filter((s) => s.level >= 0)
        .sort(
            (a, b) =>
                a.level - b.level ||
                b.frequency - a.frequency ||
                a.value.length - b.value.length ||
                a.value.localeCompare(b.value, "fr"),
        )
        .slice(0, limit)
        .map(({ value, source }) => ({ value, source }));
}

// ---------------------------------------------------------------- the list under the field

let foods = [];
let foodsAsked = false;
let input = null;
let listbox = null;
let items = [];
let active = -1;
let announced = 0; // number of suggestions the screen readers last heard
let announceTimer = 0;

async function loadFoods() {
    if (foodsAsked) return;
    foodsAsked = true;
    try {
        const resp = await fetch(FOODS_URL, { headers: { "X-PrixMalin": "1" } });
        const data = resp.ok ? await resp.json() : [];
        foods = Array.isArray(data) ? data.filter((f) => typeof f === "string") : [];
        if (document.activeElement === input) update();
    } catch {
        foods = [];
    }
}

function sources() {
    return {
        recent: recentSearches(),
        list: (state.list || []).map((item) => item.query),
        foods,
    };
}

function isOpen() {
    return Boolean(listbox) && !listbox.hidden;
}

// « 3 suggestions, … » once the typing pauses, when the list opens or its length changes
export function suggestionsText(count) {
    return count ? `${plural(count, "suggestion")}, flèches haut et bas pour choisir` : "";
}

function announceCount() {
    clearTimeout(announceTimer);
    const count = isOpen() ? items.length : 0;
    if (count === announced) return;
    announceTimer = setTimeout(() => {
        announced = count;
        if (count) announce(suggestionsText(count));
    }, ANNOUNCE_DELAY);
}

// The current list was heard (or must not be announced again)
function heard() {
    clearTimeout(announceTimer);
    announced = isOpen() ? items.length : 0;
}

function close() {
    if (!listbox) return;
    listbox.hidden = true;
    items = [];
    active = -1;
    input.removeAttribute("aria-activedescendant");
    heard();
}

function place() {
    // Right under the field, from its left edge to the right edge of the form
    const form = listbox.parentElement;
    listbox.style.top = `${input.offsetTop + input.offsetHeight + 4}px`;
    listbox.style.left = `${input.offsetLeft}px`;
    listbox.style.width = `${Math.max(input.offsetWidth, form.clientWidth - input.offsetLeft)}px`;
}

function highlight(value, typed) {
    const t = normalize(typed);
    if (!t || !normalize(value).startsWith(t)) return value;
    // Accents do not count: cut after the letters that make the text typed
    let end = 1;
    while (end < value.length && normalize(value.slice(0, end)).length < t.length) end++;
    return html`<mark>${value.slice(0, end)}</mark>${value.slice(end)}`;
}

const SOURCE_TEXT = { recent: "recherche récente", list: "dans ma liste", food: "" };

function render() {
    const typed = input.value;
    setHtml(
        listbox,
        html`${items.map(
            (s, i) =>
                html`<li role="option" id="q-opt-${i}" class="suggestion-option" aria-selected="${i === active ? "true" : "false"}" data-index="${i}">${icon(
                    s.source === "recent" ? "clock" : s.source === "list" ? "list" : "search",
                )}<span class="suggestion-text">${highlight(s.value, typed)}</span>${
                    SOURCE_TEXT[s.source] && html`<span class="suggestion-source">${SOURCE_TEXT[s.source]}</span>`
                }</li>`,
        )}`,
    );
    if (active >= 0) {
        input.setAttribute("aria-activedescendant", `q-opt-${active}`);
        listbox.querySelector(`#q-opt-${active}`)?.scrollIntoView({ block: "nearest" });
    } else {
        input.removeAttribute("aria-activedescendant");
    }
}

function update() {
    if (!input || document.activeElement !== input) return;
    items = suggest(input.value, sources());
    active = -1;
    if (!items.length) {
        close();
        return;
    }
    place();
    listbox.hidden = false;
    render();
    announceCount();
}

function choose(index) {
    const s = items[index];
    if (!s) return;
    input.value = s.value;
    close();
    requestSearch(s.value);
}

function move(step) {
    if (!isOpen()) {
        update();
        if (!isOpen()) return;
    }
    const count = items.length;
    active = active < 0 ? (step > 0 ? 0 : count - 1) : (active + step + count) % count;
    render();
}

function onKey(e) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        move(e.key === "ArrowDown" ? 1 : -1);
    } else if (e.key === "Enter" && isOpen() && active >= 0) {
        e.preventDefault();
        choose(active);
    } else if (e.key === "Escape" && isOpen()) {
        e.preventDefault();
        close();
    } else if (e.key === "Delete" && isOpen() && active >= 0 && items[active].source === "recent") {
        e.preventDefault();
        const value = items[active].value;
        forgetSearch(value);
        announce(`« ${value} » retiré des recherches récentes`);
        const keep = active;
        update();
        heard(); // the removal is announced, not the new length
        if (items.length) {
            active = Math.min(keep, items.length - 1);
            render();
        }
    } else if (e.key === "Tab") {
        close();
    }
}

// Sets up the suggestions of #q (once; the field belongs to the page shell)
export function initAutocomplete() {
    input = document.getElementById("q");
    const form = document.getElementById("search-form");
    if (!input || !form || listbox) return;
    listbox = document.createElement("ul");
    listbox.id = "q-suggestions";
    listbox.className = "suggestions-list";
    listbox.setAttribute("role", "listbox");
    listbox.setAttribute("aria-label", "Suggestions");
    listbox.hidden = true;
    if (getComputedStyle(form).position === "static") form.style.position = "relative";
    form.append(listbox);
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-controls", "q-suggestions");

    input.addEventListener("focus", () => {
        loadFoods();
        update();
    });
    input.addEventListener("input", update);
    input.addEventListener("keydown", onKey);
    input.addEventListener("blur", () => setTimeout(() => document.activeElement !== input && close(), 150));
    // The field keeps the focus when a suggestion is clicked
    listbox.addEventListener("mousedown", (e) => e.preventDefault());
    listbox.addEventListener("click", (e) => {
        const option = e.target.closest("[role=option]");
        if (option) choose(Number(option.dataset.index));
    });
    window.addEventListener("resize", () => isOpen() && place());
    on("search:requested", close);
    on("route:changed", close);
}
