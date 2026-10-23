// Settings › Sur le téléphone: address of PrixMalin on the Wi-Fi and its QR code (area of P7).
//
// GET /api/system/phone gives the address (real address of the PC on the
// network, port of this page) and whether a QR code can be drawn
// (/api/system/phone-qr.svg). Reminders: same Wi-Fi, access code, Windows
// firewall and « private » network; link to the guide (HTTPS, 4G).

import { api } from "../../../core/api.js";
import { html, setHtml } from "../../../core/html.js";

export const id = "phone";
export const title = "Sur le téléphone";
export const order = 70;
export const enabled = true;

export const GUIDE_URL = "https://github.com/Dayti-0/Checker-de-prix/blob/main/docs/acces-telephone.md";

// Why the phone cannot connect, or "" when it can
export function phoneProblem(info) {
    if (!info.allow_lan) return "L'accès depuis le téléphone est désactivé : activez-le dans Réglages › Sécurité, puis relancez PrixMalin.";
    if (!info.lan_active) return "PrixMalin ne s'ouvre que sur ce PC pour l'instant : relancez-le pour que le téléphone puisse se connecter.";
    if (!info.url) return "Ce PC n'est relié à aucun réseau Wi-Fi ou filaire : le téléphone ne peut pas s'y connecter.";
    return "";
}

function view(info) {
    const problem = phoneProblem(info);
    const guide = html`<p class="small"><a class="sys-target" href="${GUIDE_URL}" target="_blank" rel="noopener noreferrer">Aide : téléphone, HTTPS et accès en 4G (nouvel onglet)</a></p>`;
    if (problem) return html`<p class="small" data-testid="phone-problem">${problem}</p>${guide}`;
    return html`
        ${!info.local && html`<p class="small">Vous utilisez déjà PrixMalin sur cet appareil. Pour l'ouvrir d'un geste, ajoutez cette page à l'écran d'accueil (menu du navigateur).</p>`}
        <div class="sys-phone">
            ${info.qr && html`<img class="sys-qr" src="/api/system/phone-qr.svg" width="160" height="160" alt="QR code de l'adresse ${info.url}" data-testid="phone-qr">`}
            <div class="sys-phone-text">
                <p class="sys-url" data-testid="phone-url">${info.url}</p>
                <ol class="sys-steps">
                    <li>Connectez le téléphone au même Wi-Fi que le PC.</li>
                    <li>${info.qr ? "Scannez ce QR code avec l'appareil photo, ou tapez l'adresse dans le navigateur." : "Tapez cette adresse dans le navigateur du téléphone."}</li>
                    <li>Saisissez le code d'accès affiché dans Réglages › Sécurité.</li>
                </ol>
            </div>
        </div>
        <p class="muted small">La page ne s'ouvre pas sur le téléphone ? Sur le PC, dans le pare-feu Windows, autorisez Python sur les réseaux privés, et réglez le Wi-Fi en réseau « privé » (Paramètres › Réseau et Internet).</p>
        ${guide}`;
}

export function render(el) {
    let alive = true;
    setHtml(el, html`<p class="muted small">Chargement…</p>`);
    api("/api/system/phone")
        .then((info) => {
            if (alive) setHtml(el, view(info));
        })
        .catch((err) => {
            if (alive) setHtml(el, html`<p class="notice warn">${err.message}</p>`);
        });
    return () => {
        alive = false;
    };
}
