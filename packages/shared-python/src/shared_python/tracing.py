from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")


def get_correlation_id() -> str:
    return _correlation_id.get()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, logger: logging.Logger, header_name: str = "X-Request-ID"):
        super().__init__(app)
        self.logger = logger
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        correlation_id = request.headers.get(self.header_name) or str(uuid.uuid4())
        token = _correlation_id.set(correlation_id)
        started_at = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            self.logger.exception(
                "request_failed method=%s path=%s", request.method, request.url.path
            )
            _correlation_id.reset(token)
            raise

        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        response.headers[self.header_name] = correlation_id
        self.logger.info(
            "request_complete method=%s path=%s status_code=%s duration_ms=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        _correlation_id.reset(token)
        return response
