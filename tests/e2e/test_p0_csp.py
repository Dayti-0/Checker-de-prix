"""B11: the whole interface works under the Content-Security-Policy, which is really applied."""

import re

from playwright.sync_api import expect


def test_every_view_respects_the_csp(desktop):
    page = desktop
    page.goto(page.base)
    box = page.get_by_role("searchbox", name="Produit à rechercher")
    box.fill("farine de blé")
    box.press("Enter")
    expect(page.locator("[data-store] .spinner")).to_have_count(0)
    page.locator("[data-store=aldi]").get_by_role("button", name="Voir 1 résultat approchant").click()
    expect(page.locator("[data-store=aldi]")).to_contain_text("Résultats approchants")
    page.locator("[data-store=lidl]").get_by_role("button", name=re.compile("Ajouter")).first.click()
    page.get_by_role("link", name=re.compile("Ma liste")).click()
    page.get_by_role("button", name="Comparer mon panier").click()
    expect(page.get_by_text("Panier le moins cher")).to_be_visible()
    page.get_by_role("link", name="Réglages").first.click()
    postal = page.get_by_role("textbox", name="Code postal")
    postal.fill("34480")
    postal.press("Enter")
    expect(page.get_by_role("button", name="Magalas")).to_be_visible()
    page.locator("[data-retailer=coursesu]").get_by_role("button", name="Ouvrir le site").click()
    expect(page.locator("#setup-banner")).to_be_visible()
    page.get_by_role("button", name="J'ai terminé").click()
    expect(page.locator("#setup-banner")).to_be_hidden()
    assert page.evaluate("() => window.__csp") == []


def test_inline_code_is_blocked(desktop):
    page = desktop
    page.goto(page.base)
    expect(page.get_by_role("searchbox")).to_be_visible()
    page.evaluate(
        """() => {
            const box = document.createElement("div");
            box.innerHTML = '<img src="/static/none.png" onerror="window.__ran = true">'
                + '<span style="color: red">x</span>';
            document.body.append(box);
            const script = document.createElement("script");
            script.textContent = "window.__ran = true";
            document.body.append(script);
        }"""
    )
    page.wait_for_function("() => window.__csp.length >= 3")
    assert page.evaluate("() => window.__ran") is None
    assert set(page.evaluate("() => window.__csp")) >= {"script-src-attr", "style-src-attr", "script-src-elem"}
    page.errors.clear()  # the violations above are expected
