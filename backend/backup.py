"""Data of PrixMalin (area of P7): folder outside the app, backups, daily copies of the database.

- ``migrate_legacy_data()``: before 3.0 the data were in ``./data`` (folder of
  the app). ``run()`` moves it, before anything opens it, to
  ``%LOCALAPPDATA%\\PrixMalin`` (``~/.local/share/prixmalin`` elsewhere) when
  that folder does not exist yet; a file in use (a Chrome window of
  Intermarché still open) keeps ``./data`` for this time, and the move is
  tried again at the next start.
- ``export_all()`` / ``restore_all()``: the backup file (JSON, versioned) of
  every provider of ``hooks.register_backup`` (settings, list…), never the
  browser profiles nor the access code of the phone. Restore: « replace »
  (each part replaced) or « merge » (what is missing is added, what exists is
  kept), all or nothing (one transaction).
- ``daily_copy()``: one copy of the database a day in ``data/backups/``
  (SQLite backup API: consistent while the app writes), 7 kept.
"""

import asyncio
import errno
import logging
import os
import re
import shutil
import sqlite3
import time
from collections.abc import Callable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend import __version__, config, database
from backend.errors import AppError
from backend.services import hooks

logger = logging.getLogger("prixmalin.backup")

BACKUP_FORMAT = "prixmalin"
BACKUP_VERSION = 1
MAX_RESTORE_BYTES = 10 * 1024 * 1024

COPIES_DIR = "backups"
KEEP_COPIES = 7
COPY_EVERY_SECONDS = 6 * 3600  # the startup task looks every 6 hours whether today's copy exists
_COPY_NAME = re.compile(r"prixmalin-(\d{4}-\d{2}-\d{2})\.db")


# ---------------------------------------------------------------------------
# Folder of the data
# ---------------------------------------------------------------------------


def _cross_device(error: OSError) -> bool:
    return error.errno == errno.EXDEV or getattr(error, "winerror", None) == 17  # ERROR_NOT_SAME_DEVICE


def _copy_then_remove(source: Path, target: Path) -> str | None:
    """Move to another disk: copy, then remove the old folder. Returns a warning when it stays."""
    partial = target.with_name(target.name + ".copie-en-cours")
    shutil.rmtree(partial, ignore_errors=True)
    try:
        shutil.copytree(source, partial, symlinks=True)
        os.rename(partial, target)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    try:
        shutil.rmtree(source)
    except OSError as e:
        return f"Old data folder {source} could not be removed ({e}): the data are now in {target}"
    return None


def migrate_legacy_data(
    legacy: Path | None = None,
    target: Path | None = None,
    *,
    env: Mapping[str, str] = os.environ,
    in_use: Callable[[Path], bool] | None = None,
) -> tuple[int, str] | None:
    """Move ``./data`` to the folder of the data; returns ``(level, message)`` to log, or None.

    Called by ``run()`` before the logs are set up (they go into the folder).
    ``config`` points to the folder in use afterwards.
    """
    if env.get("PRIXMALIN_DATA_DIR"):
        return None
    legacy = legacy or config.LEGACY_DATA_DIR
    target = target or config.default_data_dir(env)
    if not legacy.is_dir():
        return None
    if target.exists():
        config.use_data_dir(target)
        return logging.WARNING, f"Old data folder {legacy} ignored: the data are in {target}"
    if in_use is not None and in_use(legacy):
        config.use_data_dir(legacy)
        return logging.WARNING, f"Data folder {legacy} in use by another PrixMalin: not moved"
    print(f"  Déplacement des données de PrixMalin vers {target}…", flush=True)
    warning = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(legacy, target)
        except OSError as e:
            if not _cross_device(e):
                raise
            warning = _copy_then_remove(legacy, target)
    except OSError as e:
        config.use_data_dir(legacy)
        return logging.WARNING, (
            f"Data folder not moved to {target}, {legacy} kept ({e}). Close the Chrome windows of "
            "Intermarché and E.Leclerc, then start PrixMalin again to move it."
        )
    config.use_data_dir(target)
    if warning:
        return logging.WARNING, warning
    return logging.INFO, f"Data folder moved from {legacy} to {target}"


# ---------------------------------------------------------------------------
# Backup file
# ---------------------------------------------------------------------------


class BackupFile(BaseModel):
    format: Literal["prixmalin"]
    version: int = Field(ge=1)
    app_version: str | None = Field(default=None, max_length=40)
    created_at: str | None = Field(default=None, max_length=40)
    sections: dict[str, Any]


class RestoreRequest(BaseModel):
    mode: Literal["replace", "merge"] = "replace"
    backup: BackupFile


class RestoreResult(BaseModel):
    mode: str
    restored: list[str]
    ignored: list[str]  # parts of the file unknown to this version


class CopiesInfo(BaseModel):
    count: int
    keep: int = KEEP_COPIES
    last_at: float | None = None
    data_dir: str | None = None  # on the PC only


def backup_file_name(day: date | None = None) -> str:
    return f"prixmalin-sauvegarde-{(day or date.today()):%Y-%m-%d}.json"


async def export_all(now: float | None = None) -> dict:
    sections = {}
    for name, (export_fn, _restore_fn) in sorted(hooks.backups().items()):
        try:
            sections[name] = await export_fn()
        except Exception as e:
            logger.exception("Backup of %s failed", name)
            raise AppError("La sauvegarde n'a pas pu être faite. Réessayez dans un instant.", 500, "backup") from e
    created = datetime.fromtimestamp(now or time.time()).astimezone()
    return {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "app_version": __version__,
        "created_at": created.isoformat(timespec="seconds"),
        "sections": sections,
    }


def _identity(item: Any) -> Any:
    """What makes two lines of a list the same (the query of a line of the shopping list...)."""
    if isinstance(item, dict):
        for key in ("query", "key", "name", "id"):
            if isinstance(item.get(key), str):
                return key, " ".join(item[key].lower().split())
        return tuple(sorted((k, repr(v)) for k, v in item.items() if k not in ("id", "created_at", "updated_at")))
    return repr(item)


def merge_section(current: Any, incoming: Any) -> Any:
    """« Merge »: what exists is kept, what is missing comes from the backup."""
    if isinstance(current, dict) and isinstance(incoming, dict):
        return {**incoming, **current}
    if isinstance(current, list) and isinstance(incoming, list):
        seen = {_identity(item) for item in current}
        added = [item for item in incoming if _identity(item) not in seen]
        return [*current, *added]
    return current if current not in (None, [], {}) else incoming


async def restore_all(request: RestoreRequest) -> RestoreResult:
    backup = request.backup
    if backup.version > BACKUP_VERSION:
        raise AppError(
            "Cette sauvegarde vient d'une version plus récente de PrixMalin : mettez PrixMalin à jour d'abord.",
            422,
            "backup_too_new",
        )
    providers = hooks.backups()
    restored = [name for name in backup.sections if name in providers]
    ignored = sorted(name for name in backup.sections if name not in providers)
    try:
        async with database.transaction():
            for name in restored:
                export_fn, restore_fn = providers[name]
                data = backup.sections[name]
                if request.mode == "merge":
                    data = merge_section(await export_fn(), data)
                await restore_fn(data)
    except AppError:
        raise
    except Exception as e:  # a part that does not fit (damaged file): nothing was changed
        logger.warning("Restore failed: %s", e)
        raise AppError("Ce fichier de sauvegarde est abîmé : rien n'a été changé.", 422, "backup_invalid") from e
    logger.info("Backup restored (%s): %s; ignored: %s", request.mode, restored, ignored)
    return RestoreResult(mode=request.mode, restored=restored, ignored=ignored)


# ---------------------------------------------------------------------------
# Daily copies of the database
# ---------------------------------------------------------------------------


def copies_dir() -> Path:
    return config.DATA_DIR / COPIES_DIR


def copy_name(day: date) -> str:
    return f"prixmalin-{day:%Y-%m-%d}.db"


def copies_to_delete(names: list[str], keep: int = KEEP_COPIES) -> list[str]:
    """The oldest copies beyond ``keep`` (other files are never touched)."""
    copies = sorted(name for name in names if _COPY_NAME.fullmatch(name))
    return copies[: max(0, len(copies) - keep)]


def copy_database(source: Path, dest: Path) -> None:
    """Consistent copy of the database while the app may write (SQLite backup API)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".partiel")
    partial.unlink(missing_ok=True)
    src = sqlite3.connect(source, timeout=10)
    try:
        out = sqlite3.connect(partial)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    os.replace(partial, dest)


async def daily_copy(today: date | None = None) -> Path | None:
    """Today's copy of the database (None when it exists already or there is no database)."""
    source = config.DB_PATH
    if not source.is_file():
        return None
    folder = copies_dir()
    dest = folder / copy_name(today or date.today())
    if dest.exists():
        return None
    await asyncio.to_thread(copy_database, source, dest)
    for name in copies_to_delete([f.name for f in folder.iterdir() if f.is_file()]):
        try:
            (folder / name).unlink()
        except OSError as e:
            logger.warning("Old copy %s not removed: %s", name, e)
    logger.info("Copy of the database: %s", dest.name)
    return dest


async def daily_copies() -> None:
    """Startup task of run(): one copy a day, checked every 6 hours."""
    while True:
        try:
            await daily_copy()
        except Exception:  # noqa: BLE001 (the next check tries again)
            logger.exception("Daily copy of the database failed")
        await asyncio.sleep(COPY_EVERY_SECONDS)


def copies_info(local: bool) -> CopiesInfo:
    folder = copies_dir()
    files = [f for f in folder.iterdir() if f.is_file() and _COPY_NAME.fullmatch(f.name)] if folder.is_dir() else []
    last = max((f.stat().st_mtime for f in files), default=None)
    return CopiesInfo(count=len(files), last_at=last, data_dir=str(config.DATA_DIR) if local else None)
