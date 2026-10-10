// Event bus of the app (re-exported by core/store.js: import { on, emit } from "./store.js").
//
// on(event, fn) returns the function that removes the listener; "*" listens
// to every event (fn receives (data, event)). A listener that throws does
// not stop the others.

const listeners = new Map();

export function on(event, fn) {
    if (!listeners.has(event)) listeners.set(event, new Set());
    listeners.get(event).add(fn);
    return () => listeners.get(event)?.delete(fn);
}

export function emit(event, data) {
    const fns = [...(listeners.get(event) || [])];
    if (event !== "*") fns.push(...(listeners.get("*") || []));
    for (const fn of fns) {
        try {
            fn(data, event);
        } catch (err) {
            console.error(err);
        }
    }
}
