"""Logs of the app (area of P7): a file for the diagnosis, one line per message in the console.

``configure()`` (called by ``run()``) sends every log of the app, uvicorn's
included, to ``data/logs/prixmalin.log`` (1 Mo, 5 old files kept, UTF-8, with
the full tracebacks) and to the console, where an error is a single line: the
user of the black window reads « Search failed (TimeoutError: …) », not forty
lines of Python. The access log of uvicorn (one line per request) only goes to
the file.

Never log a secret: the access code of the phone is printed to the console
with ``print()``, and the log files go into the diagnostic zip (services/health.py).
"""

import logging
import logging.handlers
import platform
import sys
import threading
from importlib import metadata
from pathlib import Path

from backend import __version__, config

FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
CONSOLE_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
CONSOLE_DATE_FORMAT = "%H:%M:%S"

LOG_FILE = "prixmalin.log"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 5

# Loggers of uvicorn: written by the handlers of the root logger (uvicorn.run(log_config=None))
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
# One line per HTTP request: in the file only
FILE_ONLY_LOGGERS = ("uvicorn.access",)
# One line per request of the app to a web service (geocoding, GitHub): warnings only
QUIET_LOGGERS = ("httpx", "httpcore")

logger = logging.getLogger("prixmalin.logs")

# Mark of the handlers installed here (configure() may be called twice)
_MARK = "_prixmalin_handler"


def log_dir() -> Path:
    return config.DATA_DIR / "logs"


class ConsoleFormatter(logging.Formatter):
    """One line per message: an exception is summed up as « (Type: first line) »."""

    def format(self, record: logging.LogRecord) -> str:
        exc_info, exc_text, stack_info = record.exc_info, record.exc_text, record.stack_info
        record.exc_info = record.exc_text = record.stack_info = None
        try:
            line = super().format(record)
        finally:
            record.exc_info, record.exc_text, record.stack_info = exc_info, exc_text, stack_info
        if exc_info and exc_info[1] is not None:
            error = exc_info[1]
            text = str(error).strip().splitlines()
            line += f" ({type(error).__name__}: {text[0][:200]})" if text else f" ({type(error).__name__})"
        return " ".join(line.splitlines())


class _NotFileOnly(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not any(record.name == name or record.name.startswith(name + ".") for name in FILE_ONLY_LOGGERS)


def file_handler(folder: Path) -> logging.handlers.RotatingFileHandler:
    folder.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        folder / LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(FORMAT))
    return handler


def console_handler(stream=None) -> logging.StreamHandler:
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(ConsoleFormatter(CONSOLE_FORMAT, CONSOLE_DATE_FORMAT))
    handler.addFilter(_NotFileOnly())
    return handler


def configure(folder: Path | None = None, *, console=None, level: int = logging.INFO) -> Path:
    """Logs to ``folder`` (``data/logs`` by default) and to the console; returns the log file."""
    folder = folder or log_dir()
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _MARK, False):
            root.removeHandler(handler)
            handler.close()
    handlers: list[logging.Handler] = [console_handler(console)]
    try:
        handlers.append(file_handler(folder))
    except OSError as e:  # read-only or full disk: the console only
        print(f"Journal impossible dans {folder} : {e}", file=sys.stderr)
    for handler in handlers:
        setattr(handler, _MARK, True)
        root.addHandler(handler)
    root.setLevel(level)
    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.captureWarnings(True)
    _catch_uncaught()
    return folder / LOG_FILE


def _catch_uncaught() -> None:
    """Uncaught errors (main thread, browser thread) are written to the log file too."""

    def excepthook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logging.getLogger("prixmalin").critical("Uncaught error", exc_info=(exc_type, exc, tb))

    def thread_excepthook(args):
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread else "?"
        logging.getLogger("prixmalin").error(
            "Uncaught error in thread %s", name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback)
        )

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook


def versions_line(channel: str | None = None) -> str:
    """« PrixMalin 2.1.0, Python 3.13.1, Playwright 1.56.0, Windows-11-…, browser: auto »."""

    def version_of(package: str) -> str:
        try:
            return metadata.version(package)
        except metadata.PackageNotFoundError:
            return "missing"

    browser = channel or config.BROWSER_CHANNEL or "auto (known at the first search)"
    return (
        f"PrixMalin {__version__}, Python {platform.python_version()}, Playwright {version_of('playwright')}, "
        f"{platform.platform()}, browser: {browser}"
    )


def log_versions(channel: str | None = None) -> None:
    # The channel actually started is logged by the browser: « Browser started (chrome, headless) »
    logger.info("%s", versions_line(channel))
