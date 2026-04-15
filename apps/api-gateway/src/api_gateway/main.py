from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api_gateway.config import settings
from api_gateway.dependencies import get_db, get_storage_backend
from api_gateway.router import build_api_router
from service_schedules.internal_router import build_internal_router
from shared_python.errors import register_exception_handlers
from shared_python.logging import configure_logging, get_logger
from shared_python.tracing import CorrelationIdMiddleware

configure_logging(service_name="api-gateway", level=settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("gateway_startup environment=%s version=%s", settings.app_env, settings.app_version)
    yield
    logger.info("gateway_shutdown")


def create_application() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Gateway for the Intelligent Data Platform modular services.",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        lifespan=lifespan,
    )
    application.add_middleware(CORSMiddleware, allow_origins=settings.backend_cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    application.add_middleware(CorrelationIdMiddleware, logger=logger)
    register_exception_handlers(application)
    application.include_router(build_internal_router(get_db, get_storage_backend, settings))
    application.include_router(build_api_router(settings), prefix=settings.api_v1_prefix)
    return application


app = create_application()
