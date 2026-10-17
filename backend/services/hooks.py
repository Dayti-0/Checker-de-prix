"""Extension points between the areas of the app: events, startup tasks, backups.

Events (keyword arguments only; P3 and P5 keep emitting them):

- ``search_finished(result, query, store_ctx, from_cache)``: a search at one
  retailer is over (``result``: StoreResult), emitted by services/search.py;
- ``products_scraped(store, store_ctx, query, products)``: products were read on
  a retailer site (not from the cache), emitted by services/search.py;
- ``basket_compared(comparison)``: a basket comparison is over
  (BasketComparison), emitted by services/basket.py.

``store_ctx`` is the store context of the retailer (``scraper.context_key``:
the id or address of the chosen store, "" for national prices).

Each listener is isolated: its errors are logged and never reach the caller.
Listeners run one after the other and the caller waits for them: a slow one
should start its own task (``asyncio.create_task``).
"""

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("prixmalin.hooks")

EVENTS = ("search_finished", "products_scraped", "basket_compared")

_listeners: dict[str, list[Callable[..., Any]]] = {}
_startup: list[Callable[[], Awaitable[Any]]] = []
_backups: dict[str, tuple[Callable[[], Awaitable[Any]], Callable[[Any], Awaitable[Any]]]] = {}


def on(event: str, fn: Callable[..., Any]) -> Callable[[], None]:
    """Call ``fn(**kwargs)`` (function or coroutine function) at each ``event``.

    Returns the function that removes the listener.
    """
    listeners = _listeners.setdefault(event, [])
    listeners.append(fn)

    def off() -> None:
        if fn in listeners:
            listeners.remove(fn)

    return off


async def emit(event: str, **kwargs: Any) -> None:
    for fn in list(_listeners.get(event, ())):
        try:
            result = fn(**kwargs)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 (a listener never breaks the caller)
            logger.exception("Listener %r of %s failed", fn, event)


def on_startup(fn: Callable[[], Awaitable[Any]]) -> Callable[[], Awaitable[Any]]:
    """Run the coroutine function ``fn()`` in the background when the app starts.

    The task is cancelled when the app stops. Registering twice is harmless.
    Usable as a decorator.
    """
    if fn not in _startup:
        _startup.append(fn)
    return fn


def startup_hooks() -> list[Callable[[], Awaitable[Any]]]:
    return list(_startup)


def register_backup(
    name: str,
    export_fn: Callable[[], Awaitable[Any]],
    restore_fn: Callable[[Any], Awaitable[Any]],
) -> None:
    """Provider of a part of the backups: ``await export_fn()`` returns JSON data,
    ``await restore_fn(data)`` puts it back (replacing the current data)."""
    _backups[name] = (export_fn, restore_fn)


def backups() -> dict[str, tuple[Callable[[], Awaitable[Any]], Callable[[Any], Awaitable[Any]]]]:
    return dict(_backups)
