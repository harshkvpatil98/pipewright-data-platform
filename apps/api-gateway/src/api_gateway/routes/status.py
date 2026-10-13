from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api_gateway.config import settings
from api_gateway.dependencies import get_db
from api_gateway.status import ceilings, collect_service_statuses, platform_status, security_snapshot
from shared_python.status import PlatformStatus, ServiceStatus, SupportContact, support_contact

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
        security=security_snapshot(db, settings),
        ceilings=ceilings(settings),
    )


@router.get("/services", response_model=list[ServiceStatus])
def get_service_statuses(db: DbSession) -> list[ServiceStatus]:
    return collect_service_statuses(db)


@router.get("/support", response_model=SupportContact)
def get_support_contact() -> SupportContact:
    """Where to get help, and which version is running. Readable without signing in."""
    return support_contact(settings.support_contact, settings.app_version)
