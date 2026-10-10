// Calls to the PrixMalin server.
//
//   const items = await api("/api/list");
//   await api("/api/list", { method: "POST", body: { query: "farine" } });
//
// Returns the JSON answer (null for 204) or throws an ApiError
// { status, code, message } whose message is in French and can be shown as is.
// Options: method, body (sent as JSON), signal (AbortSignal), timeout (ms).
// Every request carries the header « X-PrixMalin: 1 ».
// Events: "api:offline" (the server does not answer), "api:online" (it answers
// again), "api:unauthorized" (HTTP 401).

import { emit } from "./events.js";

export class ApiError extends Error {
    constructor(status, code, message) {
        super(message);
        this.name = "ApiError";
        this.status = status;
        this.code = code;
    }
}

const OFFLINE_MESSAGE = "PrixMalin ne répond pas. Vérifiez qu'il est toujours lancé sur le PC.";
const TIMEOUT_MESSAGE = "PrixMalin met trop de temps à répondre. Réessayez dans un instant.";

let offline = false;

function setOffline(value) {
    if (offline === value) return;
    offline = value;
    emit(value ? "api:offline" : "api:online");
}

export function isOffline() {
    return offline;
}

export async function api(path, { method = "GET", body, signal, timeout } = {}) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (signal) {
        if (signal.aborted) controller.abort();
        else signal.addEventListener("abort", abort, { once: true });
    }
    let timedOut = false;
    const timer = timeout
        ? setTimeout(() => {
              timedOut = true;
              controller.abort();
          }, timeout)
        : null;

    let resp;
    try {
        resp = await fetch(path, {
            method,
            headers: { "Content-Type": "application/json", "X-PrixMalin": "1" },
            body: body !== undefined ? JSON.stringify(body) : undefined,
            signal: controller.signal,
        });
    } catch {
        if (timedOut) throw new ApiError(0, "timeout", TIMEOUT_MESSAGE);
        if (signal && signal.aborted) throw new ApiError(0, "aborted", "Requête annulée");
        setOffline(true);
        throw new ApiError(0, "offline", OFFLINE_MESSAGE);
    } finally {
        clearTimeout(timer);
        if (signal) signal.removeEventListener("abort", abort);
    }
    setOffline(false);
    if (resp.status === 401) emit("api:unauthorized", { path });
    if (resp.status === 204) return null;
    const data = await resp.json().catch(() => null);
    if (!resp.ok) {
        const detail = data && data.detail;
        const message = Array.isArray(detail) ? detail.map((d) => d.msg).join(", ") : detail;
        const code = (data && data.code) || `http_${resp.status}`;
        throw new ApiError(resp.status, code, message || `Erreur serveur (${resp.status})`);
    }
    return data;
}
