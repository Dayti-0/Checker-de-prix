"""Shopping list (area of P5)."""

from fastapi import APIRouter, HTTPException

from backend.models import ListItem, ListItemCreate, ListItemUpdate
from backend.services import shopping_list

router = APIRouter()


@router.get("/list", response_model=list[ListItem])
async def api_list():
    return await shopping_list.get_list()


@router.post("/list", response_model=ListItem)
async def api_list_add(item: ListItemCreate):
    return await shopping_list.add_item(item)


@router.patch("/list/{item_id}", response_model=ListItem)
async def api_list_update(item_id: int, update: ListItemUpdate):
    item = await shopping_list.update_item(item_id, update)
    if item is None:
        raise HTTPException(404, "Article introuvable")
    return item


@router.delete("/list/{item_id}", status_code=204)
async def api_list_delete(item_id: int):
    await shopping_list.delete_item(item_id)


@router.delete("/list", status_code=204)
async def api_list_clear():
    await shopping_list.clear()
