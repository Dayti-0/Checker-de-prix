"""Errors of the API in one place: each known exception becomes a JSON answer.

``{"detail": "<message en français>", "code": "<code>"}`` with:

| Exception                     | HTTP | code                         |
|-------------------------------|------|------------------------------|
| AppError (backend/errors.py)  | its status_code | its code          |
| BrowserUnavailable            | 502  | browser_unavailable          |
| ScraperError (and subclasses) | 502  | its status (blocked...)      |
| TimeoutError (asyncio too)    | 504  | timeout                      |

``guard(action)`` turns any other error of a block into a 502 whose message
starts with ``action``.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

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


def install(app: FastAPI) -> None:
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
