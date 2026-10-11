// Banner « Le navigateur PrixMalin est ouvert … J'ai terminé » (#setup-banner),
// shown while the user acts on a retailer site (area of P4).
//
// - visible while /api/browser says setup_mode, which is asked again every 3 s
//   (the setup may end on another device); hidden at the end;
// - its text depends on where the page is shown: on the PC itself the window
//   is right there, on a phone the user has to go to the PC (is_local);
// - from a phone, « Ouvrir le site » buttons of the other views
//   ([data-setup="<key>"]) ask for a confirmation first (the views of P4 use
//   openSite() of views/status/shared.js);
// - on a phone « J'ai terminé » stays at the bottom of the screen (css/stores.css);
// - starts the watch of the stores (automatic choice of the Courses U store,
//   store chosen on the site read back after « J'ai terminé ») and opens the
//   first-launch assistant (#/bienvenue) when nothing is set yet.

import { api } from "../core/api.js";
import { endSetup, on, setBrowser, state } from "../core/store.js";
import { checkOnboarding } from "../views/onboarding/index.js";
import { openSite, watchStores } from "../views/status/shared.js";

export const enabled = true;

export const POLL_MS = 3000;

const LOCAL_TEXT = "Le navigateur PrixMalin est ouvert : faites vos réglages sur le site, puis appuyez sur";
const REMOTE_TEXT =
    "La page est ouverte sur l'ordinateur où tourne PrixMalin : allez-y pour valider la vérification ou choisir le magasin, puis appuyez ici sur";

let timer = null;

async function poll() {
    try {
        const status = await api("/api/browser", { timeout: 10000 });
        const was = state.browser || {};
        if (status.setup_mode !== was.setup_mode || status.running !== was.running) setBrowser(status);
    } catch {
        /* offline: the offline banner says so; asked again later */
    }
}

function render() {
    const banner = document.getElementById("setup-banner");
    if (!banner) return;
    const shown = Boolean(state.browser && state.browser.setup_mode);
    banner.hidden = !shown;
    document.body.classList.toggle("has-setup-banner", shown);
    const text = banner.querySelector("span");
    if (text) text.textContent = state.browser && state.browser.is_local === false ? REMOTE_TEXT : LOCAL_TEXT;
    measure();
    if (shown && !timer) {
        timer = setInterval(poll, POLL_MS);
    } else if (!shown && timer) {
        clearInterval(timer);
        timer = null;
    }
}

// Height of the banner (fixed at the bottom on a phone): the page and the
// messages are moved above it (css/stores.css)
function measure() {
    const banner = document.getElementById("setup-banner");
    if (!banner || banner.hidden) return;
    document.documentElement.style.setProperty("--setup-banner-h", `${banner.offsetHeight}px`);
}

// « Ouvrir le site » of the other views, from a phone: confirm before opening
function interceptRemoteSetup(e) {
    const target = e.target.closest ? e.target.closest("[data-setup]") : null;
    if (!target || !target.dataset.setup) return;
    if (!(state.browser && state.browser.is_local === false)) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    openSite(target.dataset.setup);
}

function initDoneButton() {
    const done = document.getElementById("setup-banner-done");
    if (!done) return;
    done.dataset.testid = "setup-done";
    done.addEventListener("click", async () => {
        done.disabled = true;
        try {
            await endSetup();
        } finally {
            done.disabled = false;
        }
    });
}

export function init() {
    initDoneButton();
    document.addEventListener("click", interceptRemoteSetup, true);
    on("browser:changed", render);
    window.addEventListener("resize", measure);
    watchStores();
    render();
    // Once the first view is shown (the router is started)
    const off = on("route:changed", () => {
        off();
        checkOnboarding();
    });
}
