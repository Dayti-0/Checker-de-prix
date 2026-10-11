"""Rules of the frontend of P2, read in the files: CSP, tokens of tokens.css, buttons, French texts."""

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
JS_FILES = sorted((FRONTEND / "js" / "views" / "search").glob("*.js")) + [
    FRONTEND / "js" / "views" / "home" / "cards" / "recent.js"
]
CSS_FILES = [FRONTEND / "css" / "search.css", FRONTEND / "css" / "results.css"]


def css_declarations(path, prop):
    """Values of ``prop`` in ``path`` (comments removed)."""
    text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    return re.findall(rf"(?<![\w-]){prop}\s*:\s*([^;}}]+)", text)


@pytest.mark.parametrize("path", CSS_FILES, ids=lambda p: p.name)
def test_font_sizes_and_radii_come_from_the_tokens(path):
    for value in css_declarations(path, "font-size"):
        assert value.strip().startswith("var(--text-") or value.strip() == "inherit", (path.name, value)
    for value in css_declarations(path, "border-radius"):
        for part in value.split():
            assert part.startswith("var(--radius") or part == "0", (path.name, value)


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_markup_respects_the_csp_and_types_its_buttons(path):
    source = path.read_text(encoding="utf-8")
    assert not re.search(r"<script", source, re.I), path.name
    assert not re.search(r"""\sstyle\s*=\s*["']""", source), path.name
    assert not re.search(r"""\son[a-z]+\s*=\s*["']""", source), path.name
    assert ".innerHTML" not in source, path.name  # only setHtml()
    for button in re.findall(r"<button\b[^>]*>", source):
        assert re.search(r"""\stype=["'](button|submit)["']""", button), (path.name, button)


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_french_plurals_without_parentheses(path):
    source = path.read_text(encoding="utf-8")
    assert not re.search(r"\w\(s\)", source), path.name  # « produit(s) »
    assert "résultats approchants" not in source.lower(), path.name  # glossary: « Produits proches »
    assert "en cache" not in source, path.name  # glossary: « prix d'il y a 2 h »


def test_common_products_for_the_suggestions():
    import json

    foods = json.loads((FRONTEND / "js" / "views" / "search" / "aliments.json").read_text(encoding="utf-8"))
    assert 280 <= len(foods) <= 320
    assert len({f.lower() for f in foods}) == len(foods)
    assert all(isinstance(f, str) and f.strip() == f and f for f in foods)
    assert {"Œufs", "Pâtes", "Crème fraîche", "Huile de tournesol", "Échalotes"} <= set(foods)


def test_files_of_the_search_are_not_ignored_by_git():
    # The rule « data/ » of .gitignore (database, profile) once hid frontend/data/aliments.json
    import shutil
    import subprocess

    git = shutil.which("git")
    if not git:
        pytest.skip("git absent")
    root = FRONTEND.parent
    files = [str(p.relative_to(root)) for p in (FRONTEND / "js" / "views" / "search").iterdir()]
    command = [git, "check-ignore", "--no-index", *files]
    found = subprocess.run(command, cwd=root, capture_output=True, text=True)  # noqa: S603 (fixed command)
    if found.returncode == 128:
        pytest.skip("not a git checkout")
    assert found.stdout.strip() == ""
