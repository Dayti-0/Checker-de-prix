"""B83: the log file of PrixMalin (rotation, tracebacks) and the one-line console."""

import io
import logging
import logging.handlers
import sys
import threading

import pytest

from backend import logging_setup


@pytest.fixture
def configured(tmp_path):
    root = logging.getLogger()
    saved = (list(root.handlers), root.level)
    hooks = (sys.excepthook, threading.excepthook)
    console = io.StringIO()
    path = logging_setup.configure(tmp_path / "logs", console=console)
    yield path, console
    for handler in list(root.handlers):
        if getattr(handler, logging_setup._MARK, False):
            root.removeHandler(handler)
            handler.close()
    root.handlers[:] = saved[0]
    root.setLevel(saved[1])
    sys.excepthook, threading.excepthook = hooks
    logging.captureWarnings(False)


def flush():
    for handler in logging.getLogger().handlers:
        handler.flush()


def test_the_log_file_is_created_with_a_rotation(configured):
    path, _ = configured
    assert path.name == "prixmalin.log" and path.parent.name == "logs"
    assert path.exists()
    handlers = [h for h in logging.getLogger().handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(handlers) == 1
    assert (handlers[0].maxBytes, handlers[0].backupCount) == (1_000_000, 5)
    assert handlers[0].encoding == "utf-8"


def test_the_console_shows_one_line_and_the_file_the_traceback(configured):
    path, console = configured
    try:
        raise ValueError("Recherche impossible\ndeuxième ligne")
    except ValueError:
        logging.getLogger("prixmalin.test").exception("Échec de la recherche « œufs »")
    flush()
    text = console.getvalue()
    assert "Traceback" not in text
    assert text.count("\n") == 1
    assert "Échec de la recherche « œufs » (ValueError: Recherche impossible)" in text
    content = path.read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in content and "deuxième ligne" in content
    assert "prixmalin.test" in content


def test_configure_twice_keeps_one_pair_of_handlers(configured, tmp_path):
    logging_setup.configure(tmp_path / "logs", console=io.StringIO())
    ours = [h for h in logging.getLogger().handlers if getattr(h, logging_setup._MARK, False)]
    assert len(ours) == 2


def test_uvicorn_logs_reach_the_file_and_access_lines_stay_out_of_the_console(configured):
    path, console = configured
    logging.getLogger("uvicorn.error").info("Started server process")
    logging.getLogger("uvicorn.access").info('127.0.0.1:5000 - "GET /api/version HTTP/1.1" 200')
    flush()
    content = path.read_text(encoding="utf-8")
    assert "Started server process" in content and "GET /api/version" in content
    assert "Started server process" in console.getvalue()
    assert "GET /api/version" not in console.getvalue()


def test_the_versions_line(configured):
    path, _ = configured
    line = logging_setup.versions_line("msedge")
    assert line.startswith("PrixMalin ") and "Python " in line and "Playwright " in line
    assert line.endswith("browser: msedge")
    logging_setup.log_versions()
    flush()
    assert "PrixMalin " in path.read_text(encoding="utf-8")
