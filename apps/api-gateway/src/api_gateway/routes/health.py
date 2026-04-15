from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api_gateway.config import settings
from api_gateway.dependencies import get_db
from shared_python.db.health import is_database_ready

router = APIRouter(tags=["health"])
DbSession = Annotated[Session, Depends(get_db)]


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


@router.get("/health/live", response_model=dict[str, str])
def live() -> dict[str, str]:
    return {
        "status": "alive",
        "service": settings.app_name,
        "environment": settings.app_env,
        "version": settings.app_version,
        "timestamp": _timestamp(),
    }


@router.get("/health/ready", response_model=dict[str, str])
def ready(db: DbSession) -> dict[str, str]:
    if not is_database_ready(db):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable.")
    return {
        "status": "ready",
        "service": settings.app_name,
        "environment": settings.app_env,
        "version": settings.app_version,
        "timestamp": _timestamp(),
    }
