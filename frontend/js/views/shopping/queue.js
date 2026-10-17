// Ticks of the mode « En magasin » waiting for the network (B64): kept in
// localStorage (an open tab survives a loss of network, and a reload), sent with
// POST /api/list/checks; the server keeps the most recent tick of each item.

import { api } from "../../core/api.js";
import { readJson, writeJson } from "../list/data.js";
import { mergeCheck } from "../list/model.js";

const KEY = "prixmalin.pendingChecks";

export function pending() {
    const queue = readJson(KEY, []);
    return Array.isArray(queue) ? queue : [];
}

export function queueCheck(id, checked) {
    const check = { id, checked, checked_at: Date.now() / 1000 };
    writeJson(KEY, mergeCheck(pending(), check));
    return check;
}

let sending = null;

// Sends the waiting ticks: true when the server took them (or none was
// waiting), false when it could not be reached. A tick made while a request is
// on its way is sent right after it.
export function flush() {
    if (sending) return sending.then(() => flush());
    sending = (async () => {
        const queue = pending();
        if (!queue.length) return true;
        try {
            await api("/api/list/checks", { method: "POST", body: { checks: queue }, timeout: 10000 });
        } catch {
            return false;
        }
        // Ticks made while sending stay in the queue
        const sent = new Map(queue.map((c) => [c.id, c.checked_at]));
        writeJson(
            KEY,
            pending().filter((c) => sent.get(c.id) !== c.checked_at),
        );
        return true;
    })().finally(() => {
        sending = null;
    });
    return sending;
}
