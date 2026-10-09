"""HTTP API: a fixed list of routers, one module per area (stubs included).

Each module of ``ROUTERS`` defines ``router`` (mounted under ``/api``) and may
define ``pages`` (mounted at the root of the site, e.g. ``/`` for index.html).
A lot fills its own module; the list below does not change.
"""

from fastapi import APIRouter

from backend.api import (
    backup,
    basket,
    browser,
    retailers,
    search,
    settings,
    shopping_list,
    status,
    system,
    tracking,
    updates,
)

ROUTERS = (search, retailers, settings, browser, shopping_list, basket, system, status, tracking, backup, updates)

api_router = APIRouter(prefix="/api")
pages_router = APIRouter()
for _module in ROUTERS:
    api_router.include_router(_module.router)
    if hasattr(_module, "pages"):
        pages_router.include_router(_module.pages)
