"""Preferences of each area, stored as JSON in the ``pref:<section>`` key of ``settings``.

    display = await prefs.get("display", DisplayPrefs)
    await prefs.update("display", DisplayPrefs, lambda p: setattr(p, "theme", "dark"))

``update`` reads, changes and writes under one global lock: concurrent
updates of the same or of different sections are never lost. ``fn`` receives
the current model; it may change it in place or return a new one, and may be
a coroutine function.
"""

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from backend.repos import settings_store

logger = logging.getLogger("prixmalin.prefs")

M = TypeVar("M", bound=BaseModel)

_lock: tuple[asyncio.AbstractEventLoop, asyncio.Lock] | None = None


def _get_lock() -> asyncio.Lock:
    global _lock
    loop = asyncio.get_running_loop()
    if _lock is None or _lock[0] is not loop:
        _lock = (loop, asyncio.Lock())
    return _lock[1]


def key(section: str) -> str:
    return f"pref:{section}"


async def _read(section: str, model: type[M]) -> M:
    raw = await settings_store.get_setting(key(section))
    if raw:
        try:
            return model.model_validate_json(raw)
        except ValidationError:
            logger.warning("Invalid preferences %s, using the defaults", section)
    return model()


async def get(section: str, model: type[M]) -> M:
    """The preferences of ``section`` (the defaults of ``model`` when none are saved)."""
    return await _read(section, model)


async def update(section: str, model: type[M], fn: Callable[[M], Any]) -> M:
    """Change the preferences of ``section`` with ``fn`` and save them; returns them."""
    async with _get_lock():
        current = await _read(section, model)
        result = fn(current)
        if inspect.isawaitable(result):
            result = await result
        new = result if isinstance(result, BaseModel) else current
        new = model.model_validate(new.model_dump())
        await settings_store.set_setting(key(section), new.model_dump_json())
        return new
