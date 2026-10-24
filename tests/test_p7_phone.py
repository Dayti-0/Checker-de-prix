"""B81: address of the phone and its QR code (GET /api/system/phone, /api/system/phone-qr.svg), lancer.bat."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import config, instance, main, security

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def pc(monkeypatch):
    monkeypatch.setattr(instance, "lan_ips", lambda: ["192.168.1.10"])
    monkeypatch.setattr(security, "LISTEN_HOST", "0.0.0.0")  # noqa: S104
    with TestClient(main.app, client=("127.0.0.1", 5000), base_url="http://localhost:8123") as client:
        yield client


def test_phone_address_uses_the_port_of_the_page(pc):
    info = pc.get("/api/system/phone").json()
    assert info == {
        "url": "http://192.168.1.10:8123",
        "others": [],
        "lan_active": True,
        "allow_lan": True,
        "qr": True,
        "local": True,
    }


def test_qr_code_of_the_address(pc):
    answer = pc.get("/api/system/phone-qr.svg")
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("image/svg+xml")
    assert answer.text.startswith("<svg") and "<script" not in answer.text
    assert answer.headers["cache-control"] == "no-store"


def test_no_address_without_network(pc, monkeypatch):
    monkeypatch.setattr(instance, "lan_ips", lambda: [])
    info = pc.get("/api/system/phone").json()
    assert info["url"] is None and info["qr"] is False
    answer = pc.get("/api/system/phone-qr.svg")
    assert answer.status_code == 404 and answer.json()["code"] == "no_qr"


def test_no_address_when_the_access_is_off(pc, monkeypatch):
    pc.patch("/api/security", json={"allow_lan": False})
    info = pc.get("/api/system/phone").json()
    assert info["url"] is None and info["allow_lan"] is False
    assert pc.get("/api/system/phone-qr.svg").status_code == 404
    pc.patch("/api/security", json={"allow_lan": True})
    monkeypatch.setattr(security, "LISTEN_HOST", "127.0.0.1")  # restarted on the PC only
    info = pc.get("/api/system/phone").json()
    assert info["url"] is None and info["lan_active"] is False


def test_without_segno_the_address_is_still_given(pc, monkeypatch):
    monkeypatch.setattr(instance, "qr_available", lambda: False)
    monkeypatch.setattr(instance, "qr_svg", lambda url: None)
    info = pc.get("/api/system/phone").json()
    assert info["url"] == "http://192.168.1.10:8123" and info["qr"] is False
    assert pc.get("/api/system/phone-qr.svg").status_code == 404


def test_the_phone_needs_the_code_for_its_address():
    with TestClient(main.app, client=("192.168.1.20", 5000), base_url="http://192.168.1.10:8000") as phone:
        assert phone.get("/api/system/phone").status_code == 401
        assert phone.get("/api/system/phone-qr.svg").status_code == 401


# --- lancer.bat and installer-raccourci.bat -----------------------------------------


@pytest.mark.parametrize("name", ["lancer.bat", "installer-raccourci.bat"])
def test_bat_files_are_crlf_and_ascii(name):
    data = (ROOT / name).read_bytes()
    assert data.isascii(), f"{name}: les commandes .bat restent sans accents"
    lines = data.split(b"\n")[:-1]
    assert lines and all(line.endswith(b"\r") for line in lines), f"{name} doit rester en CRLF"


def test_lancer_bat_steps():
    text = (ROOT / "lancer.bat").read_text(encoding="ascii")
    lines = [line.strip() for line in text.splitlines()]
    code = [line for line in lines if line and not line.lower().startswith("rem")]
    assert code[0] == "@echo off" and 'cd /d "%~dp0"' in code[:3]
    # Python 3.11 or newer, the launcher py first
    assert "for %%V in (3.13 3.12 3.11 3) do if not defined PY call :try_python py -%%V" in lines
    assert "if not defined PY call :try_python python" in lines
    assert "Add python.exe to PATH" in text
    # venv checked, dependencies only when requirements.txt changed
    assert "sys.version_info >= (3, 11)" in text and "import fastapi, playwright" in text
    assert "hashlib.sha256" in text and "venv/.prixmalin-req" in text
    # the browser opened by Python, no fixed wait; the port of PRIXMALIN_PORT
    assert 'set "PRIXMALIN_OPEN_BROWSER=1"' in lines and "timeout /t" not in text
    assert "localhost:8000" not in text
    assert "-m backend.browser_check --install" in text and "-m backend.main" in text
    assert "installer-raccourci.bat" in text and "choice /c ON" in text


def test_requirements_have_segno():
    assert "segno" in (ROOT / "requirements.in").read_text(encoding="utf-8")
    assert "segno==" in (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert config.PORT > 0


# --- review: a VPN does not hide the address of the Wi-Fi -------------------------------


def test_the_wifi_address_wins_over_a_vpn():
    assert instance.lan_ip(lambda: "10.5.0.2", lambda: ["10.5.0.2", "192.168.1.10"]) == "192.168.1.10"
    assert instance.lan_ips(lambda: "10.5.0.2", lambda: ["10.5.0.2", "192.168.1.10", "127.0.0.1"]) == [
        "192.168.1.10",
        "10.5.0.2",
    ]
    # Same kind of address: the one of the route (the probe) first
    assert instance.lan_ips(lambda: "192.168.1.10", lambda: ["192.168.56.1", "192.168.1.10"])[0] == "192.168.1.10"


def test_other_addresses_are_listed(monkeypatch):
    monkeypatch.setattr(instance, "lan_ips", lambda: ["192.168.1.10", "10.5.0.2"])
    monkeypatch.setattr(security, "LISTEN_HOST", "0.0.0.0")  # noqa: S104
    with TestClient(main.app, client=("127.0.0.1", 5000), base_url="http://localhost:8000") as pc:
        info = pc.get("/api/system/phone").json()
    assert info["url"] == "http://192.168.1.10:8000"
    assert info["others"] == ["http://10.5.0.2:8000"]
