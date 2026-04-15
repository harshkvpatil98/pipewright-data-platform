from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api_gateway.dependencies import get_db
from service_datasets.contracts import total_datasets
from service_projects.contracts import total_projects
from service_sources.contracts import total_sources

router = APIRouter(prefix="/orchestration", tags=["orchestration"])
DbSession = Annotated[Session, Depends(get_db)]


# This endpoint demonstrates how future ETL orchestration can aggregate state across service modules.
@router.post("/sample-run", response_model=dict[str, object])
def sample_run(db: DbSession) -> dict[str, object]:
    return {
        "status": "queued",
        "run_type": "sample-platform-check",
        "timestamp": datetime.now(UTC).isoformat(),
        "services": {
            "projects": {"count": total_projects(db)},
            "sources": {"count": total_sources(db)},
            "datasets": {"count": total_datasets(db)},
        },
    }
