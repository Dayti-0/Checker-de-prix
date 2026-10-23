"""The PrixMalin running on this PC (area of P7): one at a time, addresses for the phone, start banner.

- ``ensure_single_instance()``: before anything else, ``GET 127.0.0.1:PORT/api/version``
  (1 s). PrixMalin answers: its page is opened (``PRIXMALIN_OPEN_BROWSER=1``,
  set by lancer.bat), « PrixMalin est déjà ouvert » and exit 0. Another
  program uses the port: a French message that proposes ``PRIXMALIN_PORT``,
  exit 1. Then ``lock_data_dir()`` takes ``data/prixmalin.lock`` (msvcrt or
  fcntl) before the browser can start: two PrixMalin on two ports never
  share a browser profile.
- ``lan_ip()``: address of the PC on the Wi-Fi (UDP socket « connected » to an
  address of the network: no packet is sent), ``qr_svg()``/``qr_text()``: QR
  code of the address for the phone (segno; nothing when it is missing).
- ``ready()``: once the server listens, the banner of the console (addresses,
  access code, QR code, firewall tip) and the page opened in the browser.
"""

import http.client
import importlib.util
import io
import ipaddress
import json
import logging
import os
import socket
import ssl
import sys
import webbrowser
from collections.abc import Callable, Iterable
from pathlib import Path

from backend import config

logger = logging.getLogger("prixmalin.instance")

PROBE_TIMEOUT_SECONDS = 1.0
LOCK_FILE = "prixmalin.lock"
CGNAT = ipaddress.ip_network("100.64.0.0/10")  # Tailscale, mobile networks: not the Wi-Fi of the house

_lock_handle = None


# ---------------------------------------------------------------------------
# One PrixMalin at a time
# ---------------------------------------------------------------------------


def probe(port: int, host: str = "127.0.0.1", timeout: float = PROBE_TIMEOUT_SECONDS) -> str:
    """Who listens on ``port``: ``"free"``, ``"prixmalin"`` or ``"other"``."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError:
        return "free"
    sock.close()
    if config.scheme() == "https":
        # Our own port on this PC: its certificate is for the names of the PC, not for 127.0.0.1
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=context)
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", "/api/version", headers={"Host": f"{host}:{port}", "Accept": "application/json"})
        answer = conn.getresponse()
        data = json.loads(answer.read(4096) or b"null") if answer.status == 200 else None
    except (OSError, http.client.HTTPException, ValueError):
        return "other"
    finally:
        conn.close()
    return "prixmalin" if isinstance(data, dict) and isinstance(data.get("version"), str) else "other"


def can_bind(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        if os.name != "nt":  # like uvicorn: a port in TIME_WAIT is free
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def port_taken_message(port: int) -> str:
    return (
        f"\n  Le port {port} est déjà utilisé par un autre programme.\n"
        "  Fermez ce programme, ou choisissez un autre port pour PrixMalin,\n"
        "  dans cette fenêtre noire :\n"
        f"      set PRIXMALIN_PORT={port + 1}\n"
        "      lancer.bat\n"
    )


def local_url(port: int) -> str:
    return f"{config.scheme()}://localhost:{port}"


def open_page(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception as e:  # noqa: BLE001 (no browser: the address is printed)
        logger.info("Browser not opened: %s", e)


def ensure_single_instance(port: int | None = None) -> None:
    """Exit when PrixMalin already runs on the port (0) or another program has it (1)."""
    port = port or config.PORT
    state = probe(port)
    if state == "prixmalin":
        url = local_url(port)
        print(f"\n  PrixMalin est déjà ouvert : {url}\n", flush=True)
        if config.OPEN_BROWSER:
            open_page(url)
        raise SystemExit(0)
    if state == "other":
        print(port_taken_message(port), file=sys.stderr, flush=True)
        raise SystemExit(1)


def check_port(host: str, port: int) -> None:
    """The port is free on the address PrixMalin listens on (exit 1 with a French message)."""
    if not can_bind(host, port):
        print(port_taken_message(port), file=sys.stderr, flush=True)
        raise SystemExit(1)


def _try_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")  # noqa: SIM115 (kept open while PrixMalin runs)
    try:
        if os.name == "nt":  # pragma: no cover (Windows)
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _unlock(handle) -> None:
    try:
        if os.name == "nt":  # pragma: no cover (Windows)
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def is_locked(folder: Path) -> bool:
    """Another PrixMalin holds the lock of ``folder`` (a data folder)."""
    if not (folder / LOCK_FILE).exists():
        return False
    handle = _try_lock(folder / LOCK_FILE)
    if handle is None:
        return True
    _unlock(handle)
    return False


def lock_data_dir(folder: Path | None = None) -> None:
    """Take ``data/prixmalin.lock`` for the whole run (exit 1 when another PrixMalin has it)."""
    global _lock_handle
    folder = folder or config.DATA_DIR
    handle = _try_lock(folder / LOCK_FILE)
    if handle is None:
        print(
            "\n  PrixMalin est déjà lancé avec ces données (dans une autre fenêtre ?).\n"
            "  Fermez l'autre fenêtre de PrixMalin, puis relancez-le.\n",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1)
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()} {config.PORT}\n")
        handle.flush()
    except OSError:
        pass
    _lock_handle = handle


def release_lock() -> None:
    global _lock_handle
    if _lock_handle is not None:
        _unlock(_lock_handle)
        _lock_handle = None


# ---------------------------------------------------------------------------
# Address for the phone
# ---------------------------------------------------------------------------


def usable_lan_ip(address: str | None) -> bool:
    """An IPv4 address of the local network (no loopback, link-local or Tailscale address)."""
    try:
        ip = ipaddress.IPv4Address(address or "")
    except ValueError:
        return False
    return ip.is_private and not (ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip in CGNAT)


def pick_lan_ip(addresses: Iterable[str]) -> str | None:
    """The best address for the phone: 192.168.x.x, then 10.x.x.x, then 172.16-31.x.x."""
    usable = [a for a in dict.fromkeys(addresses) if usable_lan_ip(a)]
    for prefix in ("192.168.", "10.", "172."):
        for address in usable:
            if address.startswith(prefix):
                return address
    return usable[0] if usable else None


def _udp_probe() -> str | None:
    # connect() of a UDP socket sends nothing: it only picks the route (and the address) to use
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("10.254.254.254", 1))
            return sock.getsockname()[0]
        except OSError:
            return None


def _host_addresses() -> list[str]:
    try:
        return socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return []


def lan_ip(
    udp_probe: Callable[[], str | None] = _udp_probe, host_addresses: Callable[[], list[str]] = _host_addresses
) -> str | None:
    """Address of the PC on the Wi-Fi or the cable, or None (no network)."""
    first = udp_probe()
    if usable_lan_ip(first):
        return first
    return pick_lan_ip(host_addresses())


def phone_url(ip: str | None, port: int, scheme: str | None = None) -> str | None:
    return f"{scheme or config.scheme()}://{ip}:{port}" if ip else None


def qr_available() -> bool:
    return importlib.util.find_spec("segno") is not None


def qr_svg(url: str) -> str | None:
    """QR code of ``url`` in SVG (dark on white), or None without segno."""
    try:
        import segno
    except ImportError:
        return None
    out = io.BytesIO()
    segno.make(url, error="m").save(
        out,
        kind="svg",
        scale=6,
        border=2,
        dark="#000000",
        light="#ffffff",
        xmldecl=False,
        title="Adresse de PrixMalin pour le téléphone",
    )
    return out.getvalue().decode("utf-8")


def qr_text(url: str) -> str | None:
    """QR code of ``url`` drawn with blocks for the console, or None without segno."""
    try:
        import segno
    except ImportError:
        return None
    out = io.StringIO()
    segno.make(url, error="m").terminal(out=out, compact=True, border=2)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Start banner
# ---------------------------------------------------------------------------

FIREWALL_TIP = (
    "  Le téléphone n'ouvre pas la page ? Il doit être sur le même Wi-Fi que le PC ;\n"
    "  dans le pare-feu Windows, autorisez Python sur les réseaux privés, et réglez\n"
    "  le Wi-Fi du PC en réseau « privé » (Paramètres > Réseau et Internet)."
)


def banner(port: int, phone: str | None, code: str | None, lan_active: bool, qr: str | None = None) -> str:
    """Text printed when PrixMalin is ready (pure)."""
    lines = ["", f"  PrixMalin est prêt : {local_url(port)}"]
    if not lan_active:
        lines.append("  Accès depuis le téléphone désactivé (Réglages > Sécurité).")
    elif phone:
        lines.append(f"  Sur le téléphone (même Wi-Fi) : {phone}")
        if code:
            lines.append(f"  Code d'accès du téléphone : {code}")
        if qr:
            lines.append("")
            lines.extend("  " + row for row in qr.rstrip("\n").split("\n"))
        lines.extend(["", FIREWALL_TIP])
    else:
        lines.append("  Le PC n'est relié à aucun réseau : le téléphone ne pourra pas se connecter.")
    lines.extend(["", "  Fermez cette fenêtre (ou Ctrl+C) pour arrêter PrixMalin.", ""])
    return "\n".join(lines)


def _print(text: str) -> None:
    try:
        print(text, flush=True)
    except UnicodeEncodeError:  # console without UTF-8 (output redirected to a file)
        print(text.encode("ascii", "replace").decode("ascii"), flush=True)


def ready(port: int, lan_active: bool) -> None:
    """The server listens: banner in the console (never in the log file), page opened."""
    from backend import security

    phone = phone_url(lan_ip(), port) if lan_active else None
    code = security.code_text(security.access_secret().code) if phone else None
    qr = None
    if phone:
        try:
            qr = qr_text(phone)
        except Exception:  # noqa: BLE001 (the address is enough)
            qr = None
    _print(banner(port, phone, code, lan_active, qr))
    logger.info("PrixMalin ready on port %s (phone: %s)", port, phone or "no")
    if config.OPEN_BROWSER:
        open_page(local_url(port))
