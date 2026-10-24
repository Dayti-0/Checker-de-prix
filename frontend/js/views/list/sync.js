// The list changed on another device (B70): while a page of the list is shown
// and visible, GET /api/list/version every 10 s; a new version reloads the list
// (event "list:changed").
//
//   const stop = watchList();   // in render(), stop() in destroy()

import { api } from "../../core/api.js";
import { loadList } from "../../core/store.js";

export const SYNC_INTERVAL_MS = 10000;

let users = 0;
let timer = null;
let known = null;
let busy = false;

async function check() {
    if (busy || document.visibilityState !== "visible" || navigator.onLine === false) return;
    busy = true;
    try {
        const { version } = await api("/api/list/version", { timeout: 8000 });
        if (known !== null && version !== known) await loadList();
        known = version;
    } catch {
        /* the server does not answer: next time */
    } finally {
        busy = false;
    }
}

function onVisible() {
    if (document.visibilityState === "visible") check();
}

export function watchList() {
    users += 1;
    if (users === 1) {
        check();
        timer = setInterval(check, SYNC_INTERVAL_MS);
        document.addEventListener("visibilitychange", onVisible);
        window.addEventListener("focus", onVisible);
    }
    let stopped = false;
    return () => {
        if (stopped) return;
        stopped = true;
        users -= 1;
        if (users === 0) {
            clearInterval(timer);
            timer = null;
            document.removeEventListener("visibilitychange", onVisible);
            window.removeEventListener("focus", onVisible);
        }
    };
}
