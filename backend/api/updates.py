"""Routes of P7 besides the backups: updates, address for the phone, access code and security.

The list of routers is fixed (backend/api/__init__.py): this module also
carries the routes of backend/security.py (``/api/access``, ``/api/security``).

GET   /api/updates          → state of the last check (no request to GitHub)
POST  /api/updates/check    → check now (GitHub API, latest release)
PATCH /api/updates {enabled}→ automatic check once a day (on by default)
GET   /api/system/phone     → address to open on the phone, QR code, network state
GET   /api/system/phone-qr.svg → QR code of that address

The automatic check is a startup task of ``run()`` (``auto_check``), never of
the tests: at most one request to the GitHub API a day.
"""

import asyncio
import logging
import re
import time

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel

from backend import __version__, config, instance, security
from backend.errors import AppError
from backend.services import prefs

logger = logging.getLogger("prixmalin.updates")

router = APIRouter()
router.include_router(security.router)

UPDATES_SECTION = "p7.updates"
CHECK_INTERVAL_SECONDS = 24 * 3600
HTTP_TIMEOUT_SECONDS = 10.0
# Tests: httpx.MockTransport(...)
HTTP_TRANSPORT: httpx.AsyncBaseTransport | None = None

_VERSION = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")


class UpdatePrefs(BaseModel):
    enabled: bool = True
    checked_at: float | None = None
    latest: str | None = None  # "3.1.0", None when the repository has no release
    url: str | None = None  # page of the release
    failure: str | None = None  # last check: "network" (no Internet) or "github" (GitHub refused or failed)


class UpdateState(BaseModel):
    current: str
    latest: str | None = None
    available: bool = False
    enabled: bool = True
    checked_at: float | None = None
    url: str | None = None
    error: str | None = None


class UpdateSettings(BaseModel):
    enabled: bool


class PhoneInfo(BaseModel):
    url: str | None  # http://192.168.1.10:8000, None without network
    others: list[str] = []  # other addresses of this PC (VPN, second network card)
    lan_active: bool  # this run of PrixMalin listens on the network
    allow_lan: bool  # « Autoriser l'accès depuis le téléphone »
    qr: bool  # GET /api/system/phone-qr.svg gives the QR code
    local: bool  # the page is shown on the PC


# ---------------------------------------------------------------------------
# Versions (pure)
# ---------------------------------------------------------------------------


def parse_version(text: str | None) -> tuple[int, int, int] | None:
    """``"v3.0.0"`` → ``(3, 0, 0)``; ``"3.1"`` → ``(3, 1, 0)``; None for another form (« 3.0.0-rc1 »)."""
    match = _VERSION.match((text or "").strip())
    if not match:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def is_newer(latest: str | None, current: str) -> bool:
    new, now = parse_version(latest), parse_version(current)
    return bool(new and now and new > now)


def check_due(p: UpdatePrefs, now: float) -> bool:
    """The automatic check runs at most once a day."""
    return p.enabled and (p.checked_at is None or not 0 <= now - p.checked_at < CHECK_INTERVAL_SECONDS)


def release_of(data: object) -> tuple[str, str | None] | None:
    """``(version, url)`` of an answer of /releases/latest (drafts and pre-releases ignored)."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    version = parse_version(str(data.get("tag_name") or ""))
    if version is None:
        return None
    url = data.get("html_url")
    url = url if isinstance(url, str) and url.startswith("https://github.com/") else None
    return ".".join(map(str, version)), url


FAILURE_MESSAGES = {
    "network": "La dernière vérification n'a pas pu joindre Internet.",
    "github": "GitHub n'a pas répondu à la dernière vérification.",
}


def state_of(p: UpdatePrefs) -> UpdateState:
    return UpdateState(
        current=__version__,
        latest=p.latest,
        available=is_newer(p.latest, __version__),
        enabled=p.enabled,
        checked_at=p.checked_at,
        url=p.url,
        error=FAILURE_MESSAGES.get(p.failure or ""),
    )


# ---------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------


async def fetch_latest() -> tuple[str, str | None] | None:
    """Latest release on GitHub (None: no release yet). Raises httpx.HTTPError when unreachable."""
    url = f"https://api.github.com/repos/{config.UPDATES_REPO}/releases/latest"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": f"PrixMalin/{__version__}"}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, transport=HTTP_TRANSPORT) as client:
        answer = await client.get(url, headers=headers)
    if answer.status_code == 404:
        return None
    answer.raise_for_status()
    return release_of(answer.json())


async def check(now: float | None = None) -> UpdateState:
    now = now or time.time()
    found, failure = None, None
    try:
        found = await fetch_latest()
    except httpx.HTTPStatusError as e:  # 403 (limit of the GitHub API), 5xx: Internet works
        logger.info("Update check refused by GitHub: HTTP %s", e.response.status_code)
        failure = "github"
    except (httpx.HTTPError, ValueError) as e:
        logger.info("Update check failed: %s", e)
        failure = "network"

    def change(p: UpdatePrefs) -> None:
        p.checked_at = now
        p.failure = failure
        if failure is None:
            p.latest, p.url = found if found else (None, None)

    p = await prefs.update(UPDATES_SECTION, UpdatePrefs, change)
    if failure is None:
        logger.info("Update check: latest %s, current %s", p.latest or "none", __version__)
    return state_of(p)


async def auto_check() -> None:
    """Startup task of run(): the check once a day while PrixMalin runs (unless disabled)."""
    while True:
        try:
            if check_due(await prefs.get(UPDATES_SECTION, UpdatePrefs), time.time()):
                await check()
        except Exception:  # noqa: BLE001 (tried again later)
            logger.exception("Automatic update check failed")
        await asyncio.sleep(3600)


@router.get("/updates", response_model=UpdateState)
async def api_updates():
    return state_of(await prefs.get(UPDATES_SECTION, UpdatePrefs))


@router.post("/updates/check", response_model=UpdateState)
async def api_updates_check():
    return await check()


@router.patch("/updates", response_model=UpdateState)
async def api_updates_settings(body: UpdateSettings):
    def change(p: UpdatePrefs) -> None:
        p.enabled = body.enabled

    return state_of(await prefs.update(UPDATES_SECTION, UpdatePrefs, change))


# ---------------------------------------------------------------------------
# Address for the phone
# ---------------------------------------------------------------------------


def request_port(request: Request) -> int:
    """Port of the address the page was opened with (the real one in the tests and the demo)."""
    return request.url.port or config.PORT


async def phone_urls(request: Request) -> list[str]:
    """Addresses to open on the phone, best first (none when the network access is off)."""
    if not security.lan_active() or not await security.lan_allowed():
        return []
    scheme = "https" if request.url.scheme == "https" or config.scheme() == "https" else "http"
    port = request_port(request)
    return [instance.phone_url(ip, port, scheme) for ip in await asyncio.to_thread(instance.lan_ips)]


async def phone_url(request: Request) -> str | None:
    urls = await phone_urls(request)
    return urls[0] if urls else None


@router.get("/system/phone", response_model=PhoneInfo)
async def api_phone(request: Request):
    urls = await phone_urls(request)
    url = urls[0] if urls else None
    return PhoneInfo(
        url=url,
        others=urls[1:],
        lan_active=security.lan_active(),
        allow_lan=await security.lan_allowed(),
        qr=bool(url) and instance.qr_available(),
        local=security.is_local_request(request),
    )


@router.get("/system/phone-qr.svg")
async def api_phone_qr(request: Request):
    url = await phone_url(request)
    svg = instance.qr_svg(url) if url else None
    if svg is None:
        raise AppError("QR code indisponible.", 404, "no_qr")
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})
