from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from api_gateway.config import settings
from api_gateway.dependencies import SessionLocal, engine, get_db, get_storage_backend
from api_gateway.router import build_api_router
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


def create_application() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Gateway for the Pipewright modular services.",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        lifespan=lifespan,
    )
    application.add_middleware(CORSMiddleware, allow_origins=settings.backend_cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    application.add_middleware(GZipMiddleware, minimum_size=settings.gzip_minimum_size_bytes)
    application.add_middleware(CorrelationIdMiddleware, logger=logger)
    # Audit every mutating request, on its own session: the handler's
    # transaction may have rolled back, and the attempt still happened.
    application.add_middleware(AuditMiddleware, session_factory=SessionLocal)
    register_exception_handlers(application)
    application.include_router(build_internal_router(get_db, get_storage_backend, settings))
    application.include_router(
        build_workflow_internal_router(get_db, get_storage_backend, settings)
    )
    # Prometheus does not carry a bearer token, so the scrape endpoint sits
    # outside the authenticated API. It exposes counts, never rows.
    application.include_router(build_metrics_router(get_db))
    application.include_router(build_api_router(settings), prefix=settings.api_v1_prefix)
    return application


app = create_application()
