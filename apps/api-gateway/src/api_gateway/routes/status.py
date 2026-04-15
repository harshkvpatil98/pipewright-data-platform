from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api_gateway.config import settings
from api_gateway.dependencies import get_db
from api_gateway.status import collect_service_statuses, platform_status
from shared_python.status import PlatformStatus, ServiceStatus

router = APIRouter(prefix="/status", tags=["status"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=PlatformStatus)
def get_platform_status(db: DbSession) -> PlatformStatus:
    return platform_status(
        db=db,
        service_name=settings.app_name,
        environment=settings.app_env,
        version=settings.app_version,
        scheduler_internal_api_configured=bool(settings.scheduler_internal_token),
        scheduler_runtime_id_configured=bool(
            (settings.scheduler_runtime_id or "").strip()
        ),
    )


@router.get("/services", response_model=list[ServiceStatus])
def get_service_statuses(db: DbSession) -> list[ServiceStatus]:
    return collect_service_statuses(db)
