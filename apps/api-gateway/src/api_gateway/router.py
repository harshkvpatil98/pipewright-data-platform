from fastapi import APIRouter, Depends

from api_gateway.dependencies import get_db, get_storage_backend
from api_gateway.routes import health, status
from api_gateway.wiring import install_resolvers
from service_auth import build_router as build_auth_router
from service_access import build_project_guard, build_router as build_access_router
from service_auth.dependencies import build_current_user_dependency
from service_comparisons import build_router as build_comparisons_router
from service_connectors import build_router as build_connectors_router
from api_gateway.demo import build_demo_router
from api_gateway.operator_views import build_operator_router
from api_gateway.sso_router import build_router as build_sso_router
from service_datasets import build_router as build_datasets_router
from service_destinations import build_bi_router, build_router as build_destinations_router
from service_enterprise import build_router as build_enterprise_router
from service_extraction import build_router as build_extraction_router
from service_governance import build_router as build_governance_router
from service_ingestion.router import build_router as build_ingestion_router
from service_intelligence import build_router as build_intelligence_router
from service_lineage import build_router as build_lineage_router
from service_observability import build_router as build_observability_router
from service_pipeline_runs import build_router as build_pipeline_runs_router
from service_projects import build_router as build_projects_router
from service_quality import build_router as build_quality_router
from service_reporting import build_public_router as build_public_reporting_router
from service_reporting import build_router as build_reporting_router
from service_schedules import build_router as build_schedules_router
from service_sources import build_router as build_sources_router
from service_transformations import build_router as build_transformations_router
from service_workflows import build_router as build_workflows_router
from service_workbench import build_router as build_workbench_router
from service_writeback import build_router as build_writeback_router
from service_notifications import build_router as build_notifications_router


def build_api_router(settings) -> APIRouter:
    # Every project-scoped request passes the access guard before its handler
    # runs. Mounting it here rather than per-service is what makes it
    # impossible for a new route to be added without authorisation.
    install_resolvers()
    api_router = APIRouter(dependencies=[Depends(build_project_guard(get_db, settings))])
    current_user = build_current_user_dependency(get_db, settings)
    api_router.include_router(health.router)
    api_router.include_router(status.router)
    api_router.include_router(build_auth_router(get_db, settings))
    api_router.include_router(build_sso_router(get_db, settings))
    api_router.include_router(build_projects_router(get_db, current_user))
    api_router.include_router(build_operator_router(get_db, current_user))
    api_router.include_router(build_demo_router(get_db, current_user, get_storage_backend, settings))
    api_router.include_router(build_access_router(get_db, current_user))
    api_router.include_router(
        build_enterprise_router(get_db, current_user, get_storage_backend)
    )
    api_router.include_router(build_governance_router(get_db, current_user))
    api_router.include_router(build_sources_router(get_db, current_user))
    api_router.include_router(build_connectors_router(get_db, current_user))
    api_router.include_router(build_destinations_router(get_db, current_user, get_storage_backend))
    api_router.include_router(build_bi_router(get_db, current_user))
    api_router.include_router(build_datasets_router(get_db, current_user, get_storage_backend))
    api_router.include_router(build_comparisons_router(get_db, current_user, get_storage_backend))
    api_router.include_router(build_ingestion_router(get_db, current_user, get_storage_backend, settings))
    api_router.include_router(build_extraction_router(get_db, current_user, get_storage_backend, settings))
    api_router.include_router(build_quality_router(get_db, current_user, get_storage_backend, settings))
    api_router.include_router(build_pipeline_runs_router(get_db, current_user))
    api_router.include_router(build_transformations_router(get_db, current_user, get_storage_backend, settings))
    api_router.include_router(build_schedules_router(get_db, current_user, get_storage_backend, settings))
    api_router.include_router(build_workflows_router(get_db, current_user))
    api_router.include_router(build_writeback_router(get_db, current_user))
    api_router.include_router(build_workbench_router(get_db, current_user))
    api_router.include_router(build_lineage_router(get_db, current_user))
    api_router.include_router(
        build_intelligence_router(get_db, current_user, get_storage_backend)
    )
    api_router.include_router(build_observability_router(get_db, current_user))
    api_router.include_router(build_public_reporting_router(get_db, get_storage_backend))
    api_router.include_router(
        build_reporting_router(get_db, current_user, get_storage_backend)
    )
    api_router.include_router(build_notifications_router(get_db, current_user))
    return api_router
