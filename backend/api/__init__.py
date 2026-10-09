"""HTTP API, one router per area, all under ``/api``.

To add an area: create ``backend/api/<area>.py`` with ``router = APIRouter()``
and add the module to ``ROUTERS`` below.
"""

from fastapi import APIRouter

from backend.api import browser_routes, retailers, search, settings, shopping_list

ROUTERS = (search, retailers, settings, browser_routes, shopping_list)

api_router = APIRouter(prefix="/api")
for _module in ROUTERS:
    api_router.include_router(_module.router)
