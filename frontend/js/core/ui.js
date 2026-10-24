// Messages to the user.
//
//   notify("Ajouté à votre liste")
//   notify("Liste vidée", { action: { label: "Annuler", onClick: restore } })
//   notify(err.message, { type: "error" })          // shown longer, in red
//   announce("5 enseignes ont répondu")              // screen readers only
//   if (await confirmDialog({ message: "Vider toute la liste ?", danger: true })) ...

let toastTimer = null;

// Message at the bottom of the screen (#toast in #toast-region)
export function notify(message, { type = "info", action = null, duration } = {}) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = message;
    if (action) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "toast-action";
        button.textContent = action.label;
        button.addEventListener("click", () => {
            el.hidden = true;
            action.onClick();
        });
        el.append(" ", button);
    }
    el.classList.toggle("error", type === "error");
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(
        () => {
            el.hidden = true;
        },
        duration ?? (type === "error" ? 6000 : 3000),
    );
}

// Text read by screen readers (#live-region), without anything shown
export function announce(text) {
    const el = document.getElementById("live-region");
    if (!el) return;
    el.textContent = "";
    // A new text node is announced even when the text is the same as before
    setTimeout(() => {
        el.textContent = text;
    }, 50);
}

// Asks for a confirmation; resolves to true or false.
// Options: title, message, confirmLabel, danger (the browser dialog only shows the message).
export function confirmDialog({ title = "", message = "" } = {}) {
    return Promise.resolve(window.confirm(message || title));
}
