"""B11: static files, version, cache, gzip, Content-Security-Policy and headers."""

import mimetypes
import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend
from backend import config, main
from backend.api import system
from backend.security import CONTENT_SECURITY_POLICY

FRONTEND = Path(config.FRONTEND_DIR)
CSS_FILES = [
    "tokens", "base", "shell", "components", "home", "search", "results", "list", "basket", "shopping", "print",
    "settings", "stores", "status", "onboarding", "tracking", "product", "system",
]  # fmt: skip


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def test_security_headers_everywhere(client):
    for path in ("/", "/api/version", "/static/js/main.js", "/api/search/inconnu?q=x"):
        response = client.get(path)
        assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY, path
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
    assert "script-src 'self'" in CONTENT_SECURITY_POLICY and "unsafe-inline" not in CONTENT_SECURITY_POLICY


def test_index_carries_the_version(client):
    response = client.get("/")
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    page = response.text
    assert "__VERSION__" not in page
    assert f'<script type="module" src="/static/js/main.js?v={backend.__version__}"></script>' in page
    links = re.findall(r'href="/static/css/([a-z]+)\.css\?v=([\d.]+)"', page)
    assert [name for name, _ in links] == CSS_FILES
    assert {version for _, version in links} == {backend.__version__}
    # boot.js runs before the stylesheets, synchronously
    head = page.split("</head>")[0]
    assert head.index("/static/js/boot.js") < head.index("/static/css/tokens.css")
    assert '<script src="/static/js/boot.js' in head


def test_static_files_are_revalidated_and_compressed(client):
    response = client.get("/static/js/main.js", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["content-type"] == "text/javascript; charset=utf-8"
    assert client.get("/static/css/tokens.css").headers["content-type"] == "text/css; charset=utf-8"
    assert client.get("/static/icons.svg").headers["content-type"].startswith("image/svg+xml")
    for gone in ("/static/app.js", "/static/style.css", "/static/js/inconnu.js"):
        assert client.get(gone).status_code == 404


def test_a_changed_module_is_downloaded_again(tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    shutil.copytree(FRONTEND, frontend)
    monkeypatch.setattr(config, "FRONTEND_DIR", frontend)
    with TestClient(main.create_app()) as client:
        first = client.get("/static/js/core/fmt.js")
        etag = first.headers["etag"]
        assert client.get("/static/js/core/fmt.js", headers={"If-None-Match": etag}).status_code == 304
        module = frontend / "js" / "core" / "fmt.js"
        module.write_text(module.read_text(encoding="utf-8") + "\n// nouvelle version\n", encoding="utf-8")
        again = client.get("/static/js/core/fmt.js", headers={"If-None-Match": etag})
        assert again.status_code == 200
        assert again.headers["etag"] != etag
        assert again.text.endswith("// nouvelle version\n")


def test_javascript_type_does_not_depend_on_the_windows_registry():
    """On Windows, mimetypes may read ".js = text/plain" from the registry: the page stays blank."""
    mimetypes.add_type("text/plain", ".js")
    mimetypes.add_type("text/plain", ".css")
    try:
        assert mimetypes.guess_type("main.js")[0] == "text/plain"
        with TestClient(main.create_app()) as client:
            for path in ("/static/js/main.js", "/static/js/views/search/index.js"):
                assert client.get(path).headers["content-type"] == "text/javascript; charset=utf-8", path
            assert client.get("/static/css/base.css").headers["content-type"] == "text/css; charset=utf-8"
        assert mimetypes.guess_type("main.js")[0] == "text/javascript"
    finally:
        system.fix_media_types()


def test_served_types_even_if_the_registry_is_read_later(monkeypatch):
    """The type is also set on each response, whatever mimetypes says at that time."""
    import starlette.responses

    with TestClient(main.app) as client:
        monkeypatch.setattr(starlette.responses, "guess_type", lambda *args, **kwargs: ("text/plain", None))
        assert client.get("/static/js/main.js").headers["content-type"] == "text/javascript; charset=utf-8"
        assert client.get("/static/css/base.css").headers["content-type"] == "text/css; charset=utf-8"


SOURCES = sorted(p for p in FRONTEND.rglob("*") if p.suffix in (".js", ".html") and "vendor" not in p.parts)


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(FRONTEND)))
def test_no_inline_code_nor_style(path):
    """What the CSP refuses is never written: no on*= handler, style= attribute or inline script."""
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"""\son[a-z]+\s*=\s*["'{]""", text), "attribut on*="
    assert not re.search(r"""\sstyle\s*=\s*["']""", text), "attribut style="
    assert not re.search(r"<script(?![^>]*\ssrc=)[^>]*>", text), "script en ligne"


def test_innerhtml_only_through_html_templates():
    uses = [
        f"{p.relative_to(FRONTEND)}:{n}"
        for p in FRONTEND.rglob("*.js")
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write", line)
    ]
    assert uses == ["js/core/html.js:73"]
