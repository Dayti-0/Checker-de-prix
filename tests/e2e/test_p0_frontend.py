"""B03, B07: contracts of the frontend (routes, navigation, core modules, extension points)."""

import re

from playwright.sync_api import expect

from tests.e2e.helpers import js_eval

ROUTE_PATHS = [
    "/",
    "/recherche",
    "/liste",
    "/panier",
    "/courses",
    "/suivis",
    "/historique",
    "/produit/:store/:key",
    "/reglages",
    "/etat",
    "/bienvenue",
]


def test_routes_table(desktop):
    page = desktop
    page.goto(page.base)
    routes = page.evaluate(
        """async () => (await import("/static/js/routes.js")).ROUTES.map(
            (r) => ({path: r.path, enabled: r.view.enabled !== false, nav: r.view.nav ? r.view.nav.label : null}))"""
    )
    assert [r["path"] for r in routes] == ROUTE_PATHS
    enabled = {r["path"]: r["nav"] for r in routes if r["enabled"]}
    # P4 fills #/etat and #/bienvenue, P5 #/panier and #/courses (no entry in the navigation)
    assert enabled == {
        "/": "Rechercher",
        "/recherche": None,
        "/liste": "Ma liste",
        "/panier": None,
        "/courses": None,
        "/reglages": "Réglages",
        "/etat": None,
        "/bienvenue": None,
    }


def test_hidden_routes_lead_to_the_home_page(desktop):
    page = desktop
    for path in ("/suivis", "/historique", "/produit/aldi/123", "/x"):
        page.goto(f"{page.base}/#{path}")
        expect(page).to_have_url(f"{page.base}/#/")
        expect(page.get_by_text("Tapez un produit pour comparer")).to_be_visible()
    # Without a query, the results page is the home page
    page.goto(f"{page.base}/#/recherche")
    expect(page).to_have_url(f"{page.base}/#/")


def test_navigation_follows_the_route(desktop):
    page = desktop
    page.goto(page.base)
    nav = page.get_by_role("navigation", name="Navigation principale")
    expect(nav.get_by_role("link")).to_have_text(["Rechercher", "Ma liste 0", "Réglages"])
    expect(nav.locator("[aria-current=page]")).to_have_text("Rechercher")
    box = page.get_by_role("searchbox", name="Produit à rechercher")
    box.fill("farine")
    box.press("Enter")
    expect(nav.locator("[aria-current=page]")).to_have_text("Rechercher")
    nav.get_by_role("link", name=re.compile("Ma liste")).click()
    expect(nav.locator("[aria-current=page]")).to_have_text(re.compile("Ma liste"))
    expect(page.get_by_role("searchbox")).to_be_hidden()
    # « Rechercher » goes back to the last search
    expect(nav.get_by_role("link", name="Rechercher")).to_have_attribute("href", "#/recherche?q=farine")
    nav.get_by_role("link", name="Réglages").click()
    expect(page.locator("#store-filters")).to_be_hidden()


def test_nav_links_are_not_rebuilt_by_updates(desktop):
    """A click on a link is not lost while the badges update (links kept, not redrawn)."""
    page = desktop
    page.goto(page.base)
    link = page.get_by_role("link", name=re.compile("Ma liste"))
    expect(link).to_be_visible()
    page.evaluate(
        """async () => {
            const { emit } = await import("/static/js/core/store.js");
            window.__link = document.querySelector("[data-nav=list]");
            for (let i = 0; i < 50; i++) emit("list:changed");
            window.__storm = setInterval(() => emit("list:changed"), 1);
        }"""
    )
    assert page.evaluate(
        "() => window.__link === document.querySelector('[data-nav=list]') && window.__link.isConnected"
    )
    for _ in range(5):
        link.click()
        expect(page).to_have_url(f"{page.base}/#/liste")
        page.get_by_role("link", name="Rechercher").click()
        expect(page).to_have_url(f"{page.base}/#/")
    page.evaluate("() => clearInterval(window.__storm)")
    assert page.evaluate("() => window.__link.isConnected")


def test_html_helpers(desktop):
    page = desktop
    page.goto(page.base)
    rendered = page.evaluate(
        """async () => {
            const { html, raw, attr, safeUrl } = await import("/static/js/core/html.js");
            const name = '<img src=x onerror="alert(1)">';
            return {
                text: String(html`<b>${name}</b>`),
                nested: String(html`<ul>${["a", "<b>"].map((x) => html`<li>${x}</li>`)}</ul>`),
                falsy: String(html`${null}${undefined}${false}${true}${0}${""}`),
                raw: String(html`${raw("<i>ok</i>")}`),
                attr: String(attr({ href: 'a"b', hidden: true, disabled: false, title: null })),
                urls: ["https://x.fr/p", "http://x.fr", "javascript:alert(1)", " JAVASCRIPT:x", "/p", "data:x",
                    "//x.fr", ""]
                    .map(safeUrl),
            };
        }"""
    )
    assert rendered["text"] == "<b>&lt;img src=x onerror=&quot;alert(1)&quot;&gt;</b>"
    assert rendered["nested"] == "<ul><li>a</li><li>&lt;b&gt;</li></ul>"
    assert rendered["falsy"] == "0"
    assert rendered["raw"] == "<i>ok</i>"
    assert rendered["attr"] == ' href="a&quot;b" hidden'
    assert rendered["urls"] == ["https://x.fr/p", "http://x.fr", "", "", "", "", "", ""]
    # setHtml refuses plain strings
    error = page.evaluate(
        """async () => {
            const { setHtml } = await import("/static/js/core/html.js");
            try { setHtml(document.createElement("div"), "<b>x</b>"); return null; } catch (e) { return e.name; }
        }"""
    )
    assert error == "TypeError"


def test_fmt_helpers(desktop):
    page = desktop
    page.goto(page.base)
    fmt = "/static/js/core/fmt.js"
    assert js_eval(page, fmt, "euros", 1.5) == "1,50 €"
    assert js_eval(page, fmt, "euros", None) == ""
    assert js_eval(page, fmt, "unitText", {"unit_price": 0.79, "unit": "kg"}) == "0,79 €/kg"
    assert js_eval(page, fmt, "unitText", {"unit_price_label": "1 kg = 0,79 €"}) == "1 kg = 0,79 €"
    assert js_eval(page, fmt, "plural", 0, "produit") == "0 produit"
    assert js_eval(page, fmt, "plural", 1, "article introuvable", "articles introuvables") == "1 article introuvable"
    assert js_eval(page, fmt, "plural", 2, "article introuvable", "articles introuvables") == "2 articles introuvables"
    now = 1_800_000_000_000
    cases = [
        (now / 1000 - 20, "à l'instant"),
        (now / 1000 - 300, "il y a 5 min"),
        (now - 2 * 3600_000, "il y a 2 h"),
        (now / 1000 - 26 * 3600, "hier"),
        (now / 1000 - 3 * 86400, "il y a 3 jours"),
        (None, ""),
    ]
    for ts, expected in cases:
        assert js_eval(page, fmt, "relativeTime", ts, now) == expected


def test_api_client(desktop):
    page = desktop
    headers = []
    page.on("request", lambda r: headers.append(r.headers.get("x-prixmalin")) if "/api/" in r.url else None)
    page.goto(page.base)
    expect(page.get_by_role("searchbox")).to_be_visible()
    assert headers and all(h == "1" for h in headers)

    error = page.evaluate(
        """async () => {
            const { api, ApiError } = await import("/static/js/core/api.js");
            try { await api("/api/search/inconnu?q=x"); } catch (e) {
                return { isApiError: e instanceof ApiError, status: e.status, code: e.code, message: e.message };
            }
        }"""
    )
    assert error == {"isApiError": True, "status": 404, "code": "http_404", "message": "Enseigne inconnue : inconnu"}

    # The server stops answering, then answers again
    page.route("**/api/list", lambda route: route.abort())
    offline = page.evaluate(
        """async () => {
            const { api } = await import("/static/js/core/api.js");
            const { on } = await import("/static/js/core/store.js");
            const events = [];
            on("api:offline", () => events.push("offline"));
            on("api:online", () => events.push("online"));
            window.__events = events;
            try { await api("/api/list"); } catch (e) {
                return { code: e.code, message: e.message, events: [...events] };
            }
        }"""
    )
    assert offline["code"] == "offline" and offline["events"] == ["offline"]
    assert "PrixMalin ne répond pas" in offline["message"]
    page.unroute("**/api/list")
    page.evaluate("""async () => (await import("/static/js/core/api.js")).api("/api/list")""")
    assert page.evaluate("() => window.__events") == ["offline", "online"]
    # The 404 and the aborted request were reported by the browser on purpose
    assert len(page.errors) == 2 and all("Failed to load resource" in e for e in page.errors)
    page.errors.clear()


def test_notify_with_an_action(desktop):
    page = desktop
    page.goto(page.base)
    page.evaluate(
        """async () => {
            const { notify } = await import("/static/js/core/ui.js");
            notify("Liste vidée", { action: { label: "Annuler", onClick: () => { window.__undone = true; } } });
        }"""
    )
    toast = page.get_by_role("status")
    expect(toast).to_contain_text("Liste vidée")
    toast.get_by_role("button", name="Annuler").click()
    expect(toast).to_be_hidden()
    assert page.evaluate("() => window.__undone") is True


def test_product_extension_points(desktop):
    page = desktop
    page.goto(page.base)
    page.evaluate(
        """async () => {
            const { html } = await import("/static/js/core/html.js");
            const { productBadges } = await import("/static/js/ext/product-badges.js");
            const { productActions } = await import("/static/js/ext/product-actions.js");
            productBadges.push(
                (p) => p.store === "lidl" && html`<span class="tag" data-testid="ext-badge">Badge ${p.name}</span>`);
            productBadges.push(() => { throw new Error("provider en panne"); });
            productActions.push((p) => html`<button type="button" data-testid="ext-action">Suivre</button>`);
        }"""
    )
    box = page.get_by_role("searchbox", name="Produit à rechercher")
    box.fill("farine")
    box.press("Enter")
    expect(page.locator("[data-store=lidl] [data-testid=ext-badge]")).to_have_text("Badge Farine de blé T45")
    expect(page.locator("[data-store=aldi] [data-testid=ext-badge]")).to_have_count(0)
    expect(page.locator("[data-store=aldi] [data-testid=ext-action]").first).to_be_visible()
    # The broken provider was reported in the console: not an error of the test. It is
    # removed first: the retailers still answering would report it again afterwards
    page.evaluate(
        """async () => {
            const { productBadges } = await import("/static/js/ext/product-badges.js");
            productBadges.splice(productBadges.length - 1, 1);
        }"""
    )
    page.errors[:] = [e for e in page.errors if "provider en panne" not in e]


def test_home_cards_and_settings_sections(desktop):
    page = desktop
    page.goto(page.base)
    expect(page.get_by_role("button", name="Farine")).to_be_visible()
    assert page.evaluate("() => [...document.querySelectorAll('[data-card]')].map((c) => c.dataset.card)") == [
        "recent",
        "list",  # P5 (hidden while the list is empty)
        "status",  # P4
        "setup",
    ]
    page.goto(f"{page.base}/#/reglages")
    expect(page.get_by_role("heading", name="Navigateur")).to_be_visible()
    assert page.evaluate("() => [...document.querySelectorAll('[data-section]')].map((s) => s.dataset.section)") == [
        "location",
        "stores",
        "advanced",
        "security",  # P7
        "data",  # P7
        "phone",  # P7
        "about",  # P7
    ]
    contract = page.evaluate(
        """async () => {
            const { SECTIONS } = await import("/static/js/views/settings/index.js");
            return SECTIONS.map((s) => [s.id, typeof s.title, typeof s.order, typeof s.enabled, typeof s.render]);
        }"""
    )
    assert [c[0] for c in contract] == [
        "location",
        "stores",
        "display",
        "advanced",
        "security",
        "data",
        "phone",
        "about",
    ]
    assert all(c[1:] == ["string", "number", "boolean", "function"] for c in contract)


def test_features_are_started(desktop):
    page = desktop
    page.goto(page.base)
    features = page.evaluate(
        """async () => {
            const { FEATURES } = await import("/static/js/features/index.js");
            const started = (f) => f.enabled !== false && typeof f.init === "function";
            return Object.fromEntries(Object.entries(FEATURES).map(([k, f]) => [k, started(f)]));
        }"""
    )
    assert features == {
        "offlineBanner": False,
        "setupBanner": True,
        "bell": False,
        "accessCode": True,  # P7
        "updateBanner": True,  # P7
    }
    for selector in (
        "#view",
        "#search-form",
        "#q",
        "#store-filters",
        "#header-extras",
        "#setup-banner",
        "#toast-region",
        "#live-region",
    ):
        assert page.locator(selector).count() == 1, selector


def test_icons(desktop):
    page = desktop
    page.goto(page.base)
    sprite = page.request.get(f"{page.base}/static/icons.svg")
    assert sprite.ok and sprite.headers["content-type"].startswith("image/svg+xml")
    ids = page.evaluate(
        """async () => {
            const { icon } = await import("/static/js/core/icons.js");
            const { setHtml, html } = await import("/static/js/core/html.js");
            const box = document.createElement("div");
            setHtml(box, html`${icon("search")}${icon("trash-2", { label: "Supprimer" })}`);
            document.body.append(box);
            const [decorative, labelled] = box.querySelectorAll("svg");
            return [decorative.getAttribute("aria-hidden"), labelled.getAttribute("aria-label"),
                labelled.getAttribute("role"), decorative.querySelector("use").getAttribute("href")];
        }"""
    )
    assert ids == ["true", "Supprimer", "img", "/static/icons.svg#search"]
    for name in ("search", "list", "settings", "map-pin", "trash-2", "bell", "x", "plus"):
        assert f'<symbol id="{name}"' in sprite.text(), name


def test_settings_link_forgets_the_retailer_anchor(desktop):
    # Only « Rechercher » remembers its last address (nav.keepParams)
    page = desktop
    page.goto(f"{page.base}/#/reglages?enseigne=coursesu")
    page.get_by_role("link", name=re.compile("Ma liste")).click()
    expect(page).to_have_url(re.compile(r"#/liste$"))
    settings = page.locator("nav a", has_text="Réglages").first
    expect(settings).to_have_attribute("href", "#/reglages")


def test_malformed_path_parameter_does_not_break_the_router(desktop):
    page = desktop
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{page.base}/#/produit/aldi/%E0%A4%A")
    expect(page).to_have_url(f"{page.base}/#/")
    assert errors == []
