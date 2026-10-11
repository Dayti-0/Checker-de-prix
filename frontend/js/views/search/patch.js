// Updates a part of the page without rebuilding what did not change (B28):
// the focus, the scroll position and the loaded images stay where they are.
//
//   patch(container, html`<li data-key="a">…</li><li data-key="b">…</li>`)
//
// The children of `container` are matched by their data-key (else by their
// position). A child whose markup is unchanged is kept as it is; a child that
// carries data-patch keeps its element and has its own children patched the
// same way; any other changed child is replaced. When the focused element is
// replaced, the element of the new markup with the same id or data-focus is
// focused instead.

import { setHtml } from "../../core/html.js";

const SOURCE = Symbol("source");

function keyOf(el, index) {
    return el.dataset.key || `@${el.tagName}:${index}`;
}

function remember(el) {
    el[SOURCE] = el.outerHTML;
    for (const child of el.querySelectorAll("*")) child[SOURCE] = child.outerHTML;
}

function syncAttributes(target, source) {
    for (const { name } of [...target.attributes]) {
        if (!source.hasAttribute(name) && name !== "style") target.removeAttribute(name);
    }
    for (const { name, value } of source.attributes) {
        if (target.getAttribute(name) !== value) target.setAttribute(name, value);
    }
}

function patchChildren(parent, source) {
    const old = new Map();
    [...parent.children].forEach((el, i) => old.set(keyOf(el, i), el));
    let cursor = parent.firstElementChild;
    [...source.children].forEach((fresh, i) => {
        const key = keyOf(fresh, i);
        let el = old.get(key);
        old.delete(key);
        if (el && el.tagName === fresh.tagName && fresh.hasAttribute("data-patch")) {
            syncAttributes(el, fresh);
            patchChildren(el, fresh);
        } else if (!el || el[SOURCE] !== fresh.outerHTML) {
            remember(fresh);
            if (el) {
                if (cursor === el) cursor = fresh;
                el.replaceWith(fresh);
            }
            el = fresh;
        }
        if (el === cursor) cursor = el.nextElementSibling;
        else parent.insertBefore(el, cursor);
    });
    while (cursor) {
        const next = cursor.nextElementSibling;
        cursor.remove();
        cursor = next;
    }
}

// How to find the focused element again in the new markup
function focusSelector(el) {
    if (!el || el === document.body) return null;
    if (el.id) return `#${CSS.escape(el.id)}`;
    if (el.dataset && el.dataset.focus) return `[data-focus="${CSS.escape(el.dataset.focus)}"]`;
    return null;
}

export function patch(container, markup) {
    const template = document.createElement("template");
    setHtml(template, markup);
    const active = document.activeElement;
    const inside = active && container.contains(active);
    const selector = inside ? focusSelector(active) : null;
    patchChildren(container, template.content);
    if (inside && document.activeElement !== active) {
        const target = (active.isConnected && container.contains(active) && active) ||
            (selector && container.querySelector(selector));
        if (target && typeof target.focus === "function") target.focus({ preventScroll: true });
    }
}
