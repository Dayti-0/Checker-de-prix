"""B82 (one PrixMalin at a time) and B81 (address of the phone, start banner): backend/instance.py and run()."""

import http.server
import json
import socket
import threading

import pytest

from backend import config, instance, main


class _Answer(http.server.BaseHTTPRequestHandler):
    body = b""
    content_type = "application/json"

    def do_GET(self):  # noqa: N802 (http.server)
        self.send_response(200)
        self.send_header("Content-Type", self.content_type)
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


@pytest.fixture
def listening():
    """``listening(body, content_type)`` → port of a small HTTP server on 127.0.0.1."""
    servers = []

    def start(body: bytes, content_type: str = "application/json") -> int:
        handler = type("Handler", (_Answer,), {"body": body, "content_type": content_type})
        server = http.server.HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server.server_address[1]

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def no_side_effects(monkeypatch):
    """run() must stop before any of these."""
    calls = []

    def forbidden(name):
        def fn(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"{name} called")

        return fn

    monkeypatch.setattr(main.backup, "migrate_legacy_data", forbidden("migrate"))
    monkeypatch.setattr(main.instance, "lock_data_dir", forbidden("lock"))
    monkeypatch.setattr(main.logging_setup, "configure", forbidden("logs"))
    monkeypatch.setattr(main, "Server", forbidden("uvicorn"))
    monkeypatch.setattr(main.browser, "_launch", forbidden("browser"))
    opened = []
    monkeypatch.setattr(instance, "open_page", opened.append)
    return calls, opened


# --- B82 -------------------------------------------------------------------------


def test_probe(listening):
    assert instance.probe(free_port()) == "free"
    assert instance.probe(listening(json.dumps({"version": "2.1.0"}).encode())) == "prixmalin"
    assert instance.probe(listening(b"<html>autre</html>", "text/html")) == "other"
    assert instance.probe(listening(b'{"autre": 1}')) == "other"


def test_a_second_run_opens_the_first_one_and_quits(listening, monkeypatch, no_side_effects, capsys):
    calls, opened = no_side_effects
    port = listening(json.dumps({"version": "2.1.0"}).encode())
    monkeypatch.setattr(config, "PORT", port)
    monkeypatch.setattr(config, "OPEN_BROWSER", True)
    with pytest.raises(SystemExit) as stop:
        main.run()
    assert stop.value.code == 0
    assert calls == [] and opened == [f"http://localhost:{port}"]
    assert "browser" not in calls  # no browser launched (main.browser._launch never called)
    assert "PrixMalin est déjà ouvert" in capsys.readouterr().out


def test_the_browser_is_opened_by_lancer_bat_only(listening, monkeypatch, no_side_effects):
    _, opened = no_side_effects
    monkeypatch.setattr(config, "PORT", listening(json.dumps({"version": "2.1.0"}).encode()))
    monkeypatch.setattr(config, "OPEN_BROWSER", False)
    with pytest.raises(SystemExit):
        main.run()
    assert opened == []


def test_port_taken_by_another_program(listening, monkeypatch, no_side_effects, capsys):
    calls, opened = no_side_effects
    port = listening(b"<html>Un autre serveur</html>", "text/html")
    monkeypatch.setattr(config, "PORT", port)
    with pytest.raises(SystemExit) as stop:
        main.run()
    assert stop.value.code == instance.EXIT_PORT_TAKEN == 3 and calls == [] and opened == []
    err = capsys.readouterr().err
    assert f"Le port {port} est déjà utilisé" in err and f"PRIXMALIN_PORT, par exemple {port + 1}" in err
    assert "fenêtre noire" not in err


def test_port_taken_message_from_lancer_bat():
    """After a double-click, the window closes: lancer.bat offers the next port itself (review n° 3)."""
    text = instance.port_taken_message(8000, from_launcher=True)
    assert "Le port 8000 est déjà utilisé" in text and "lancer.bat va proposer" in text
    assert "set PRIXMALIN_PORT" not in text and "fenêtre noire" not in text


def test_check_port(capsys):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert not instance.can_bind("127.0.0.1", port)
        with pytest.raises(SystemExit) as stop:
            instance.check_port("127.0.0.1", port)
        assert stop.value.code == instance.EXIT_PORT_TAKEN
    assert instance.can_bind("127.0.0.1", free_port())


def test_lock_of_the_data_folder(tmp_path, capsys):
    assert not instance.is_locked(tmp_path)
    instance.lock_data_dir(tmp_path)
    try:
        assert (tmp_path / "prixmalin.lock").exists()
        assert instance.is_locked(tmp_path)
        with pytest.raises(SystemExit) as stop:  # another PrixMalin on another port
            instance.lock_data_dir(tmp_path)
        assert stop.value.code == 1
        assert "déjà lancé avec ces données" in capsys.readouterr().err
    finally:
        instance.release_lock()
    assert not instance.is_locked(tmp_path)


def test_run_in_order(monkeypatch, tmp_path):
    """run(): the move of ./data before the lock and the logs, then uvicorn on the address of Réglages."""
    steps = []
    monkeypatch.setattr(config, "PORT", free_port())
    monkeypatch.setattr(config, "HOST_FROM_ENV", False)
    monkeypatch.setattr(instance, "probe", lambda port: steps.append("probe") or "free")
    monkeypatch.setattr(main.backup, "migrate_legacy_data", lambda **kw: steps.append("move") or None)
    monkeypatch.setattr(main.instance, "lock_data_dir", lambda: steps.append("lock"))
    monkeypatch.setattr(main.logging_setup, "configure", lambda: steps.append("logs") or tmp_path / "x.log")
    monkeypatch.setattr(main.security, "lan_allowed_sync", lambda path: False)
    monkeypatch.setattr(main.security, "LISTEN_HOST", None)
    monkeypatch.setattr(main.hooks, "_startup", list(main.hooks._startup))
    seen = {}

    class FakeServer:
        def __init__(self, config_, on_ready):
            seen.update(host=config_.host, proxy_headers=config_.proxy_headers, log_config=config_.log_config)
            self.started = True

        def run(self):
            steps.append("uvicorn")

    monkeypatch.setattr(main, "Server", FakeServer)
    main.run()
    assert steps == ["probe", "move", "lock", "logs", "uvicorn"]
    assert seen == {"host": "127.0.0.1", "proxy_headers": False, "log_config": None}
    assert main.security.LISTEN_HOST == "127.0.0.1"
    names = [fn.__name__ for fn in main.hooks.startup_hooks()]
    assert "daily_copies" in names and "auto_check" in names
    assert main.browser.profile_dir == config.BROWSER_PROFILE_DIR


def test_create_app_starts_no_daily_task():
    """The tests and the demo (create_app) never check GitHub nor copy the database: run() only."""
    main.create_app()
    assert main.backup.daily_copies not in main.hooks.startup_hooks()
    assert main.updates.auto_check not in main.hooks.startup_hooks()


# --- B81 -------------------------------------------------------------------------


def test_lan_ip_and_its_choice():
    assert instance.lan_ip(lambda: "192.168.1.10", list) == "192.168.1.10"
    # The route goes through Tailscale or nowhere: the addresses of the PC
    assert instance.lan_ip(lambda: "100.101.1.2", lambda: ["127.0.1.1", "172.20.0.3", "192.168.0.12"]) == "192.168.0.12"
    assert instance.lan_ip(lambda: None, lambda: ["10.0.0.5", "169.254.3.3"]) == "10.0.0.5"
    assert instance.lan_ip(lambda: None, lambda: ["127.0.0.1"]) is None
    assert instance.pick_lan_ip(["172.17.0.1", "10.1.1.1", "192.168.1.3"]) == "192.168.1.3"
    for bad in ("127.0.0.1", "169.254.1.1", "8.8.8.8", "100.64.0.1", "0.0.0.0", "fe80::1", "", None):  # noqa: S104
        assert not instance.usable_lan_ip(bad), bad
    assert instance.phone_url("192.168.1.10", 8001) == "http://192.168.1.10:8001"
    assert instance.phone_url(None, 8000) is None


def test_lan_ip_with_the_real_socket():
    ip = instance.lan_ip()
    assert ip is None or instance.usable_lan_ip(ip)


def test_qr_codes():
    svg = instance.qr_svg("http://192.168.1.10:8000")
    assert svg.startswith("<svg") and "Adresse de PrixMalin" in svg and "<script" not in svg
    text = instance.qr_text("http://192.168.1.10:8000")
    assert "█" in text and len(text.splitlines()) > 10
    assert instance.qr_available()


def test_qr_codes_without_segno(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_segno(name, *args, **kwargs):
        if name == "segno":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_segno)
    assert instance.qr_svg("http://192.168.1.10:8000") is None
    assert instance.qr_text("http://192.168.1.10:8000") is None


def test_banner():
    text = instance.banner(8000, "http://192.168.1.10:8000", "123 456", True, "QR\nQR\n")
    assert "PrixMalin est prêt : http://localhost:8000" in text
    assert "Sur le téléphone (même Wi-Fi) : http://192.168.1.10:8000" in text
    assert "Code d'accès du téléphone : 123 456" in text and "  QR\n  QR" in text
    assert "pare-feu Windows" in text and "réseaux privés" in text
    off = instance.banner(8000, None, None, False)
    assert "désactivé" in off and "Code" not in off
    assert "aucun réseau" in instance.banner(8000, None, None, True)


def test_ready_prints_the_code_but_never_logs_it(monkeypatch, capsys, caplog):
    from backend import security

    opened = []
    monkeypatch.setattr(instance, "open_page", opened.append)
    monkeypatch.setattr(instance, "lan_ip", lambda: "192.168.1.10")
    monkeypatch.setattr(config, "OPEN_BROWSER", True)
    with caplog.at_level("INFO"):
        instance.ready(8000, True)
    code = security.code_text(security.access_secret().code)
    assert code in capsys.readouterr().out
    assert code not in caplog.text and security.access_secret().code not in caplog.text
    assert opened == ["http://localhost:8000"]


# --- HTTPS with a certificate (docs/acces-telephone.md, mkcert) ----------------------


@pytest.fixture
def certificate(tmp_path, monkeypatch):
    import shutil
    import subprocess

    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl introuvable")
    cert, key = tmp_path / "pc.pem", tmp_path / "pc-key.pem"
    subprocess.run(  # noqa: S603
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=pc.local",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(config, "SSL_CERTFILE", str(cert))
    monkeypatch.setattr(config, "SSL_KEYFILE", str(key))
    return cert, key


def test_https_addresses(certificate):
    assert config.scheme() == "https"
    assert instance.local_url(8000) == "https://localhost:8000"
    assert instance.phone_url("192.168.1.10", 8000) == "https://192.168.1.10:8000"


def test_probe_over_https(certificate):
    import ssl

    cert, key = certificate
    handler = type("Handler", (_Answer,), {"body": json.dumps({"version": "2.1.0"}).encode()})
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert instance.probe(server.server_address[1]) == "prixmalin"
    finally:
        server.shutdown()
        server.server_close()


def test_run_with_https(certificate, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PORT", free_port())
    monkeypatch.setattr(instance, "probe", lambda port: "free")
    monkeypatch.setattr(main.backup, "migrate_legacy_data", lambda **kw: None)
    monkeypatch.setattr(main.instance, "lock_data_dir", lambda: None)
    monkeypatch.setattr(main.logging_setup, "configure", lambda: tmp_path / "x.log")
    monkeypatch.setattr(main.hooks, "_startup", list(main.hooks._startup))
    monkeypatch.setattr(main.security, "LISTEN_HOST", None)
    seen = {}

    class FakeServer:
        def __init__(self, config_, on_ready):
            seen.update(cert=config_.ssl_certfile, key=config_.ssl_keyfile)
            self.started = True

        def run(self):
            pass

    monkeypatch.setattr(main, "Server", FakeServer)
    main.run()
    assert seen == {"cert": config.SSL_CERTFILE, "key": config.SSL_KEYFILE}
