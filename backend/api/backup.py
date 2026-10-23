"""Backup and restore of the data (area of P7; parts given by hooks.register_backup).

GET  /api/backup        → the backup file (JSON, downloaded as prixmalin-sauvegarde-AAAA-MM-JJ.json)
POST /api/restore       → {mode: "replace" | "merge", backup: <file>} (10 Mo at most)
GET  /api/backup/info   → daily copies of the database (number, last one), data folder (PC only)
"""

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend import backup
from backend.errors import AppError
from backend.security import is_local_request

router = APIRouter()

TOO_BIG = "Ce fichier est trop gros pour une sauvegarde de PrixMalin (10 Mo au plus)."


@router.get("/backup")
async def api_backup():
    data = await backup.export_all()
    name = backup.backup_file_name()
    return JSONResponse(
        data,
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )


async def read_limited(request: Request, limit: int) -> bytes:
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > limit:
        raise AppError(TOO_BIG, 413, "too_big")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise AppError(TOO_BIG, 413, "too_big")
    return bytes(body)


@router.post("/restore", response_model=backup.RestoreResult)
async def api_restore(request: Request):
    raw = await read_limited(request, backup.MAX_RESTORE_BYTES)
    try:
        body = backup.RestoreRequest.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as e:
        raise AppError(
            "Ce fichier n'est pas une sauvegarde de PrixMalin : rien n'a été changé.", 422, "backup_invalid"
        ) from e
    return await backup.restore_all(body)


@router.get("/backup/info", response_model=backup.CopiesInfo)
async def api_backup_info(request: Request):
    return backup.copies_info(is_local_request(request))
