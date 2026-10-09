"""Only one PrixMalin at a time on the PC (area of P7). No effect in P0."""


def ensure_single_instance() -> None:
    """Called by ``python -m backend.main`` before starting the server."""
