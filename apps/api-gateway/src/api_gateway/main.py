from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from api_gateway.config import settings
from api_gateway.dependencies import SessionLocal, engine, get_db, get_storage_backend
from api_gateway.router import build_api_router
from api_gateway.tracing import install_tracing
from service_enterprise import build_metrics_router
from service_governance import AuditMiddleware
from service_schedules.internal_router import build_internal_router
from service_workflows.internal_router import build_internal_router as build_workflow_internal_router
from shared_python.errors import register_exception_handlers
from shared_python.logging import configure_logging, get_logger
from shared_python.tracing import CorrelationIdMiddleware

configure_logging(service_name="api-gateway", level=settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("gateway_startup environment=%s version=%s", settings.app_env, settings.app_version)
    from api_gateway.first_run import make_first_administrator

    make_first_administrator(SessionLocal)
    yield
    # Release pooled sockets -- both our own and any opened to customer databases
    # by the extraction connectors -- so shutdown does not leak connections.
    try:
        from service_extraction.connectors.sql_database import dispose_cached_engines

        dispose_cached_engines()
    except Exception:  # noqa: BLE001 - shutdown must not raise
        logger.exception("extraction_engine_dispose_failed")
    engine.dispose()
    logger.info("gateway_shutdown")


#: Sent with every answer (A6, W7). The API is never meant to be framed or
#: sniffed as another content type, and its addresses carry ids.
SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
)


class SecurityHeadersMiddleware:
    """Adds `SECURITY_HEADERS` to every HTTP response, leaving any already set."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message.get("headers", [])}
                extra = [(name, value) for name, value in SECURITY_HEADERS if name not in present]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _audit_session(application: FastAPI):
    """A session on the database requests use.

    When a test swaps the database (overriding `get_db`), the audit follows
    it, instead of writing the test's requests into the configured database.
    """
    override = application.dependency_overrides.get(get_db)
    if override is None:
        return SessionLocal()
    return next(override())


def create_application() -> FastAPI:
    # Plugins first (X1): what they add is in the catalogues before any route reads them.
    from api_gateway.plugins import load_enabled

    load_enabled(settings)
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Gateway for the Pipewright modular services.",
        # Under /api, like everything the gateway serves: behind the Compose
        # proxy and the Helm ingress only /api reaches the gateway, so a
        # reference at /docs was the web app's 404 (A9). /docs and /redoc
        # still answer, by redirect, for anyone talking to the gateway directly.
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        lifespan=lifespan,
    )

    @application.get("/docs", include_in_schema=False)
    def _docs_moved() -> RedirectResponse:
        return RedirectResponse("/api/docs", status_code=308)

    @application.get("/redoc", include_in_schema=False)
    def _redoc_moved() -> RedirectResponse:
        return RedirectResponse("/api/redoc", status_code=308)
    application.add_middleware(CORSMiddleware, allow_origins=settings.backend_cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    application.add_middleware(GZipMiddleware, minimum_size=settings.gzip_minimum_size_bytes)
    application.add_middleware(CorrelationIdMiddleware, logger=logger)
    application.add_middleware(SecurityHeadersMiddleware)
    # Audit every mutating request, on its own session: the handler's
    # transaction may have rolled back, and the attempt still happened.
    application.add_middleware(AuditMiddleware, session_factory=lambda: _audit_session(application))
    register_exception_handlers(application)
    application.include_router(build_internal_router(get_db, get_storage_backend, settings))
    application.include_router(
        build_workflow_internal_router(get_db, get_storage_backend, settings)
    )
    # Prometheus does not carry a bearer token, so the scrape endpoint sits
    # outside the authenticated API. It exposes counts, never rows.
    application.include_router(build_metrics_router(get_db))
    application.include_router(build_api_router(settings), prefix=settings.api_v1_prefix)
    install_tracing(application, engine, settings)
    return application


app = create_application()
