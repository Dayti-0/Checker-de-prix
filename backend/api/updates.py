"""Routes of P7 besides the backups: phone access and security (this commit), more below.

The list of routers is fixed (backend/api/__init__.py): this module also
carries the routes of backend/security.py (``/api/access``, ``/api/security``).
"""

from fastapi import APIRouter

from backend import security

router = APIRouter()
router.include_router(security.router)
