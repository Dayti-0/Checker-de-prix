"""When PrixMalin stops calling a retailer for a while (area of P3).

Two mechanisms:

- **hard blocks** (``HardBlocks``): the site refused the connection (DataDome
  « Accès temporairement restreint », ``t=bv``, HTTP 429). No call at all to
  the retailer for 30 minutes, doubled at each new block (at most 4 hours),
  whatever the user does. Kept in the ``p3.blocks`` preferences (SQLite) so a
  restart does not shorten the pause. Enforced by ``browser.run`` (every call
  to a site goes through it) and by ``search.search_store``.
- **circuit breaker** (``Circuit``, in memory, per retailer and store): after
  an anti-robot check or « store required », the retailer is not called for
  10 minutes, or until « J'ai terminé » or a change of store; after 2 timeouts
  in a row, for 2 minutes. While it is open a search answers at once (with the
  older prices when there are some). A search asked again by the user
  (``refresh``) goes through, except for an anti-robot check of a retailer
  driven by its own Chrome window (Intermarché): there, only « Ouvrir le site »
  then « J'ai terminé » reopens the circuit.

The decisions are pure functions (``next_hard_block``, ``after_result``,
``may_call``), tested in tests/test_p3_circuit.py.
"""

import logging
import time
from dataclasses import dataclass, replace

from backend import config
from backend.models import BlockRecord, BlockRecords, RetailerState

logger = logging.getLogger("prixmalin.circuit")

PREFS_SECTION = "p3.blocks"

# A new hard block more than this after the end of the previous pause starts
# again from 30 minutes
HARD_BLOCK_RESET_SECONDS = 24 * 60 * 60

# Ranks of browser.PRIORITIES
INTERACTIVE = "interactive"


# ---------------------------------------------------------------------------
# Hard blocks
# ---------------------------------------------------------------------------


def next_hard_block(previous: BlockRecord | None, now: float) -> BlockRecord:
    """Record after a new hard block at ``now``: pause of 30 min, doubled each time, at most 4 h."""
    base = config.HARD_BLOCK_COOLDOWN_SECONDS
    previous = previous or BlockRecord()
    recent = previous.last_hard_block and now - max(previous.until, previous.last_hard_block) < HARD_BLOCK_RESET_SECONDS
    seconds = min(max(previous.seconds * 2, base), config.HARD_BLOCK_COOLDOWN_MAX_SECONDS) if recent else base
    return BlockRecord(until=now + seconds, seconds=seconds, last_hard_block=now, last_blocked=now)


class HardBlocks:
    """Hard blocks of every retailer, in memory and (``persist``) in the preferences."""

    def __init__(self, persist: bool = False) -> None:
        self.persist = persist
        self._records: dict[str, BlockRecord] = {}
        # Database the records were read from (each test has its own)
        self._loaded_from: str | None = None

    async def load(self) -> None:
        """Read the records saved in the database (once per database)."""
        if not self.persist or self._loaded_from == str(config.DB_PATH):
            return
        from backend.services import prefs

        saved = await prefs.get(PREFS_SECTION, BlockRecords)
        self._records = dict(saved.retailers)
        self._loaded_from = str(config.DB_PATH)

    def record(self, key: str) -> BlockRecord:
        """Record of ``key`` in memory (``get`` reads the database first)."""
        return self._records.get(key) or BlockRecord()

    async def get(self, key: str) -> BlockRecord:
        await self.load()
        return self.record(key)

    def active(self, now: float | None = None) -> dict[str, float]:
        """``{key: end of the pause}`` of the retailers paused now (memory only)."""
        now = time.time() if now is None else now
        return {key: r.until for key, r in self._records.items() if r.until > now}

    async def until(self, key: str, now: float | None = None) -> float | None:
        """End of the pause of ``key``, or None when the retailer may be called."""
        await self.load()
        now = time.time() if now is None else now
        until = self.record(key).until
        return until if until > now else None

    async def hard_block(self, key: str, now: float | None = None) -> BlockRecord:
        """The site of ``key`` refused the connection: start (or lengthen) its pause."""
        await self.load()
        record = next_hard_block(self._records.get(key), time.time() if now is None else now)
        logger.warning("%s refused the connection: no call before %s s from now", key, int(record.seconds))
        return await self._save(key, record)

    async def blocked(self, key: str, now: float | None = None) -> None:
        """The site of ``key`` asked for an anti-robot check (remembered 24 h by the warm-up)."""
        await self.load()
        record = self.record(key).model_copy()
        record.last_blocked = time.time() if now is None else now
        await self._save(key, record)

    async def clear(self, key: str) -> None:
        await self.load()
        await self._save(key, None)

    async def _save(self, key: str, record: BlockRecord | None) -> BlockRecord | None:
        if record is None:
            self._records.pop(key, None)
        else:
            self._records[key] = record
        if self.persist:
            from backend.services import prefs

            def change(saved: BlockRecords) -> None:
                if record is None:
                    saved.retailers.pop(key, None)
                else:
                    saved.retailers[key] = record

            try:
                await prefs.update(PREFS_SECTION, BlockRecords, change)
            except Exception:  # noqa: BLE001 (still enforced in memory)
                logger.exception("Block of %s not saved", key)
        return record


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CircuitState:
    """Circuit of one retailer and store context."""

    reason: str | None = None  # "blocked", "store_required" or "timeout" while open
    until: float = 0.0
    timeouts: int = 0  # timeouts in a row
    status: str | None = None  # status and message of the answer that opened it
    message: str | None = None


def after_result(state: CircuitState | None, status: str, message: str | None, now: float) -> CircuitState:
    """State after a real call to the site that ended with ``status``."""
    state = state or CircuitState()
    if status in ("blocked", "store_required"):
        return CircuitState(status, now + config.CIRCUIT_BLOCKED_SECONDS, 0, status, message)
    if status == "timeout":
        timeouts = state.timeouts + 1
        if timeouts >= config.CIRCUIT_TIMEOUTS:
            return CircuitState("timeout", now + config.CIRCUIT_TIMEOUT_SECONDS, timeouts, status, message)
        return replace(state, timeouts=timeouts)
    if status in ("ok", "empty"):
        return CircuitState()
    return state  # "error" (site unreachable...): no change


def is_open(state: CircuitState | None, now: float) -> bool:
    return state is not None and state.until > now


def may_call(state: CircuitState | None, now: float, *, refresh: bool, priority: str, dedicated: bool) -> bool:
    """Whether a search may call the site (else it answers from the open circuit)."""
    if not is_open(state, now):
        return True
    if not refresh or priority != INTERACTIVE:
        return False
    # Intermarché: a new try before the check was validated in its window would
    # only show DataDome one more automated call
    return not (dedicated and state.reason == "blocked")


class Circuit:
    """Circuits of every (retailer, store context), in memory."""

    def __init__(self) -> None:
        self._states: dict[tuple[str, str], CircuitState] = {}

    def get(self, key: str, store_ctx: str) -> CircuitState | None:
        return self._states.get((key, store_ctx))

    def update(self, key: str, store_ctx: str, status: str, message: str | None, now: float | None = None) -> None:
        now = time.time() if now is None else now
        state = after_result(self._states.get((key, store_ctx)), status, message, now)
        if state == CircuitState():
            self._states.pop((key, store_ctx), None)
        else:
            self._states[(key, store_ctx)] = state

    def reset(self, key: str | None = None) -> None:
        """Close the circuits of ``key`` (« J'ai terminé »), or of every retailer."""
        for k in [k for k in self._states if key is None or k[0] == key]:
            del self._states[k]

    def state(self, key: str, hard: BlockRecord, now: float | None = None) -> RetailerState:
        now = time.time() if now is None else now
        result = RetailerState(store=key, last_blocked=hard.last_blocked or None)
        states = [s for (k, _), s in self._states.items() if k == key]
        if states:
            result.timeouts = max(s.timeouts for s in states)
        opened = [s for s in states if is_open(s, now)]
        if opened:
            longest = max(opened, key=lambda s: s.until)
            result.circuit_open, result.reason, result.until = True, longest.reason, longest.until
        if hard.until > now:
            result.circuit_open, result.reason = True, "hard_block"
            result.until = result.hard_block_until = hard.until
        return result
