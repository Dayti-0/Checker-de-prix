"""State of the retailers, debug snapshots and diagnostic report (area of P4)."""

import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from backend.models import RetailerHealth
from backend.services import health

router = APIRouter()


@router.get("/status/retailers", response_model=list[RetailerHealth])
async def api_status_retailers():
    return await health.all_health()


@router.get("/status/snapshot/{name}")
async def api_status_snapshot(name: str):
    """A page saved in data/debug/ (HTML and JSON shown as text, never run)."""
    path = health.snapshot_file(name)
    if path is None:
        raise HTTPException(404, "Capture introuvable.")
    return FileResponse(
        path,
        media_type=health.SNAPSHOT_TYPES[path.suffix[1:]],
        headers={
            "Cache-Control": "no-store",
            # A saved page of a retailer never runs anything here
            "Content-Security-Policy": "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'",
        },
    )


@router.get("/status/diagnostic.zip")
async def api_status_diagnostic():
    data = await health.diagnostic_zip()
    name = time.strftime("prixmalin-diagnostic-%Y%m%d-%H%M.zip")
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )
