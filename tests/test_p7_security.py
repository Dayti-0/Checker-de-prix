"""B80: the network access to PrixMalin (host, origin, access code of the phone)."""

import pytest
from fastapi.testclient import TestClient

from backend import config, main, security
from backend.services import prefs
from tests.conftest import run

PHONE = ("192.168.1.20", 5000)
PC_ADDRESS = "http://192.168.1.10:8000"


@pytest.fixture(autouse=True)
def fresh_attempts(monkeypatch):
    monkeypatch.setattr(security, "attempts", security.Attempts())
    monkeypatch.setattr(security, "_secret_cache", None)


@pytest.fixture
def phone():
    with TestClient(main.app, client=PHONE, base_url=PC_ADDRESS) as client:
        yield client


@pytest.fixture
def pc():
    with TestClient(main.app, client=("127.0.0.1", 5000), base_url="http://localhost:8000") as client:
        yield client


def current_code(pc) -> str:
    return pc.get("/api/security").json()["code"]


def allow(phone, code):
    return phone.post("/api/access", json={"code": code}, headers={"X-PrixMalin": "1"})


# --- pure helpers ----------------------------------------------------------------


def test_split_host_port():
    assert security.split_host_port("PC-Salon.local:8000") == ("pc-salon.local", 8000)
    assert security.split_host_port("192.168.1.10") == ("192.168.1.10", None)
    assert security.split_host_port("[::1]:8000") == ("::1", 8000)
    assert security.split_host_port("[fe80::1]") == ("fe80::1", None)
    assert security.split_host_port("localhost.:8000") == ("localhost", 8000)
    for bad in ("", None, "a b", "host:port", "[::1", "[zz]:80", "::1", "évil.fr", "x:80:90"):
        assert security.split_host_port(bad) is None, bad


def test_allowed_hosts():
    machine = ("desktop-ab12",)
    for host in ("localhost", "127.0.0.1", "::1", "192.168.1.10", "10.0.0.3", "fe80::1", "desktop-ab12"):
        assert security.allowed_host(host, machine), host
    assert security.allowed_host("desktop-ab12.local", machine)
    assert security.allowed_host("pc.tail1234.ts.net", machine)
    assert security.allowed_host("prixmalin.maison", machine, extra=("prixmalin.maison",))
    assert security.allowed_host("pc.mondomaine.fr", machine, extra=(".mondomaine.fr",))
    for host in ("attacker.example", "desktop-ab12.attacker.example", "localhost.attacker.example", "", None):
        assert not security.allowed_host(host, machine), host
    assert not security.allowed_host("mondomaine.fr.evil", machine, extra=(".mondomaine.fr",))


def test_origin_matches():
    assert security.origin_matches("http://192.168.1.10:8000", "192.168.1.10:8000")
    assert security.origin_matches("https://pc.tail1234.ts.net", "pc.tail1234.ts.net")
    assert security.origin_matches("http://localhost", "localhost:80")
    assert security.origin_matches("http://LOCALHOST:8000", "localhost:8000")
    assert not security.origin_matches("http://localhost:8001", "localhost:8000")
    assert not security.origin_matches("https://evil.example", "localhost:8000")
    assert not security.origin_matches("null", "localhost:8000")
    assert not security.origin_matches("http://localhost:99999", "localhost:8000")
    assert not security.origin_matches("ftp://localhost:8000", "localhost:8000")


def test_client_kind():
    assert security.client_kind("127.0.0.1", {}) == "local"
    assert security.client_kind("::1", {}) == "local"
    assert security.client_kind("::ffff:127.0.0.1", {}) == "local"
    assert security.client_kind("testclient", {}) == "test"
    assert security.client_kind("192.168.1.20", {}) == "remote"
    assert security.client_kind(None, {}) == "remote"
    # tailscale serve: from 127.0.0.1, through a proxy
    assert security.client_kind("127.0.0.1", {"x-forwarded-for": "100.64.0.7"}) == "remote"
    assert security.client_kind("testclient", {"forwarded": "for=1.2.3.4"}) == "remote"


def test_access_code_and_token():
    secret = security.new_secret()
    assert len(secret.code) == 6 and secret.code.isdigit()
    assert security.code_ok(secret, secret.code)
    assert security.code_ok(secret, f" {secret.code[:3]} {secret.code[3:]} ")
    assert not security.code_ok(secret, "")
    assert not security.code_ok(secret, str((int(secret.code) + 1) % 10**6).zfill(6))
    token = security.access_token(secret)
    assert security.token_ok(secret, token)
    assert not security.token_ok(secret, token[:-1] + ("0" if token[-1] != "0" else "1"))
    assert not security.token_ok(secret, None) and not security.token_ok(secret, "é")
    other = security.new_secret()
    assert not security.token_ok(other, token)
    assert security.code_text("123456") == "123 456"
    assert security.parse_secret('{"code": "12345", "key": "00"}') is None
    assert security.parse_secret("pas du json") is None


def test_attempts_by_client_and_overall():
    attempts = security.Attempts(per_client=5, overall=7, window=60)
    for i in range(5):
        assert attempts.retry_after("a", 100 + i) == 0
        attempts.failed("a", 100 + i)
    assert attempts.retry_after("a", 105) == pytest.approx(55)
    assert attempts.retry_after("b", 105) == 0
    attempts.failed("b", 106)
    attempts.failed("c", 107)
    assert attempts.retry_after("d", 108) == pytest.approx(52)  # 7 failures in the last minute
    assert attempts.retry_after("a", 160.5) == 0  # one minute later
    attempts.succeeded("b")
    assert "b" not in attempts._by_client


def test_secret_is_kept_in_its_own_file(tmp_path):
    secret = security.access_secret()
    path = config.DATA_DIR / security.ACCESS_FILE
    assert path.exists() and secret.code in path.read_text(encoding="utf-8")
    security._secret_cache = None
    assert security.access_secret() == secret
    renewed = security.renew_secret()
    assert renewed.code != secret.code or renewed.key != secret.key
    path.write_text("abîmé", encoding="utf-8")
    security._secret_cache = None
    assert security.access_secret() != renewed  # a damaged file: a new code


# --- the middleware, with a phone ------------------------------------------------


def test_phone_needs_the_cookie(phone, pc):
    assert phone.get("/api/settings").status_code == 401
    body = phone.get("/api/list").json()
    assert body["code"] == "access_required" and "code d'accès" in body["detail"]
    assert phone.get("/api/access").json() == {"authorized": False, "local": False}
    answer = allow(phone, current_code(pc))
    assert answer.status_code == 200 and answer.json() == {"authorized": True, "local": False}
    assert phone.get("/api/settings").status_code == 200
    assert phone.get("/api/access").json()["authorized"] is True


def test_the_cookie_is_httponly_strict_for_one_year(phone, pc):
    answer = allow(phone, current_code(pc))
    cookie = answer.headers["set-cookie"].lower()
    assert cookie.startswith(security.ACCESS_COOKIE + "=")
    assert "httponly" in cookie and "samesite=strict" in cookie and "max-age=31536000" in cookie
    assert "path=/" in cookie and "secure" not in cookie  # http on the Wi-Fi: no Secure flag
    assert security.access_secret().code not in answer.headers["set-cookie"]


def test_the_cookie_is_secure_behind_tailscale_https(pc):
    headers = {"X-Forwarded-For": "100.64.0.7", "X-Forwarded-Proto": "https", "X-PrixMalin": "1"}
    with TestClient(main.app, client=("127.0.0.1", 5000), base_url="http://pc.tail1234.ts.net") as tailnet:
        assert tailnet.get("/api/settings", headers=headers).status_code == 401
        answer = tailnet.post("/api/access", json={"code": current_code(pc)}, headers=headers)
        assert answer.status_code == 200
        assert "secure" in answer.headers["set-cookie"].lower()


def test_wrong_code_and_limit_of_attempts(phone, pc):
    code = current_code(pc).replace(" ", "")
    wrong = str((int(code) + 1) % 10**6).zfill(6)
    for _ in range(security.MAX_FAILURES):
        answer = allow(phone, wrong)
        assert answer.status_code == 403 and answer.json()["code"] == "wrong_code"
    blocked = allow(phone, code)  # even the right code: wait one minute
    assert blocked.status_code == 429 and blocked.json()["code"] == "too_many_attempts"
    assert phone.get("/api/settings").status_code == 401
    with TestClient(main.app, client=("192.168.1.21", 5000), base_url=PC_ADDRESS) as other:
        assert allow(other, code).status_code == 200  # another address is not limited


def test_unknown_host_is_refused(pc):
    with TestClient(main.app, client=PHONE, base_url="http://attacker.example:8000") as attacker:
        answer = attacker.get("/api/settings")
        assert answer.status_code == 400 and answer.json()["code"] == "bad_host"
        assert attacker.get("/").status_code == 400
    with TestClient(main.app, client=("127.0.0.1", 5000), base_url="http://attacker.example:8000") as rebinding:
        assert rebinding.get("/api/settings").status_code == 400
        assert rebinding.get("/").text.startswith("Adresse inconnue")
    assert pc.get("/api/settings").status_code == 200


def test_post_without_the_header_is_refused(phone, pc):
    allow(phone, current_code(pc))
    assert phone.post("/api/list", json={"query": "riz"}).status_code == 403
    ok = phone.post("/api/list", json={"query": "riz"}, headers={"X-PrixMalin": "1", "Origin": PC_ADDRESS})
    assert ok.status_code in (200, 201)
    other = phone.post("/api/list", json={"query": "riz"}, headers={"X-PrixMalin": "1", "Origin": "http://evil"})
    assert other.status_code == 403 and other.json()["code"] == "forbidden_origin"


def test_post_from_a_web_page_on_the_pc(pc):
    # A script or a test (no Origin, no Sec-Fetch-Site): allowed
    assert pc.post("/api/list", json={"query": "riz"}).status_code in (200, 201)
    # A page of another site, in the browser of the PC
    evil = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
    assert pc.post("/api/list", json={"query": "riz"}, headers=evil).status_code == 403
    assert pc.post("/api/list", json={"query": "riz"}, headers={"Origin": "https://evil.example"}).status_code == 403
    # The page of PrixMalin without the header (a form): refused
    page = {"Origin": "http://localhost:8000", "Sec-Fetch-Site": "same-origin"}
    assert pc.post("/api/list", json={"query": "riz"}, headers=page).status_code == 403
    page["X-PrixMalin"] = "1"
    assert pc.post("/api/list", json={"query": "riz"}, headers=page).status_code in (200, 201)


def test_cross_site_requests_are_refused(pc, phone):
    answer = pc.get("/api/search/aldi?q=riz", headers={"Sec-Fetch-Site": "cross-site"})
    assert answer.status_code == 403 and answer.json()["code"] == "cross_site"
    assert pc.get("/api/version", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    allow(phone, current_code(pc))
    assert phone.get("/api/version", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_the_page_and_its_files_need_no_code(phone):
    assert phone.get("/").status_code == 200
    assert phone.get("/static/js/main.js").status_code == 200
    assert phone.get("/favicon.ico").status_code == 204


def test_docs_are_for_the_pc_only(phone, pc):
    for path in ("/docs", "/openapi.json", "/redoc"):
        assert phone.get(path).status_code == 404
        assert pc.get(path).status_code == 200


def test_access_from_the_phone_disabled(phone, pc):
    allow(phone, current_code(pc))
    assert phone.patch("/api/security", json={"allow_lan": False}, headers={"X-PrixMalin": "1"}).status_code == 403
    state = pc.patch("/api/security", json={"allow_lan": False}).json()
    assert state["allow_lan"] is False and state["restart_needed"] is True
    answer = phone.get("/api/settings")
    assert answer.status_code == 403 and answer.json()["code"] == "lan_disabled"
    assert phone.get("/").status_code == 403
    assert security.lan_allowed_sync(config.DB_PATH) is False
    assert pc.patch("/api/security", json={"allow_lan": True}).json()["restart_needed"] is False
    assert phone.get("/api/settings").status_code == 200


def test_the_code_is_shown_on_the_pc_only(phone, pc):
    state = pc.get("/api/security").json()
    assert state["local"] is True and len(state["code"]) == 7 and state["code"][3] == " "
    allow(phone, state["code"])
    remote = phone.get("/api/security").json()
    assert remote["local"] is False and remote["code"] is None and remote["code_created_at"] is None


def test_a_new_code_signs_the_phones_out(phone, pc):
    old = current_code(pc)
    allow(phone, old)
    assert phone.get("/api/settings").status_code == 200
    assert phone.post("/api/security/code", headers={"X-PrixMalin": "1"}).status_code == 403
    new = pc.post("/api/security/code").json()["code"]
    assert phone.get("/api/settings").status_code == 401
    assert allow(phone, new).status_code == 200


def test_the_listen_address(monkeypatch):
    monkeypatch.setattr(config, "HOST_FROM_ENV", False)
    assert security.listen_host(config.DB_PATH) == "0.0.0.0"  # noqa: S104 (no database yet)
    run(prefs.update(security.PREFS_SECTION, security.SecurityPrefs, lambda p: setattr(p, "allow_lan", False)))
    assert security.listen_host(config.DB_PATH) == "127.0.0.1"
    monkeypatch.setattr(config, "HOST_FROM_ENV", True)
    monkeypatch.setattr(config, "HOST", "192.168.1.10")
    assert security.listen_host(config.DB_PATH) == "192.168.1.10"
    monkeypatch.setattr(security, "LISTEN_HOST", "127.0.0.1")
    assert security.lan_active() is False
    monkeypatch.setattr(security, "LISTEN_HOST", "0.0.0.0")  # noqa: S104
    assert security.lan_active() is True


def test_is_local_request_for_the_browser_status(pc, phone):
    assert pc.get("/api/browser").json()["is_local"] is True
    allow(phone, current_code(pc))
    assert phone.get("/api/browser").json()["is_local"] is False


def test_refusals_carry_the_security_headers(phone):
    answer = phone.get("/api/settings")
    assert answer.headers["content-security-policy"].startswith("default-src 'self'")
    assert answer.headers["x-content-type-options"] == "nosniff"
