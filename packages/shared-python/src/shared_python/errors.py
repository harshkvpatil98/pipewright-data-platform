from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request


class ApplicationError(Exception):
    status_code = 400
    #: Set by a recipe's step loop: which step (from 0) the refusal came from,
    #: so the Studio shows it under that step rather than the one open (E1).
    step_index: int | None = None

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class NotFoundError(ApplicationError):
    status_code = 404


class ConflictError(ApplicationError):
    status_code = 409


class UnauthorizedError(ApplicationError):
    status_code = 401


class ForbiddenError(ApplicationError):
    status_code = 403


class BadRequestError(ApplicationError):
    status_code = 400


class InternalServerError(ApplicationError):
    status_code = 500


class MisconfiguredEnvironmentError(ApplicationError):
    """Raised when required platform secrets (e.g. encryption key) are missing or invalid."""

    status_code = 503


class TooManyRequestsError(ApplicationError):
    """A rate limit was reached; `retry_after` says how many seconds until it resets."""

    status_code = 429

    def __init__(self, detail: str, *, retry_after: int):
        super().__init__(detail)
        self.retry_after = max(1, int(retry_after))


# Registering shared exception handling once in the gateway keeps service packages simple.
def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def handle_application_error(_: Request, exc: ApplicationError) -> JSONResponse:
        headers = {"Retry-After": str(exc.retry_after)} if isinstance(exc, TooManyRequestsError) else None
        content: dict = {"detail": exc.detail}
        if exc.step_index is not None:
            content["step_index"] = exc.step_index
        return JSONResponse(status_code=exc.status_code, content=content, headers=headers)
