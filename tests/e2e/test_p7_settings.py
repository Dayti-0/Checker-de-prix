"""Réglages › Sécurité, Mes données, Sur le téléphone, À propos (P7), the access code screen and the update banner."""

import json
import re

import pytest
from playwright.sync_api import expect

from backend import __version__, instance, security
from backend.api import updates
from tests.e2e.axe import assert_accessible
from tests.e2e.conftest import CSP_WATCH

SECTIONS = ("security", "data", "phone", "about")
SCALES = [0.9, 1, 1.25, 1.6]


@pytest.fixture(params=["desktop", "dark", "mobile"])
def page(request):
    return request.getfixturevalue(request.param)


@pytest.fixture(autouse=True)
def network(monkeypatch):
    """A fixed address on the Wi-Fi, a fake GitHub (never reached by the tests)."""
    monkeypatch.setattr(instance, "lan_ips", lambda: ["192.168.1.10"])

    async def latest():
        return "9.0.0", "https://github.com/Dayti-0/Checker-de-prix/releases/tag/v9.0.0"

    monkeypatch.setattr(updates, "fetch_latest", latest)
    monkeypatch.setattr(security, "attempts", security.Attempts())


def section(page, name):
    return page.locator(f"[data-section={name}]")


def open_settings(page):
    page.goto(f"{page.base}/#/reglages")
    for name in SECTIONS:
        expect(section(page, name)).to_be_visible()
    expect(section(page, "security").get_by_test_id("access-code-value")).to_have_text(re.compile(r"^\d{3} \d{3}$"))
    expect(section(page, "phone").get_by_test_id("phone-url")).to_be_visible()
    expect(section(page, "about").get_by_test_id("update-state")).to_be_visible()
    expect(section(page, "data").get_by_test_id("copies-info")).not_to_be_empty()


def test_sections_are_accessible(page):
    open_settings(page)
    assert_accessible(page, "réglages P7")


def test_security_section(desktop):
    page = desktop
    open_settings(page)
    sec = section(page, "security")
    expect(sec.get_by_role("heading", name="Sécurité")).to_be_visible()
    code = sec.get_by_test_id("access-code-value")
    expect(code).to_have_text(security.code_text(security.access_secret().code))
    old = code.inner_text()
    page.once("dialog", lambda dialog: dialog.accept())
    sec.get_by_role("button", name="Changer le code").click()
    expect(code).not_to_have_text(old)
    expect(code).to_have_text(security.code_text(security.access_secret().code))
    expect(page.locator("#toast")).to_contain_text("Nouveau code d'accès")

    switch = sec.get_by_role("checkbox", name="Autoriser l'accès depuis le téléphone")
    expect(switch).to_be_checked()
    expect(sec.get_by_test_id("lan-state")).to_contain_text("Un téléphone sur le même Wi-Fi peut ouvrir PrixMalin")
    switch.click()
    expect(sec.get_by_test_id("lan-state")).to_contain_text("ne pourra plus se connecter au prochain démarrage")
    expect(code).to_be_hidden()
    expect(section(page, "phone")).to_be_visible()
    sec.get_by_role("checkbox", name="Autoriser l'accès depuis le téléphone").click()
    expect(sec.get_by_test_id("lan-state")).to_contain_text("Un téléphone sur le même Wi-Fi")
    expect(code).to_be_visible()


def test_phone_section(page):
    page.goto(f"{page.base}/#/reglages")
    phone = section(page, "phone")
    port = page.base.rsplit(":", 1)[1]
    expect(phone.get_by_test_id("phone-url")).to_have_text(f"http://192.168.1.10:{port}")
    qr = phone.get_by_role("img", name=f"QR code de l'adresse http://192.168.1.10:{port}")
    expect(qr).to_be_visible()
    page.wait_for_function("img => img.complete && img.naturalWidth > 0", arg=qr.element_handle())
    expect(phone).to_contain_text("pare-feu Windows")
    guide = phone.get_by_role("link", name=re.compile("^Aide : téléphone, HTTPS"))
    expect(guide).to_have_attribute("href", re.compile(r"docs/acces-telephone\.md$"))
    expect(guide).to_have_attribute("target", "_blank")


def test_phone_section_lists_the_other_addresses(desktop, monkeypatch):
    """A VPN on the PC: the address of the Wi-Fi first, the others below."""
    monkeypatch.setattr(instance, "lan_ips", lambda: ["192.168.1.10", "10.5.0.2"])
    page = desktop
    page.goto(f"{page.base}/#/reglages")
    port = page.base.rsplit(":", 1)[1]
    phone = section(page, "phone")
    expect(phone.get_by_test_id("phone-url")).to_have_text(f"http://192.168.1.10:{port}")
    expect(phone.get_by_test_id("phone-others")).to_have_text(
        f"Autres adresses de ce PC, si celle-ci ne marche pas : http://10.5.0.2:{port}"
    )


def test_data_section_backup_and_restore(desktop, tmp_path):
    page = desktop
    page.request.post(f"{page.base}/api/list", data={"query": "Confiture d'abricots", "quantity": 2})
    page.goto(f"{page.base}/#/reglages")
    data = section(page, "data")
    with page.expect_download() as download:
        data.get_by_role("link", name="Enregistrer une sauvegarde").click()
    saved = download.value
    assert re.fullmatch(r"prixmalin-sauvegarde-\d{4}-\d{2}-\d{2}\.json", saved.suggested_filename)
    path = tmp_path / saved.suggested_filename
    saved.save_as(path)
    backup = json.loads(path.read_text(encoding="utf-8"))
    assert backup["format"] == "prixmalin"
    assert [i["query"] for i in backup["sections"]["shopping_list"]] == ["Confiture d'abricots"]

    page.request.delete(f"{page.base}/api/list")
    page.request.post(f"{page.base}/api/list", data={"query": "Miel"})
    expect(data.get_by_test_id("restore-name")).to_have_text("Aucun fichier choisi")
    data.get_by_label("Restaurer une sauvegarde").set_input_files(str(path))
    expect(data.get_by_test_id("restore-name")).to_have_text(path.name)
    data.get_by_role("button", name="Restaurer ce fichier").click()
    expect(data.get_by_test_id("restore-result")).to_have_text("Sauvegarde ajoutée à vos données.")
    expect(data.get_by_test_id("restore-name")).to_have_text("Aucun fichier choisi")
    queries = sorted(i["query"] for i in page.request.get(f"{page.base}/api/list").json())
    assert queries == ["Confiture d'abricots", "Miel"]

    # Replace, after a confirmation
    data.get_by_label("Restaurer une sauvegarde").set_input_files(str(path))
    data.get_by_role("radio", name="Les remplacer par la sauvegarde").check()
    page.once("dialog", lambda dialog: dialog.accept())
    data.get_by_role("button", name="Restaurer ce fichier").click()
    expect(data.get_by_test_id("restore-result")).to_have_text("Sauvegarde restaurée.")
    assert [i["query"] for i in page.request.get(f"{page.base}/api/list").json()] == ["Confiture d'abricots"]

    # Not a backup
    bad = tmp_path / "notes.json"
    bad.write_text("pas une sauvegarde", encoding="utf-8")
    data.get_by_label("Restaurer une sauvegarde").set_input_files(str(bad))
    data.get_by_role("button", name="Restaurer ce fichier").click()
    expect(data.get_by_test_id("restore-result")).to_have_text("Ce fichier n'est pas une sauvegarde de PrixMalin.")


def test_about_section_and_update_banner(desktop):
    page = desktop
    page.goto(f"{page.base}/#/reglages")
    about = section(page, "about")
    expect(about.get_by_test_id("app-version")).to_have_text(__version__)
    expect(about.get_by_test_id("update-state")).to_have_text("Aucune vérification pour l'instant.")
    expect(page.get_by_test_id("update-banner")).to_have_count(0)
    about.get_by_role("button", name="Vérifier maintenant").click()
    expect(about.get_by_test_id("update-state")).to_have_text(
        f"Nouvelle version 9.0.0 disponible (vous avez la {__version__})."
    )
    banner = page.get_by_test_id("update-banner")
    expect(banner).to_contain_text("Nouvelle version 9.0.0 de PrixMalin disponible")
    expect(banner.get_by_role("link", name="Nouveautés de la version 9.0.0 (nouvel onglet)")).to_have_attribute(
        "href", "https://github.com/Dayti-0/Checker-de-prix/releases/tag/v9.0.0"
    )
    assert_accessible(page, "bandeau de mise à jour")
    # Shown again at the next load, until « Plus tard »
    page.reload()
    expect(page.get_by_test_id("update-banner")).to_be_visible()
    page.get_by_test_id("update-banner").get_by_role("button", name="Plus tard").click()
    expect(page.get_by_test_id("update-banner")).to_have_count(0)
    page.reload()
    expect(section(page, "about").get_by_test_id("update-state")).to_contain_text("Nouvelle version 9.0.0")
    expect(page.get_by_test_id("update-banner")).to_have_count(0)

    switch = section(page, "about").get_by_role("checkbox", name="Rechercher une nouvelle version une fois par jour")
    expect(switch).to_be_checked()
    switch.click()
    expect(section(page, "about").get_by_role("checkbox", name=re.compile("une fois par jour"))).not_to_be_checked()


def test_finger_sized_targets(mobile):
    page = mobile
    open_settings(page)
    for name in SECTIONS:
        targets = section(page, name).locator("button:visible, a:visible, label.switch:visible, .sys-modes label")
        for i in range(targets.count()):
            box = targets.nth(i).bounding_box()
            assert box and box["height"] >= 44, (name, targets.nth(i).inner_text(), box)


@pytest.mark.parametrize("width", [360, 390])
def test_no_horizontal_scroll(chromium, server, width):
    for scale in SCALES:
        context = chromium.new_context(locale="fr-FR", viewport={"width": width, "height": 780}, is_mobile=True)
        context.add_init_script(CSP_WATCH)
        context.add_init_script(f"localStorage.setItem('prixmalin.textScale', '{scale}')")
        page = context.new_page()
        errors = []
        page.on("console", lambda m, errors=errors: errors.append(m.text) if m.type == "error" else None)
        page.base = server
        open_settings(page)
        wide = page.evaluate(
            """(ids) => ids.filter((id) => {
                const el = document.querySelector(`[data-section=${id}]`);
                return el.scrollWidth > el.clientWidth || el.getBoundingClientRect().right > innerWidth;
            })""",
            list(SECTIONS),
        )
        assert wide == [], (width, scale, wide)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, scale)
        assert errors == [], errors
        context.close()


# --- access code screen (a device other than the PC) ------------------------------------


@pytest.fixture
def phone(chromium, server):
    """A page seen by the server as a phone of the Wi-Fi (X-Forwarded-For, see backend/security.py)."""
    context = chromium.new_context(
        locale="fr-FR",
        viewport={"width": 390, "height": 844},
        is_mobile=True,
        has_touch=True,
        extra_http_headers={"X-Forwarded-For": "192.168.1.20"},
    )
    context.add_init_script(CSP_WATCH)
    page = context.new_page()
    page.base = server
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: page.errors.append(m.text) if m.type == "error" else None)
    yield page
    context.close()


def refusals_only(errors):
    """The browser reports the refused requests (401 before the code, 403 for a wrong code) in its console."""
    return [e for e in errors if not re.search(r"status of 40[13]", e)]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_access_code_screen(phone, theme):
    page = phone
    page.emulate_media(color_scheme=theme)
    page.goto(f"{page.base}/#/")
    dialog = page.get_by_role("dialog", name="Code d'accès")
    expect(dialog).to_be_visible()
    field = dialog.get_by_label("Code à 6 chiffres")
    expect(field).to_be_focused()
    assert_accessible(page, f"code d'accès ({theme})")

    page.keyboard.press("Escape")  # cannot be dismissed
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Valider").click()
    expect(dialog.locator("#access-error")).to_have_text("Saisissez le code à 6 chiffres affiché sur le PC.")
    expect(field).to_have_attribute("aria-invalid", "true")

    code = security.access_secret().code
    field.fill(str((int(code) + 1) % 10**6).zfill(6))
    dialog.get_by_role("button", name="Valider").click()
    expect(dialog.locator("#access-error")).to_have_text("Code incorrect. Vérifiez le code affiché sur le PC.")

    field.fill(f"{code[:3]} {code[3:]}")
    with page.expect_navigation():
        dialog.get_by_role("button", name="Valider").click()
    expect(page.get_by_role("dialog", name="Code d'accès")).to_have_count(0)
    expect(page.get_by_role("link", name="Réglages").first).to_be_visible()
    cookies = {c["name"]: c for c in page.context.cookies()}
    assert cookies[security.ACCESS_COOKIE]["httpOnly"] is True
    assert cookies[security.ACCESS_COOKIE]["sameSite"] == "Strict"
    assert refusals_only(page.errors) == []

    # Réglages on the phone: no code shown, a line instead
    page.goto(f"{page.base}/#/reglages")
    expect(section(page, "security").get_by_test_id("security-remote")).to_contain_text("Cet appareil a accès")
    expect(section(page, "security").get_by_test_id("access-code-value")).to_have_count(0)
    assert refusals_only(page.errors) == []


def test_access_code_js_helpers(desktop):
    from tests.e2e.helpers import js_eval

    page = desktop
    page.goto(f"{page.base}/#/")
    module = "/static/js/features/access-code.js"
    assert js_eval(page, module, "normalizeCode", " 123 456 ") == "123456"
    assert js_eval(page, module, "codeProblem", "12345") == "Le code compte 6 chiffres."
    assert js_eval(page, module, "codeProblem", "123456") == ""
    about = "/static/js/views/settings/sections/about.js"
    assert js_eval(page, about, "updateText", {"available": False, "checked_at": None}) == (
        "Aucune vérification pour l'instant."
    )
    banner = "/static/js/features/update-banner.js"
    assert js_eval(page, banner, "shouldShow", {"available": True, "latest": "9.0.0"}, "9.0.0") is False
    assert js_eval(page, banner, "shouldShow", {"available": True, "latest": "9.0.0"}, None) is True
    data = "/static/js/views/settings/sections/data.js"
    assert js_eval(page, data, "restoredText", {"mode": "replace", "ignored": ["x", "y"]}) == (
        "Sauvegarde restaurée. 2 parties inconnues de cette version ont été ignorées."
    )
