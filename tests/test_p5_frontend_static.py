"""Rules of the frontend of P5, read in the files: CSP, tokens of tokens.css, buttons, French texts."""

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
VIEWS = FRONTEND / "js" / "views"
JS_FILES = sorted(
    [*(VIEWS / "list").glob("*.js"), *(VIEWS / "basket").glob("*.js"), *(VIEWS / "shopping").glob("*.js")]
) + [VIEWS / "home" / "cards" / "list.js"]
CSS_FILES = [FRONTEND / "css" / f"{name}.css" for name in ("list", "basket", "shopping", "print")]


def css_text(path):
    return re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)


def css_declarations(path, prop):
    """Values of ``prop`` in ``path`` (comments removed)."""
    return re.findall(rf"(?<![\w-]){prop}\s*:\s*([^;}}]+)", css_text(path))


def test_every_file_of_the_lot_is_checked():
    names = {p.name for p in JS_FILES}
    assert {"index.js", "runner.js", "change-sheet.js", "queue.js", "share-sheet.js", "list.js"} <= names
    assert all(p.exists() for p in CSS_FILES)


@pytest.mark.parametrize("path", CSS_FILES, ids=lambda p: p.name)
def test_font_sizes_radii_and_colours_come_from_the_tokens(path):
    for value in css_declarations(path, "font-size"):
        assert value.strip().startswith("var(--text-") or value.strip() == "inherit", (path.name, value)
    for value in css_declarations(path, "border-radius"):
        for part in value.split():
            assert part.startswith("var(--radius") or part == "0", (path.name, value)
    # Colours: tokens (or the system colours of the printed page), never a raw value
    text = css_text(path)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", text), path.name
    assert not re.search(r"\b(rgb|rgba|hsl|hsla)\(", text), path.name


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_markup_respects_the_csp_and_types_its_buttons(path):
    source = path.read_text(encoding="utf-8")
    assert not re.search(r"<script", source, re.I), path.name
    assert not re.search(r"""\sstyle\s*=\s*["']""", source), path.name
    assert not re.search(r"""\son[a-z]+\s*=\s*["']""", source), path.name
    assert ".innerHTML" not in source, path.name  # only setHtml()
    for button in re.findall(r"<button\b[^>]*>", source):
        assert re.search(r"""\stype=["'](button|submit)["']""", button), (path.name, button)


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_french_texts_follow_the_glossary(path):
    source = path.read_text(encoding="utf-8")
    # « article(s) »: fmt.plural() (a call such as actionMarkup(s) is not a text)
    assert not re.search(r"\b[a-zà-ÿ]{3,}\(s\)(?!\s*(\{|=>|\)|,|;|}))", source), path.name
    assert "en cache" not in source, path.name  # « prix d'il y a 2 h »
    assert "résultats approchants" not in source.lower(), path.name
    assert not re.search(r"toFixed\(2\)", source), path.name  # prices: fmt.euros()


def test_the_basket_never_calls_an_incomplete_basket_the_cheapest():
    """« Panier le moins cher » comes only with best_store, which the server gives to complete
    baskets, and only when that basket has every item (isComplete)."""
    model = (VIEWS / "basket" / "model.js").read_text(encoding="utf-8")
    assert model.count('"Panier le moins cher"') == 1
    before = model.split('"Panier le moins cher"')[0]
    assert "comparison.best_store" in before and "if (isComplete(best, n))" in before
