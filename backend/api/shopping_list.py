"""Shopping list and basket comparison."""

from fastapi import APIRouter, HTTPException

from backend import database
from backend.models import BasketComparison, BasketRequest, ListItem, ListItemCreate, ListItemUpdate
from backend.services import basket

router = APIRouter()


@router.get("/list", response_model=list[ListItem])
async def api_list():
    return await basket.get_list()


@router.post("/list", response_model=ListItem)
async def api_list_add(item: ListItemCreate):
    return await basket.add_item(item)


@router.patch("/list/{item_id}", response_model=ListItem)
async def api_list_update(item_id: int, update: ListItemUpdate):
    item = await basket.update_item(item_id, update)
    if item is None:
        raise HTTPException(404, "Article introuvable")
    return item


@router.delete("/list/{item_id}", status_code=204)
async def api_list_delete(item_id: int):
    await database.delete_item(item_id)


@router.delete("/list", status_code=204)
async def api_list_clear():
    await database.clear_items()


@router.post("/basket/compare", response_model=BasketComparison)
async def api_basket_compare(request: BasketRequest):
    return await basket.compare_basket(request.stores, request.refresh)
