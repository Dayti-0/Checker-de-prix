"""Errors shown to the user, and the helper that shortens technical messages."""


class AppError(Exception):
    """An error whose French ``message`` can be shown as is (HTTP ``status_code``).

    Raised by the services; ``backend/api/errors.py`` turns it into a JSON
    response ``{"detail": message, "code": code}``.
    """

    status_code = 400
    code = "error"

    def __init__(self, message: str, status_code: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


def short_error(error: BaseException, limit: int = 200) -> str:
    """First line of an exception message, at most ``limit`` characters."""
    lines = str(error).strip().splitlines()
    return (lines[0] if lines else type(error).__name__)[:limit]
