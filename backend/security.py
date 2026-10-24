"""Security of the web server (area of P7).

``install(app)`` adds two ASGI middlewares:

- ``SecurityHeaders``: CSP, ``nosniff`` and ``Referrer-Policy`` on every response;
- ``AccessGuard``, for every request:
  1. the ``Host`` must be a name of this PC: localhost, an IP address, the
     name of the PC or ``name.local``, a Tailscale ``*.ts.net`` name or one of
     ``PRIXMALIN_ALLOWED_HOSTS`` (otherwise 400: a web page cannot reach
     PrixMalin through a domain name of its own, « DNS rebinding »);
  2. ``/api`` with ``Sec-Fetch-Site: cross-site``: 403;
  3. a method other than GET/HEAD needs ``X-PrixMalin: 1`` and an ``Origin``
     absent or equal to the address of PrixMalin (403). On the PC, a request
     with neither ``Origin`` nor ``Sec-Fetch-Site`` does not come from a web
     page (a script, the tests) and only needs the right ``Origin``;
  4. a client outside the PC (the phone) needs the cookie ``prixmalin_acces``
     for ``/api`` (401 otherwise), obtained with the 6-digit access code shown
     in Réglages › Sécurité and in the console (``POST /api/access``, 5 wrong
     codes per minute and per address, 20 for all of them); the page and its
     files stay readable, so that the phone can show the code screen;
     ``/docs`` and ``/openapi.json`` are for the PC only (404); with
     « Autoriser l'accès depuis le téléphone » off, 403 until PrixMalin
     restarts on 127.0.0.1.

A request is « from the PC » when its address is a loopback one and it went
through no proxy (no ``X-Forwarded-For``: ``tailscale serve`` adds it, so a
phone of the tailnet needs the code too). ``run()`` starts uvicorn without
``proxy_headers``: the address is always the one of the connection.
Starlette's TestClient (address « testclient », in the same process) counts
as the PC, and the address « testserver » of its own server is accepted.

The code and the key of the cookies live in ``data/acces-telephone.json``,
outside the database: never in a backup, the diagnostic or a log. A new code
also changes the key: every phone must type the new one.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import sqlite3
import time
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, Request, Response
from pydantic import BaseModel, Field
from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import cookie_parser
from starlette.responses import JSONResponse, PlainTextResponse

from backend import config
from backend.errors import AppError
from backend.services import prefs

logger = logging.getLogger("prixmalin.security")

# Only the files of PrixMalin run in the page: no inline script, style
# attribute or event handler (the frontend never uses them). Product images
# come from the retailer sites (https).
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "img-src 'self' https: data:",
        "script-src 'self'",
        "style-src 'self'",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "form-action 'self'",
    ]
)

HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

ACCESS_COOKIE = "prixmalin_acces"
COOKIE_MAX_AGE = 365 * 24 * 3600
ACCESS_FILE = "acces-telephone.json"
PREFS_SECTION = "p7.security"

MAX_FAILURES = 5  # wrong codes per minute and per address
MAX_FAILURES_ALL = 20  # wrong codes per minute, every address together
FAILURE_WINDOW_SECONDS = 60.0

SAFE_METHODS = ("GET", "HEAD")
LOCAL_ONLY_PATHS = ("/docs", "/redoc", "/openapi.json")
OPEN_API_PATHS = ("/api/access",)
# Starlette's TestClient (same process): its client and server are never network addresses
TEST_CLIENT = "testclient"
TEST_SERVER = "testserver"
FORWARDED_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip")
LOOPBACK_NAMES = ("localhost", "localhost.localdomain")
TAILSCALE_SUFFIX = ".ts.net"

# Address the server listens on, set by run() (None: not started by run(), config.HOST)
LISTEN_HOST: str | None = None


class SecurityPrefs(BaseModel):
    allow_lan: bool = True  # « Autoriser l'accès depuis le téléphone »


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

_NAME = re.compile(r"[a-z0-9_.-]+")


def split_host_port(value: str | None) -> tuple[str, int | None] | None:
    """``"PC.local:8000"`` → ``("pc.local", 8000)``; ``"[::1]:8000"`` → ``("::1", 8000)``; None if malformed."""
    value = (value or "").strip().lower()
    if not value:
        return None
    if value.startswith("["):
        end = value.find("]")
        if end < 0:
            return None
        host, rest = value[1:end], value[end + 1 :]
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            return None
        if not rest:
            return host, None
        if not rest.startswith(":") or not rest[1:].isdigit():
            return None
        return host, int(rest[1:])
    host, colon, port = value.partition(":")
    if colon and (not port.isdigit() or ":" in port):
        return None
    host = host.rstrip(".")
    if not host or not _NAME.fullmatch(host):
        return None
    return host, int(port) if colon else None


def is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def is_loopback(address: str | None) -> bool:
    try:
        ip = ipaddress.ip_address(address or "")
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return ip.is_loopback or bool(mapped and mapped.is_loopback)


def allowed_host(host: str | None, machine: Iterable[str] = (), extra: Iterable[str] = ()) -> bool:
    """A name under which PrixMalin answers (``host`` without port, lowercase)."""
    if not host:
        return False
    if host in LOOPBACK_NAMES or is_ip(host) or host.endswith(TAILSCALE_SUFFIX):
        return True
    names = {name.lower() for name in machine if name}
    if host in names or host in {f"{name}.local" for name in names}:
        return True
    for name in extra:
        name = name.strip().lower()
        if name and (host == name or (name.startswith(".") and host.endswith(name))):
            return True
    return False


def origin_matches(origin: str | None, host_header: str | None) -> bool:
    """``Origin`` is the address of PrixMalin itself (same name and port)."""
    if not origin:
        return False
    try:
        parts = urlsplit(origin)
        origin_port = parts.port
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    default = 443 if parts.scheme == "https" else 80
    host = split_host_port(host_header)
    if host is None:
        return False
    return parts.hostname.lower().rstrip(".") == host[0] and (origin_port or default) == (host[1] or default)


def client_kind(client_host: str | None, headers: Mapping[str, str]) -> str:
    """``"local"`` (the PC), ``"test"`` (TestClient, the PC too) or ``"remote"`` (phone, tailnet)."""
    forwarded = any(name in headers for name in FORWARDED_HEADERS)
    if forwarded:
        return "remote"
    if client_host == TEST_CLIENT:
        return "test"
    return "local" if is_loopback(client_host) else "remote"


def is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


@dataclass(frozen=True)
class Refusal:
    status: int
    code: str
    message: str


BAD_HOST = Refusal(400, "bad_host", "Adresse inconnue de PrixMalin : ouvrez l'adresse affichée dans sa fenêtre.")
CROSS_SITE = Refusal(403, "cross_site", "Demande venue d'un autre site : refusée.")
FORGED = Refusal(403, "forbidden_origin", "Demande refusée : rechargez la page de PrixMalin.")
NOT_FOUND = Refusal(404, "http_404", "Introuvable.")
LAN_DISABLED = Refusal(
    403, "lan_disabled", "L'accès depuis le téléphone est désactivé sur le PC (Réglages › Sécurité)."
)
CODE_NEEDED = Refusal(401, "access_required", "Saisissez le code d'accès affiché sur le PC, dans Réglages › Sécurité.")


def check(
    *,
    method: str,
    path: str,
    headers: Mapping[str, str],
    kind: str,
    authorized: bool = False,
    lan_allowed: bool = True,
    check_host: bool = True,
    machine: Iterable[str] = (),
    extra: Iterable[str] = (),
) -> Refusal | None:
    """Why the request is refused (see the docstring of this module), or None.

    ``check_host`` is false for the TestClient's own server (no network).
    """
    host_header = headers.get("host")
    if check_host and kind != "test":
        host = split_host_port(host_header)
        if host is None or not allowed_host(host[0], machine, extra):
            return BAD_HOST
    if is_api(path) and headers.get("sec-fetch-site", "").lower() == "cross-site":
        return CROSS_SITE
    if method.upper() not in SAFE_METHODS:
        origin = headers.get("origin")
        from_page = origin is not None or "sec-fetch-site" in headers
        if origin is not None and not origin_matches(origin, host_header):
            return FORGED
        if (kind == "remote" or from_page) and headers.get("x-prixmalin") != "1":
            return FORGED
    if kind == "remote":
        if path in LOCAL_ONLY_PATHS or path.startswith("/docs/"):
            return NOT_FOUND
        if not lan_allowed:
            return LAN_DISABLED
        if is_api(path) and path not in OPEN_API_PATHS and not authorized:
            return CODE_NEEDED
    return None


# ---------------------------------------------------------------------------
# Access code
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AccessSecret:
    code: str  # 6 digits, typed on the phone
    key: str  # 64 hex characters: key of the cookies
    created_at: float


_CODE = re.compile(r"\d{6}")
_KEY = re.compile(r"[0-9a-f]{64}")


def new_secret(now: float | None = None) -> AccessSecret:
    return AccessSecret(f"{secrets.randbelow(10**6):06d}", secrets.token_hex(32), now or time.time())


def access_token(secret: AccessSecret) -> str:
    """Value of the cookie: it changes with the key (a new code signs every phone out)."""
    return hmac.new(bytes.fromhex(secret.key), b"prixmalin-acces-1", hashlib.sha256).hexdigest()


def token_ok(secret: AccessSecret, token: str | None) -> bool:
    if not token:
        return False
    return hmac.compare_digest(access_token(secret).encode(), token.encode("utf-8", "ignore"))


def normalize_code(given: str | None) -> str:
    """« 123 456 » → « 123456 » (spaces and dashes typed with the code)."""
    return re.sub(r"[\s-]", "", given or "")


def code_ok(secret: AccessSecret, given: str | None) -> bool:
    """Compared in constant time."""
    return hmac.compare_digest(normalize_code(given).encode("utf-8", "ignore"), secret.code.encode())


def code_text(code: str) -> str:
    """« 123456 » → « 123 456 » (easier to read and to type)."""
    return f"{code[:3]} {code[3:]}"


def parse_secret(text: str) -> AccessSecret | None:
    try:
        data = json.loads(text)
        secret = AccessSecret(str(data["code"]), str(data["key"]), float(data.get("created_at") or 0))
    except (ValueError, KeyError, TypeError):
        return None
    if not _CODE.fullmatch(secret.code) or not _KEY.fullmatch(secret.key):
        return None
    return secret


def secret_path() -> Path:
    return config.DATA_DIR / ACCESS_FILE


def save_secret(path: Path, secret: AccessSecret) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps({"code": secret.code, "key": secret.key, "created_at": secret.created_at}), encoding="utf-8"
    )
    try:
        os.chmod(tmp, 0o600)
    except OSError:  # pragma: no cover (Windows: the folder of the user already)
        pass
    os.replace(tmp, path)


_secret_cache: tuple[str, AccessSecret] | None = None


def access_secret() -> AccessSecret:
    """The current code (created the first time)."""
    global _secret_cache
    path = secret_path()
    if _secret_cache is not None and _secret_cache[0] == str(path):
        return _secret_cache[1]
    secret = None
    try:
        secret = parse_secret(path.read_text(encoding="utf-8"))
        if secret is None:
            logger.warning("Access code file unreadable, a new code is created")
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Access code file unreadable (%s), a new code is created", e)
    if secret is None:
        secret = new_secret()
        save_secret(path, secret)
        logger.info("New access code for the phone created")
    _secret_cache = (str(path), secret)
    return secret


def renew_secret() -> AccessSecret:
    """A new code and a new key: the phones already allowed must type the new code."""
    global _secret_cache
    path = secret_path()
    secret = new_secret()
    save_secret(path, secret)
    _secret_cache = (str(path), secret)
    logger.info("Access code of the phone changed")
    return secret


class Attempts:
    """Wrong codes of the last minute, by address and for all of them."""

    def __init__(
        self, per_client: int = MAX_FAILURES, overall: int = MAX_FAILURES_ALL, window: float = FAILURE_WINDOW_SECONDS
    ) -> None:
        self.per_client, self.overall, self.window = per_client, overall, window
        self._by_client: dict[str, deque[float]] = {}
        self._all: deque[float] = deque()

    def _prune(self, now: float) -> None:
        limit = now - self.window
        while self._all and self._all[0] <= limit:
            self._all.popleft()
        for client in list(self._by_client):
            failures = self._by_client[client]
            while failures and failures[0] <= limit:
                failures.popleft()
            if not failures:
                del self._by_client[client]

    def retry_after(self, client: str, now: float) -> float:
        """Seconds to wait before the next try (0: allowed now)."""
        self._prune(now)
        waits = [0.0]
        failures = self._by_client.get(client)
        if failures and len(failures) >= self.per_client:
            waits.append(failures[0] + self.window - now)
        if len(self._all) >= self.overall:
            waits.append(self._all[0] + self.window - now)
        return max(waits)

    def failed(self, client: str, now: float) -> None:
        self._prune(now)
        self._by_client.setdefault(client, deque()).append(now)
        self._all.append(now)

    def succeeded(self, client: str) -> None:
        self._by_client.pop(client, None)


attempts = Attempts()


# ---------------------------------------------------------------------------
# Setting « Autoriser l'accès depuis le téléphone »
# ---------------------------------------------------------------------------


async def lan_allowed() -> bool:
    try:
        return (await prefs.get(PREFS_SECTION, SecurityPrefs)).allow_lan
    except Exception:  # noqa: BLE001 (database unavailable: the code is still asked)
        logger.exception("Security settings unreadable")
        return True


def lan_allowed_sync(db_path: Path) -> bool:
    """The setting, read before the server starts (sqlite3, read only; True when unknown)."""
    try:
        if not Path(db_path).is_file():
            return True
        uri = Path(db_path).resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=2) as db:
            row = db.execute("SELECT value FROM settings WHERE key = ?", (prefs.key(PREFS_SECTION),)).fetchone()
        db.close()
        return SecurityPrefs.model_validate_json(row[0]).allow_lan if row else True
    except Exception:  # noqa: BLE001 (no table yet, damaged file: the default)
        return True


def listen_host(db_path: Path | None = None) -> str:
    """Address to listen on: PRIXMALIN_HOST, else everywhere or the PC only, as set in Réglages."""
    if config.HOST_FROM_ENV:
        return config.HOST
    return "0.0.0.0" if lan_allowed_sync(db_path or config.DB_PATH) else "127.0.0.1"  # noqa: S104


def lan_active() -> bool:
    """This run of PrixMalin can be reached from the network."""
    host = LISTEN_HOST if LISTEN_HOST is not None else config.HOST
    return not (is_loopback(host) or host in LOOPBACK_NAMES)


_machine: tuple[str, ...] | None = None


def machine_names() -> tuple[str, ...]:
    """Name of the PC (« desktop-ab12 ») and its first label, lowercase."""
    global _machine
    if _machine is None:
        try:
            name = socket.gethostname().lower().rstrip(".")
        except OSError:
            name = ""
        _machine = tuple(sorted({n for n in (name, name.split(".")[0]) if n}))
    return _machine


# ---------------------------------------------------------------------------
# Middlewares
# ---------------------------------------------------------------------------


class SecurityHeaders:
    """ASGI middleware: adds HEADERS to every HTTP response (unless already set)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _client_host(scope) -> str | None:
    client = scope.get("client")
    return client[0] if client else None


def _in_process(scope) -> bool:
    """Request of Starlette's TestClient (uvicorn gives the address of the socket)."""
    server = scope.get("server")
    return bool(server) and server[0] == TEST_SERVER


def _cookie(headers: Headers) -> str | None:
    raw = headers.get("cookie")
    return cookie_parser(raw).get(ACCESS_COOKIE) if raw else None


class AccessGuard:
    """ASGI middleware: the checks of the docstring of this module."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        kind = client_kind(_client_host(scope), headers)
        authorized, lan = True, True
        if kind == "remote":
            lan = await lan_allowed()
            authorized = token_ok(access_secret(), _cookie(headers))
        path = scope.get("path", "")
        refusal = check(
            method=scope.get("method", "GET"),
            path=path,
            headers=headers,
            kind=kind,
            authorized=authorized,
            lan_allowed=lan,
            check_host=not _in_process(scope),
            machine=machine_names(),
            extra=config.ALLOWED_HOSTS,
        )
        if refusal is None:
            await self.app(scope, receive, send)
            return
        if refusal.status == 400:
            logger.warning("Request refused: unknown address %r", (headers.get("host") or "")[:80])
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if is_api(path):
            response = JSONResponse({"detail": refusal.message, "code": refusal.code}, status_code=refusal.status)
        else:
            response = PlainTextResponse(refusal.message, status_code=refusal.status)
        await response(scope, receive, send)


def install(app: FastAPI) -> None:
    # The last one added runs first: the headers go on the refusals too
    app.add_middleware(AccessGuard)
    app.add_middleware(SecurityHeaders)


def request_kind(request: Request) -> str:
    return client_kind(request.client.host if request.client else None, request.headers)


def is_local_request(request: Request) -> bool:
    """The request comes from the PC that runs PrixMalin (not from the phone)."""
    return request_kind(request) in ("local", "test")


def require_local(request: Request) -> None:
    if not is_local_request(request):
        raise AppError("Ce réglage se change sur le PC où PrixMalin est lancé.", 403, "local_only")


def _is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    # tailscale serve (https) on the same PC
    peer = request.client.host if request.client else None
    return is_loopback(peer) and request.headers.get("x-forwarded-proto", "").lower() == "https"


def _attempt_key(request: Request) -> str:
    """Counter of the wrong codes: the address of the connection.

    X-Forwarded-For only counts when the connection comes from the PC itself
    (tailscale serve): a device of the Wi-Fi could change it at each try.
    """
    peer = request.client.host if request.client else "?"
    if not is_loopback(peer):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
    return f"{peer}|{forwarded}" if forwarded else peer


# ---------------------------------------------------------------------------
# Routes (mounted by backend/api/updates.py, a router of P7)
# ---------------------------------------------------------------------------

router = APIRouter()


class AccessRequest(BaseModel):
    code: str = Field(max_length=32)


class AccessState(BaseModel):
    authorized: bool
    local: bool


class SecurityUpdate(BaseModel):
    allow_lan: bool


class SecurityState(BaseModel):
    local: bool  # the page is shown on the PC
    allow_lan: bool  # « Autoriser l'accès depuis le téléphone »
    lan_active: bool  # this run of PrixMalin listens on the network
    restart_needed: bool  # the setting takes effect at the next start
    forced_host: str | None = None  # PRIXMALIN_HOST: the setting has no effect
    code: str | None = None  # « 123 456 », on the PC only
    code_created_at: float | None = None


@router.get("/access", response_model=AccessState)
async def api_access_state(request: Request):
    local = is_local_request(request)
    return AccessState(authorized=local or token_ok(access_secret(), request.cookies.get(ACCESS_COOKIE)), local=local)


@router.post("/access", response_model=AccessState)
async def api_access(body: AccessRequest, request: Request, response: Response):
    """The phone types the code: it gets the cookie (valid one year)."""
    if is_local_request(request):
        return AccessState(authorized=True, local=True)
    client = _attempt_key(request)
    now = time.monotonic()
    wait = attempts.retry_after(client, now)
    if wait > 0:
        raise AppError("Trop d'essais. Attendez une minute avant de réessayer.", 429, "too_many_attempts")
    secret = access_secret()
    if not code_ok(secret, body.code):
        attempts.failed(client, now)
        logger.warning("Wrong access code typed from %s", request.client.host if request.client else "?")
        raise AppError("Code incorrect. Vérifiez le code affiché sur le PC.", 403, "wrong_code")
    attempts.succeeded(client)
    response.set_cookie(
        ACCESS_COOKIE,
        access_token(secret),
        max_age=COOKIE_MAX_AGE,
        path="/",
        httponly=True,
        samesite="strict",
        secure=_is_https(request),
    )
    logger.info("Phone allowed: %s", request.client.host if request.client else "?")
    return AccessState(authorized=True, local=False)


async def security_state(request: Request) -> SecurityState:
    local = is_local_request(request)
    allow = (await prefs.get(PREFS_SECTION, SecurityPrefs)).allow_lan
    active = lan_active()
    state = SecurityState(
        local=local,
        allow_lan=allow,
        lan_active=active,
        restart_needed=not config.HOST_FROM_ENV and allow != active,
        forced_host=config.HOST if config.HOST_FROM_ENV else None,
    )
    if local:
        secret = access_secret()
        state.code, state.code_created_at = code_text(secret.code), secret.created_at
    return state


@router.get("/security", response_model=SecurityState)
async def api_security(request: Request):
    return await security_state(request)


@router.patch("/security", response_model=SecurityState)
async def api_security_update(body: SecurityUpdate, request: Request):
    require_local(request)

    def change(p: SecurityPrefs) -> None:
        p.allow_lan = body.allow_lan

    await prefs.update(PREFS_SECTION, SecurityPrefs, change)
    logger.info("Access from the phone %s", "allowed" if body.allow_lan else "disabled")
    return await security_state(request)


@router.post("/security/code", response_model=SecurityState)
async def api_security_new_code(request: Request):
    require_local(request)
    renew_secret()
    return await security_state(request)
