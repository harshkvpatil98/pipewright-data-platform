from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_pipeline_runs.models import PipelineRun
from shared_python.errors import NotFoundError


def get_pipeline_run_for_project(db: Session, project_id: uuid.UUID, run_id: uuid.UUID) -> PipelineRun:
    pipeline_run = db.scalar(
        select(PipelineRun).where(PipelineRun.id == run_id, PipelineRun.project_id == project_id)
    )
    if pipeline_run is None:
        raise NotFoundError("Pipeline run not found.")
    return pipeline_run


def total_pipeline_runs(db: Session) -> int:
    return db.scalar(select(func.count(PipelineRun.id))) or 0
