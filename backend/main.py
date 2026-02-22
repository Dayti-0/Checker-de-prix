import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.config import BASE_DIR
from backend.database import close_db
from backend.models import AppConfig, LocationConfig, SearchResponse
from backend.services.location import get_app_config, set_postal_code
from backend.services.search import search_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_db()


app = FastAPI(title="PrixMalin", version="1.0.0", lifespan=lifespan)


# --- API routes ---


@app.get("/api/search", response_model=SearchResponse)
async def api_search(
    q: str = Query(..., min_length=1, description="Product search query"),
    stores: str | None = Query(None, description="Comma-separated store names"),
):
    store_list = [s.strip() for s in stores.split(",") if s.strip()] if stores else None
    return await search_all(q, store_list)


@app.post("/api/config/location", response_model=AppConfig)
async def api_set_location(body: LocationConfig):
    return await set_postal_code(body.postal_code)


@app.get("/api/config/stores", response_model=AppConfig)
async def api_get_stores():
    return await get_app_config()


# --- Static files (frontend) ---

FRONTEND_DIR = BASE_DIR / "frontend"


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/favicon.ico")
async def favicon():
    # Return an empty 204 to suppress browser 404 requests
    return Response(status_code=204)


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
