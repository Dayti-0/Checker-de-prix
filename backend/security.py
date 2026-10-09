"""Security of the web server (area of P7).

P0 provides the entry points: ``install(app)`` (HTTP headers) and
``is_local_request(request)``.
"""

from fastapi import FastAPI, Request

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def install(app: FastAPI) -> None:
    """Security headers on every response (added with the Content-Security-Policy)."""


def is_local_request(request: Request) -> bool:
    """The request comes from the PC that runs PrixMalin (not from the phone)."""
    host = request.client.host if request.client else ""
    return host in _LOCAL_HOSTS or host.startswith("127.")
