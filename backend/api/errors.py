"""Errors of the API in one place: each known exception becomes a JSON answer.

``{"detail": "<message en français>", "code": "<code>"}`` with:

| Exception                     | HTTP | code                         |
|-------------------------------|------|------------------------------|
| AppError (backend/errors.py)  | its status_code | its code          |
| BrowserUnavailable            | 502  | browser_unavailable          |
| ScraperError (and subclasses) | 502  | its status (blocked...)      |
| TimeoutError (asyncio too)    | 504  | timeout                      |
| HTTPException                 | its status | http_<status>          |
| RequestValidationError        | 422  | validation                   |

``guard(action)`` turns any other error of a block into a 502 whose message
starts with ``action``.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from http import HTTPStatus

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.browser import BrowserUnavailable
from backend.errors import AppError, short_error
from backend.scrapers.base import ScraperError

logger = logging.getLogger("prixmalin.api")

TIMEOUT_MESSAGE = "Le site n'a pas répondu à temps. Réessayez dans un instant."


def error_response(status_code: int, message: str, code: str) -> JSONResponse:
    return JSONResponse({"detail": message, "code": code}, status_code=status_code)


async def _app_error(request: Request, error: AppError) -> JSONResponse:
    return error_response(error.status_code, error.message, error.code)


async def _browser_unavailable(request: Request, error: BrowserUnavailable) -> JSONResponse:
    return error_response(502, str(error), "browser_unavailable")


async def _scraper_error(request: Request, error: ScraperError) -> JSONResponse:
    return error_response(502, str(error), error.status)


async def _timeout(request: Request, error: TimeoutError) -> JSONResponse:
    return error_response(504, TIMEOUT_MESSAGE, "timeout")


# Default English phrases of Starlette, shown to the user in French
HTTP_MESSAGES = {
    400: "Requête invalide.",
    401: "Accès refusé.",
    403: "Accès interdit.",
    404: "Introuvable.",
    405: "Action non autorisée.",
    413: "Envoi trop volumineux.",
    429: "Trop de demandes, réessayez dans un instant.",
}


async def _http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
    detail = error.detail if isinstance(error.detail, str) else ""
    # Messages written in French by the routes are kept; Starlette's defaults are translated
    try:
        default = HTTPStatus(error.status_code).phrase
    except ValueError:
        default = ""
    if not detail or detail == default:
        detail = HTTP_MESSAGES.get(error.status_code, "Erreur.")
    response = error_response(error.status_code, detail, f"http_{error.status_code}")
    for name, value in (error.headers or {}).items():
        response.headers[name] = value
    return response


# Type of the errors whose message is written for the user (backend/models/settings.py)
USER_MESSAGE_TYPE = "invalid"


async def _validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    errors = error.errors()
    if errors and all(e.get("type") == USER_MESSAGE_TYPE for e in errors):
        # Messages written in French for the user (« Saisissez 5 chiffres… »)
        message = " ".join(dict.fromkeys(str(e.get("msg", "")) for e in errors))
        return error_response(422, message, "validation")
    # Field names only: the submitted values are never echoed back
    fields = sorted({".".join(str(part) for part in e.get("loc", ())[1:]) or "requête" for e in errors})
    message = "Données invalides : " + ", ".join(fields) + "."
    return error_response(422, message, "validation")


def install(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(BrowserUnavailable, _browser_unavailable)
    app.add_exception_handler(ScraperError, _scraper_error)
    app.add_exception_handler(TimeoutError, _timeout)


@contextmanager
def guard(action: str, timeout_message: str | None = None) -> Iterator[None]:
    """Turn an unexpected error into a 502 « ``action`` : <first line of the error> ».

    The errors listed above keep their own answer; a timeout gets
    ``timeout_message`` when one is given.
    """
    try:
        yield
    except (HTTPException, AppError, BrowserUnavailable, ScraperError):
        raise
    except TimeoutError as e:
        if timeout_message is None:
            raise
        raise AppError(timeout_message, 504, "timeout") from e
    except Exception as e:
        logger.exception("%s", action)
        raise AppError(f"{action} : {short_error(e)}", 502, "unexpected") from e
