"""Security of the web server (area of P7).

P0 provides the entry points: ``install(app)`` (HTTP headers below, on every
response) and ``is_local_request(request)``.
"""

from fastapi import FastAPI, Request
from starlette.datastructures import MutableHeaders

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

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


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


def install(app: FastAPI) -> None:
    app.add_middleware(SecurityHeaders)


def is_local_request(request: Request) -> bool:
    """The request comes from the PC that runs PrixMalin (not from the phone)."""
    host = request.client.host if request.client else ""
    return host in _LOCAL_HOSTS or host.startswith("127.")
