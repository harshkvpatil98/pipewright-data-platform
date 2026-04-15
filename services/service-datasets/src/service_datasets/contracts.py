from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from service_datasets.models import Dataset


def project_dataset_count_expression(project_model) -> Select:
    return (
        select(func.count(Dataset.id))
        .where(Dataset.project_id == project_model.id)
        .correlate(project_model)
        .scalar_subquery()
    )


def total_datasets(db: Session) -> int:
    return db.scalar(select(func.count(Dataset.id))) or 0
