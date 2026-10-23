"""Shopping list, usual items and saved lists (area of P5).

Static paths (``/list/version``, ``/list/usual``…) are declared before
``/list/{item_id}``.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from backend.api.common import get_scraper
from backend.models import (
    BulkRequest,
    ChecksRequest,
    FinishRequest,
    ListItem,
    ListItemCreate,
    ListItemUpdate,
    ListVersion,
    ParsedLine,
    ParseRequest,
    RestoreRequest,
    Template,
    TemplateApply,
    TemplateCreate,
    TemplateDetail,
    Trip,
    UsualItem,
)
from backend.services import basket, shopping_list

router = APIRouter()


@router.get("/list", response_model=list[ListItem])
async def api_list():
    return await shopping_list.get_list()


@router.post("/list", response_model=ListItem)
async def api_list_add(item: ListItemCreate):
    return await shopping_list.add_item(item)


@router.delete("/list", status_code=204)
async def api_list_clear():
    await shopping_list.clear()


@router.get("/list/version", response_model=ListVersion)
async def api_list_version():
    """Incremented at each change of the list: the pages poll it (PC ↔ téléphone)."""
    return ListVersion(version=await shopping_list.get_version())


@router.get("/list/categories", response_model=list[str])
async def api_list_categories():
    return shopping_list.categories()


@router.get("/list/usual", response_model=list[UsualItem])
async def api_list_usual():
    return await shopping_list.usual_items()


@router.delete("/list/usual", status_code=204)
async def api_list_forget_usual(query: str = Query(..., min_length=1, max_length=120)):
    await shopping_list.forget_usual(query)


@router.post("/list/parse", response_model=list[ParsedLine])
async def api_list_parse(request: ParseRequest):
    """Preview of « Coller une liste » (nothing is written)."""
    return await shopping_list.preview_text(request.text)


@router.post("/list/bulk", response_model=list[ListItem])
async def api_list_bulk(request: BulkRequest):
    return await shopping_list.bulk_add(request.items)


@router.post("/list/restore", response_model=list[ListItem])
async def api_list_restore(request: RestoreRequest):
    """« Annuler » after a deletion (or « Vider la liste »): the lines come back as the
    server kept them ({id} or {ids}); returns the list. 404 ``restore_expired`` when too late."""
    if not request.all_ids():
        raise HTTPException(422, "Aucun article à rétablir")
    return await shopping_list.restore_items(request.all_ids())


@router.post("/list/checks", response_model=list[ListItem])
async def api_list_checks(request: ChecksRequest):
    """Ticks made in the store (replayed after a loss of network: the latest wins)."""
    return await shopping_list.apply_checks(request.checks)


@router.post("/list/finish", response_model=list[ListItem])
async def api_list_finish(request: FinishRequest):
    """« Terminer » (``remove`` with ``ids``: only those lines); returns the list."""
    return await shopping_list.finish(request.mode, request.ids)


@router.get("/list/export")
async def api_list_export(
    format: Literal["txt", "csv"] = "txt",
    plan: int | None = Query(None, ge=0, le=10),
    store: str | None = None,
    download: bool = False,
):
    """The list as text or CSV, by retailer (``store``, or ``plan`` of the last basket) then by aisle."""
    if store is not None:
        get_scraper(store)
    items = await shopping_list.get_list()
    comparison = await basket.last_comparison() if plan is not None or store is not None else None
    assignment, labels = shopping_list.assignment_of(comparison, plan=plan, store=store)
    text = shopping_list.format_list(items, format, assignment, labels)
    headers = {"Cache-Control": "no-store"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="ma-liste.{format}"'
    if format == "csv":
        # BOM: a spreadsheet opens the accents correctly
        return Response("﻿" + text, media_type="text/csv; charset=utf-8", headers=headers)
    return Response(text, media_type="text/plain; charset=utf-8", headers=headers)


@router.get("/list/trip", response_model=Trip)
async def api_list_trip(
    plan: int | None = Query(None, ge=0, le=10),
    store: str | None = None,
):
    """Mode « En magasin »: the list by retailer (``store``, or ``plan`` of the last basket)
    then by aisle, with the product and the price retained; the whole list by aisle without them."""
    if store is not None:
        get_scraper(store)
    items = await shopping_list.get_list()
    comparison = await basket.last_comparison() if plan is not None or store is not None else None
    return shopping_list.trip_of(items, comparison, plan=plan, store=store)


@router.patch("/list/{item_id}", response_model=ListItem)
async def api_list_update(item_id: int, update: ListItemUpdate):
    item = await shopping_list.update_item(item_id, update)
    if item is None:
        raise HTTPException(404, "Article introuvable")
    return item


@router.delete("/list/{item_id}", status_code=204)
async def api_list_delete(item_id: int):
    await shopping_list.delete_item(item_id)


# --- Saved lists (« Courses de la semaine ») -------------------------------------


@router.get("/templates", response_model=list[Template])
async def api_templates():
    return await shopping_list.list_templates()


@router.post("/templates", response_model=Template)
async def api_template_save(request: TemplateCreate):
    """Save the list under a name (a list of that name is replaced)."""
    return await shopping_list.save_template(request.name)


@router.get("/templates/{template_id}", response_model=TemplateDetail)
async def api_template(template_id: int):
    template = await shopping_list.get_template(template_id)
    if template is None:
        raise HTTPException(404, "Liste enregistrée introuvable")
    return template


@router.delete("/templates/{template_id}", status_code=204)
async def api_template_delete(template_id: int):
    if not await shopping_list.delete_template(template_id):
        raise HTTPException(404, "Liste enregistrée introuvable")


@router.post("/templates/{template_id}/apply", response_model=list[ListItem])
async def api_template_apply(template_id: int, request: TemplateApply):
    items = await shopping_list.apply_template(template_id, request.mode)
    if items is None:
        raise HTTPException(404, "Liste enregistrée introuvable")
    return items
