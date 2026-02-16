import logging

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import BASE_DIR
from backend.database import close_db
from backend.models import SearchResponse
from backend.services.search import search_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="PrixMalin", version="1.0.0")


@app.on_event("shutdown")
async def shutdown():
    await close_db()


# --- API routes ---


@app.get("/api/search", response_model=SearchResponse)
async def api_search(
    q: str = Query(..., min_length=1, description="Product search query"),
    stores: str | None = Query(None, description="Comma-separated store names"),
):
    store_list = [s.strip() for s in stores.split(",") if s.strip()] if stores else None
    return await search_all(q, store_list)


# --- Static files (frontend) ---

FRONTEND_DIR = BASE_DIR / "frontend"


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
