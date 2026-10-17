// Sheets of « Ma liste », « Panier » and « En magasin »: a modal <dialog>, at
// the bottom of the screen on a phone (styles: .p5-sheet in css/list.css).
//
//   const sheet = openSheet({ id: "edit-sheet", title: "Modifier « farine »", body: html`…` });
//   sheet.content            the element under the title (event delegation)
//   sheet.update(html`…`)    new content
//   sheet.close()
//
// Escape, the « Fermer » button and a click outside close it; the focus then
// goes back to the button that opened it (found again by its data-focus when
// the page was drawn again meanwhile).

import { html, setHtml } from "../../core/html.js";
import { icon } from "../../core/icons.js";

export function openSheet({ id, title, body, onClose = null }) {
    document.getElementById(id)?.close();
    const opener = document.activeElement;
    const focusKey = opener && opener.dataset ? opener.dataset.focus : null;
    const dialog = document.createElement("dialog");
    dialog.className = "p5-sheet";
    dialog.id = id;
    dialog.dataset.testid = id;
    dialog.setAttribute("aria-labelledby", `${id}-title`);
    setHtml(
        dialog,
        html`<div class="p5-sheet-box">
            <div class="p5-sheet-head">
                <h2 id="${id}-title" class="p5-sheet-title">${title}</h2>
                <button type="button" class="p5-sheet-close" data-close aria-label="Fermer">${icon("x")}</button>
            </div>
            <div class="p5-sheet-content">${body}</div>
        </div>`,
    );
    document.body.append(dialog);
    const content = dialog.querySelector(".p5-sheet-content");
    dialog.addEventListener("click", (e) => {
        if (e.target === dialog || e.target.closest("[data-close]")) dialog.close();
    });
    dialog.addEventListener("close", () => {
        dialog.remove();
        if (onClose) onClose();
        let back = opener;
        if ((!back || !back.isConnected) && focusKey) {
            back = document.querySelector(`[data-focus="${CSS.escape(focusKey)}"]`);
        }
        if (back && back.isConnected && typeof back.focus === "function") {
            back.focus({ preventScroll: true });
            back.scrollIntoView({ block: "nearest" });
        }
    });
    dialog.showModal();
    return {
        dialog,
        content,
        update(markup) {
            setHtml(content, markup);
        },
        close() {
            if (dialog.open) dialog.close();
        },
        get open() {
            return dialog.isConnected && dialog.open;
        },
    };
}
