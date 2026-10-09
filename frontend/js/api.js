// JSON helper for the PrixMalin API: throws an Error carrying the French
// message of the server ("detail") when the response is not OK.

export async function api(path, options = {}) {
    const resp = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options,
        body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
    if (resp.status === 204) return null;
    const data = await resp.json().catch(() => null);
    if (!resp.ok) {
        const detail = data && data.detail;
        const message = Array.isArray(detail) ? detail.map((d) => d.msg).join(", ") : detail;
        throw new Error(message || `Erreur serveur (${resp.status})`);
    }
    return data;
}
