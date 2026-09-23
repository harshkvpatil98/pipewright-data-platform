"""`AS OF` SQL over a stored dataset: query the data as it was.

Settled decision #8 draws the line: temporal SQL applies to *materialised
Pipewright datasets*, never to SQL the workbench sends to a customer database.
So this does not rewrite anybody's SQL. It resolves one recorded version -- by
number, or the newest one published at or before an instant -- loads that
version's artifact into a private in-memory SQLite database as a table named
`dataset`, and runs the caller's SELECT there under the workbench's read-only
policy. Nothing is written; nothing survives the request.

Publication ordering (§8): "as of T" means the version with the greatest
`created_at` not after T; two versions published in the same instant tie-break
on the higher version number, which is also the later publication. An instant
before the first version resolves to nothing, and says so, rather than to the
current head. Values come back exactly as the workbench renders them
(`execute._json_safe`): decimals as text, timestamps in ISO 8601, nulls as
null, nested values as JSON. A pruned version answers with why.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from service_datasets.models import Dataset, DatasetVersion
from service_datasets.service import get_dataset_model_for_project
from service_datasets.version_lifecycle import require_readable
from service_projects.contracts import ensure_owned_project
from service_workbench.execute import run_script
from service_workbench.safety import SessionPolicy
from service_workbench.schemas import TemporalQueryRequest, TemporalQueryResponse
from service_workbench.sql_text import StatementKind, parse
from shared_python.errors import BadRequestError, NotFoundError

TABLE_NAME = "dataset"
#: The most rows one temporal query returns. Declared in the response so a
#: caller can tell a small result from a capped one (§8).
MAX_ROWS = 1_000
TIMEOUT_SECONDS = 15


def resolve_version(
    db: Session,
    dataset: Dataset,
    *,
    version_number: int | None,
    as_of: datetime | None,
) -> DatasetVersion:
    """Which recorded version a request means. Number wins over instant; with
    neither, the head."""
    if version_number is not None:
        version = db.scalar(
            select(DatasetVersion).where(
                DatasetVersion.dataset_id == dataset.id,
                DatasetVersion.version_number == version_number,
            )
        )
        if version is None:
            raise NotFoundError(f"This dataset has no version {version_number}.")
        return version

    query = select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)
    if as_of is not None:
        moment = as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=UTC)
        query = query.where(DatasetVersion.created_at <= moment)
    version = db.scalar(
        query.order_by(DatasetVersion.created_at.desc(), DatasetVersion.version_number.desc()).limit(1)
    )
    if version is None:
        if as_of is not None:
            first = db.scalar(
                select(DatasetVersion)
                .where(DatasetVersion.dataset_id == dataset.id)
                .order_by(DatasetVersion.version_number)
                .limit(1)
            )
            if first is None:
                raise NotFoundError("This dataset has no recorded versions to query.")
            raise NotFoundError(
                f"No version of this dataset existed at {moment.isoformat()}; the earliest, "
                f"version 1, was published {first.created_at.isoformat()}."
            )
        raise NotFoundError("This dataset has no recorded versions to query.")
    return version


def temporal_query(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: TemporalQueryRequest,
    user: Any,
    storage: Any,
) -> TemporalQueryResponse:
    ensure_owned_project(db, project_id, user.id)
    dataset = get_dataset_model_for_project(db, project_id, dataset_id)
    version = resolve_version(
        db, dataset, version_number=payload.version_number, as_of=payload.as_of
    )
    require_readable(version)

    script = parse(payload.sql)
    if len(script.statements) != 1:
        raise BadRequestError(
            "Run one statement at a time against a version: "
            f"{len(script.statements)} were given."
        )
    [only] = script.statements
    if only.kind is not StatementKind.READ:
        # There is no write mode here to turn on: a version is a snapshot, and
        # the copy this query runs against is thrown away with the request.
        raise BadRequestError(
            "A version is a read-only snapshot; only a SELECT can run against it "
            f"(statement 1 is a {only.kind.value}). To change live data, use the "
            "table editor, which stages a reviewed change set."
        )

    frame = _load_frame(storage, version, fallback_type=dataset.file_type)
    engine = create_engine("sqlite://")
    try:
        _sqlite_safe(frame).to_sql(TABLE_NAME, engine, index=False, if_exists="replace")
        policy = SessionPolicy(
            row_limit=max(1, min(payload.row_limit, MAX_ROWS)), timeout_seconds=TIMEOUT_SECONDS
        )
        result = run_script(engine, payload.sql, policy=policy, parameters=payload.parameters)
    finally:
        engine.dispose()

    [statement] = result.statements
    if statement.error:
        raise BadRequestError(statement.error)

    return TemporalQueryResponse(
        dataset_id=dataset.id,
        version_number=version.version_number,
        version_published_at=version.created_at,
        requested_as_of=payload.as_of,
        table_name=TABLE_NAME,
        columns=list(statement.columns),
        rows=list(statement.rows),
        row_count=int(statement.row_count),
        truncated=bool(statement.truncated),
        row_limit=policy.row_limit,
        duration_ms=result.duration_ms,
        warnings=list(result.warnings),
    )


def _load_frame(storage: Any, version: DatasetVersion, *, fallback_type: str | None) -> pd.DataFrame:
    from service_ingestion.parsers import parse_tabular_file

    try:
        stored = storage.read_bytes(version.file_path)
    except Exception as exc:  # noqa: BLE001 - one honest answer for every read failure
        raise BadRequestError(
            f"Version {version.version_number}'s stored artifact could not be read."
        ) from exc
    return parse_tabular_file(
        file_bytes=stored, file_type=version.file_type or fallback_type or "csv"
    ).dataframe


def _sqlite_safe(frame: pd.DataFrame) -> pd.DataFrame:
    """SQLite holds scalars. Nested values (from the nested-data tools) go in as
    JSON text so a query can still see them, rather than failing the load."""
    out = frame.copy()
    for column in out.columns:
        if out[column].dtype == object and out[column].map(
            lambda v: isinstance(v, (list, dict, tuple))
        ).any():
            out[column] = out[column].map(
                lambda v: json.dumps(v, default=str) if isinstance(v, (list, dict, tuple)) else v
            )
    return out
