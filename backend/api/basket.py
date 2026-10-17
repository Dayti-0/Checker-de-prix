"""Basket comparison (area of P5)."""

from fastapi import APIRouter

from backend.models import BasketComparison, BasketRequest
from backend.services import basket

router = APIRouter()


@router.post("/basket/compare", response_model=BasketComparison)
async def api_basket_compare(request: BasketRequest):
    return await basket.compare_basket(request.stores, request.refresh)
