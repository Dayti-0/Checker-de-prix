"""The web page and the app itself: index.html, static files, version (area of P1, except /api/version)."""

import mimetypes
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import __version__, config

# Mounted under /api
router = APIRouter()
# Mounted at the root of the site
pages = APIRouter()

# Types of the files of the frontend. Python guesses them with the mimetypes
# module, which reads the Windows registry: there ".js" may be "text/plain",
# and the browser then refuses to run the ES modules (blank page).
MEDIA_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".webmanifest": "application/manifest+json",
}


def fix_media_types() -> None:
    for extension, media_type in MEDIA_TYPES.items():
        mimetypes.add_type(media_type, extension)


@router.get("/version")
async def api_version():
    return {"version": __version__}


def index_html() -> str:
    """index.html with the version of the app in the addresses of its files."""
    page = (config.FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    return page.replace("__VERSION__", __version__)


@pages.get("/")
async def index():
    return HTMLResponse(index_html(), headers={"Cache-Control": "no-cache"})


@pages.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


class FrontendFiles(StaticFiles):
    """Static files with their exact type, revalidated on each load.

    The JavaScript ES modules import each other without a version in their
    URL: with "Cache-Control: no-cache" the browser asks each time and gets
    "304 Not Modified" (ETag) while the file did not change, so that it never
    mixes old and new modules after an update of the app.
    """

    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        media_type = MEDIA_TYPES.get(Path(full_path).suffix.lower())
        if media_type:
            charset = "; charset=utf-8" if media_type.startswith("text/") else ""
            response.headers["content-type"] = media_type + charset
        return response

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


def mount_frontend(app: FastAPI) -> None:
    fix_media_types()
    app.mount("/static", FrontendFiles(directory=str(config.FRONTEND_DIR)), name="static")
