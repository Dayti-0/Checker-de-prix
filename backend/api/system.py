"""The web page and the app itself: index.html, static files, version (area of P1, except /api/version)."""

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import __version__, config

# Mounted under /api
router = APIRouter()
# Mounted at the root of the site
pages = APIRouter()


@router.get("/version")
async def api_version():
    return {"version": __version__}


@pages.get("/")
async def index():
    return FileResponse(config.FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@pages.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


class FrontendFiles(StaticFiles):
    """Static files revalidated on each load.

    The JavaScript ES modules import each other without a version in their
    URL: without this header the browser could mix old and new modules after
    an update of the app.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


def mount_frontend(app: FastAPI) -> None:
    app.mount("/static", FrontendFiles(directory=str(config.FRONTEND_DIR)), name="static")
