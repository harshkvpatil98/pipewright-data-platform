from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request


class ApplicationError(Exception):
    status_code = 400

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


# Registering shared exception handling once in the gateway keeps service packages simple.
def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def handle_application_error(_: Request, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
