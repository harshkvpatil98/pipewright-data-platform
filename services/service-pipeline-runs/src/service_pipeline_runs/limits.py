"""How much one project may run at once, and what goes first (D2, O8).

Every project has a limit on runs going at the same time: its own
(`projects.max_runs_at_once`) or the deployment's (`PROJECT_RUNS_AT_ONCE`,
default 4). What counts is what a person would call a run: a recipe run, an
import, a delivery, a workflow run. The recipe runs a workflow starts are
part of that workflow run, so they are not counted again.

- A run a person starts while their project is at its limit is refused,
  with the reason (`admit`).
- Queued work waits: the worker skips projects at their limit
  (`busy_projects`), so one busy project does not hold the rest up, and
  takes the highest priority first (`PRIORITY`): started by a person, then
  scheduled, then backfills.

Who started a run is set around the code that starts it (`started_by`), so
a run's origin is recorded without every caller passing it along.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import Integer, String, Uuid, case, column, func, literal, select, table, union_all
from sqlalchemy.orm import Session

from shared_python.errors import TooManyRequestsError
from shared_python.words import count_of

#: Runs at once per project when neither the project nor the deployment says.
DEFAULT_RUNS_AT_ONCE = 4

ORIGINS = ("person", "schedule", "backfill", "workflow")
#: Lower goes first.
PRIORITY = {"person": 0, "schedule": 1, "workflow": 1, "backfill": 2}

_ORIGIN: ContextVar[str] = ContextVar("pipewright_run_origin", default="person")

# The tables are named rather than imported: workflows depend on this
# package, and this must count their runs.
_PIPELINE_RUNS = table("pipeline_runs", column("project_id", Uuid()), column("status", String()),
                       column("origin", String()))
_WORKFLOW_RUNS = table("workflow_runs", column("project_id", Uuid()), column("status", String()))
_PROJECTS = table("projects", column("id", Uuid()), column("max_runs_at_once", Integer()))


@contextmanager
def started_by(origin: str) -> Iterator[None]:
    """Runs created inside this block were started by `origin`."""
    if origin not in ORIGINS:
        raise ValueError(f"Unknown run origin {origin!r}.")
    token = _ORIGIN.set(origin)
    try:
        yield
    finally:
        _ORIGIN.reset(token)


def current_origin() -> str:
    return _ORIGIN.get()


def default_limit(settings: Any | None = None) -> int:
    """The deployment's limit. `WORKFLOW_MAX_RUNS_PER_PROJECT` is the name it had
    when it limited only workflow runs, and is still read."""
    configured = getattr(settings, "project_runs_at_once", None) if settings is not None else None
    configured = configured or os.getenv("PROJECT_RUNS_AT_ONCE") or os.getenv("WORKFLOW_MAX_RUNS_PER_PROJECT")
    try:
        return max(1, int(configured or DEFAULT_RUNS_AT_ONCE))
    except (TypeError, ValueError):
        return DEFAULT_RUNS_AT_ONCE


def limit_for(db: Session, project_id: uuid.UUID, settings: Any | None = None) -> int:
    own = db.scalar(select(_PROJECTS.c.max_runs_at_once).where(_PROJECTS.c.id == project_id))
    return int(own) if own else default_limit(settings)


def _going():
    """Every run going, one row per run, by project."""
    return union_all(
        select(_PIPELINE_RUNS.c.project_id).where(
            _PIPELINE_RUNS.c.status == "running", _PIPELINE_RUNS.c.origin != "workflow"),
        select(_WORKFLOW_RUNS.c.project_id).where(_WORKFLOW_RUNS.c.status == "running"),
    ).subquery()


def going(db: Session, project_id: uuid.UUID) -> int:
    runs = _going()
    return int(db.scalar(select(func.count()).select_from(runs).where(runs.c.project_id == project_id)) or 0)


def busy_projects(settings: Any | None = None):
    """The projects at their limit, as a subquery for `project_id.not_in(...)`."""
    runs = _going()
    own_limit = (
        select(_PROJECTS.c.max_runs_at_once).where(_PROJECTS.c.id == runs.c.project_id).scalar_subquery()
    )
    return (
        select(runs.c.project_id)
        .group_by(runs.c.project_id)
        .having(func.count() >= func.coalesce(own_limit, literal(default_limit(settings))))
    )


def admit(db: Session, project_id: uuid.UUID, settings: Any | None = None) -> None:
    """Refuse a run a person starts while the project already has its limit going."""
    limit = limit_for(db, project_id, settings)
    now = going(db, project_id)
    if now >= limit:
        raise TooManyRequestsError(
            f"This project already has {count_of(now, 'run')} going, its limit at once. Start this again when one "
            "finishes; an admin can raise the limit in the project's settings.",
            retry_after=30,
        )


def priority_of(origin_column):
    """An ORDER BY expression: a person's runs, then scheduled ones, then backfills."""
    return case(
        (origin_column == "person", 0),
        (origin_column == "backfill", 2),
        else_=1,
    )
