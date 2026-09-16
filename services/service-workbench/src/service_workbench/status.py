from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared_python.status import ServiceStatus

from service_workbench import sandbox
from service_workbench.models import Notebook, QueryRun, SavedQuery


def get_service_status(db: Session) -> ServiceStatus:
    available = sandbox.capabilities()
    return ServiceStatus(
        name="service-workbench",
        status="healthy",
        details={
            "saved_query_count": int(db.scalar(select(func.count(SavedQuery.id))) or 0),
            "notebook_count": int(db.scalar(select(func.count(Notebook.id))) or 0),
            "queries_run": int(db.scalar(select(func.count(QueryRun.id))) or 0),
            # Stated rather than hidden: on a deployment that cannot enforce the
            # limits, Python cells are off and somebody should be able to see why.
            "python_cells": "enabled" if available.usable else "disabled",
            "python_cells_reason": available.reason,
        },
    )
