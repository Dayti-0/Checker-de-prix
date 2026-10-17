"""Logs of the app (area of P7). In P0: the console, as before."""

import logging

FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def configure() -> None:
    """Called by ``python -m backend.main`` before starting the server."""
    logging.basicConfig(level=logging.INFO, format=FORMAT)
