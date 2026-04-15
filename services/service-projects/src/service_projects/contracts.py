from __future__ import annotations

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from service_projects.models import Project
from shared_python.errors import NotFoundError


def ensure_project_exists(db: Session, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found.")
    return project


# Returning 404 for non-owned resources avoids leaking which project IDs exist.
def ensure_owned_project(db: Session, project_id: uuid.UUID, owner_user_id: uuid.UUID) -> Project:
    project = db.scalar(
        select(Project).where(Project.id == project_id, Project.owner_user_id == owner_user_id)
    )
    if project is None:
        raise NotFoundError("Project not found.")
    return project


def count_project_sources(db: Session, project_id: uuid.UUID) -> int:
    return (
        db.execute(
            text("SELECT COUNT(*) FROM sources WHERE project_id = :project_id"),
            {"project_id": project_id},
        ).scalar_one()
        or 0
    )


def count_project_datasets(db: Session, project_id: uuid.UUID) -> int:
    return (
        db.execute(
            text("SELECT COUNT(*) FROM datasets WHERE project_id = :project_id"),
            {"project_id": project_id},
        ).scalar_one()
        or 0
    )


def count_project_runs(db: Session, project_id: uuid.UUID) -> int:
    return (
        db.execute(
            text("SELECT COUNT(*) FROM pipeline_runs WHERE project_id = :project_id"),
            {"project_id": project_id},
        ).scalar_one()
        or 0
    )


def total_projects(db: Session) -> int:
    return db.scalar(select(func.count(Project.id))) or 0
