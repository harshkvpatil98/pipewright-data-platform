from fastapi import APIRouter

from api_gateway.dependencies import get_db, get_storage_backend
from api_gateway.routes import health, status
from service_auth import build_router as build_auth_router
from service_auth.dependencies import build_current_user_dependency
from service_comparisons import build_router as build_comparisons_router
from service_datasets import build_router as build_datasets_router
from service_destinations import build_bi_router, build_router as build_destinations_router
from service_ingestion.router import build_router as build_ingestion_router
from service_pipeline_runs import build_router as build_pipeline_runs_router
from service_projects import build_router as build_projects_router
from service_schedules import build_router as build_schedules_router
from service_sources import build_router as build_sources_router
from service_transformations import build_router as build_transformations_router
from service_notifications import build_router as build_notifications_router


def build_api_router(settings) -> APIRouter:
    api_router = APIRouter()
    current_user = build_current_user_dependency(get_db, settings)
    api_router.include_router(health.router)
    api_router.include_router(status.router)
    api_router.include_router(build_auth_router(get_db, settings))
    api_router.include_router(build_projects_router(get_db, current_user))
    api_router.include_router(build_sources_router(get_db, current_user))
    api_router.include_router(build_destinations_router(get_db, current_user, get_storage_backend))
    api_router.include_router(build_bi_router(get_db, current_user))
    api_router.include_router(build_datasets_router(get_db, current_user))
    api_router.include_router(build_comparisons_router(get_db, current_user, get_storage_backend))
    api_router.include_router(build_ingestion_router(get_db, current_user, get_storage_backend, settings))
    api_router.include_router(build_pipeline_runs_router(get_db, current_user))
    api_router.include_router(build_transformations_router(get_db, current_user, get_storage_backend, settings))
    api_router.include_router(build_schedules_router(get_db, current_user, get_storage_backend, settings))
    api_router.include_router(build_notifications_router(get_db, current_user))
    return api_router
