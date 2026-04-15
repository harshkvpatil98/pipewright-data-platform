from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from service_auth.schemas import UserRead
from service_destinations.models import DestinationConfig
from service_destinations.publish_schemas import DatasetPublishPostgresRequest
from service_destinations.publish_service import publish_dataset_to_postgres
from service_datasets.models import Dataset
from shared_python.errors import BadRequestError, NotFoundError


def _user() -> UserRead:
    return UserRead(
        id=uuid.uuid4(),
        username="u",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@patch("service_destinations.publish_service.ensure_owned_project", side_effect=NotFoundError("missing"))
def test_publish_requires_project(_e) -> None:
    db = MagicMock()
    with pytest.raises(NotFoundError):
        publish_dataset_to_postgres(
            db,
            project_id=uuid.uuid4(),
            dataset_id=uuid.uuid4(),
            payload=DatasetPublishPostgresRequest(
                destination_id=uuid.uuid4(),
                table_name="ok_table",
                write_mode="replace",
            ),
            current_user=_user(),
            storage_backend=object(),
        )


@patch("service_destinations.publish_service.write_dataframe_to_postgres")
@patch("service_destinations.publish_service.mark_pipeline_run_succeeded")
@patch("service_destinations.publish_service.mark_pipeline_run_running")
@patch("service_destinations.publish_service.create_pipeline_run")
@patch("service_destinations.publish_service.get_dataset_model_for_project")
@patch("service_destinations.publish_service.get_destination_model")
@patch("service_destinations.publish_service.ensure_owned_project")
def test_publish_success(
    ensure_owned,
    get_dest,
    get_ds,
    create_run,
    mark_run,
    mark_ok,
    write_pg,
) -> None:
    ensure_owned.return_value = None
    pid = uuid.uuid4()
    did = uuid.uuid4()
    dest_id = uuid.uuid4()
    dest = DestinationConfig(
        id=dest_id,
        project_id=pid,
        name="pg",
        destination_type="postgres",
        status="active",
        config_json={
            "host": "h",
            "port": 5432,
            "database": "d",
            "username": "u",
            "password": "p",
        },
        created_by_user_id=None,
    )
    dest.created_at = datetime.now(UTC)
    dest.updated_at = datetime.now(UTC)
    get_dest.return_value = dest

    ds = Dataset(
        id=did,
        project_id=pid,
        name="ds",
        original_filename="f.csv",
        file_path="x",
        file_type="csv",
        file_size_bytes=10,
        is_derived=False,
        status="ready",
        ingestion_status="succeeded",
    )
    ds.created_at = datetime.now(UTC)
    ds.updated_at = datetime.now(UTC)
    get_ds.return_value = ds

    run = MagicMock()
    run.id = uuid.uuid4()
    create_run.return_value = run

    mark_ok.return_value = MagicMock(
        id=run.id,
        project_id=pid,
        triggered_by_user_id=_user().id,
        pipeline_id=None,
        triggered_by_username=None,
        run_type="dataset_publish_postgres",
        status="succeeded",
        started_at=None,
        completed_at=None,
        summary_json={},
        logs_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    write_pg.return_value = 3

    db = MagicMock()

    with patch("service_destinations.publish_service._load_dataframe", return_value=pd.DataFrame({"a": [1, 2, 3]})):
        out = publish_dataset_to_postgres(
            db,
            project_id=pid,
            dataset_id=did,
            payload=DatasetPublishPostgresRequest(
                destination_id=dest_id,
                table_name="t1",
                write_mode="replace",
            ),
            current_user=_user(),
            storage_backend=object(),
        )

    assert out.success is True
    assert out.row_count_written == 3
    write_pg.assert_called_once()


@patch("service_destinations.publish_service.get_destination_model")
@patch("service_destinations.publish_service.ensure_owned_project")
def test_publish_rejects_non_postgres(ensure_owned, get_dest) -> None:
    ensure_owned.return_value = None
    dest = MagicMock()
    dest.destination_type = "s3"
    dest.status = "active"
    get_dest.return_value = dest
    db = MagicMock()
    with pytest.raises(BadRequestError, match="PostgreSQL"):
        publish_dataset_to_postgres(
            db,
            project_id=uuid.uuid4(),
            dataset_id=uuid.uuid4(),
            payload=DatasetPublishPostgresRequest(
                destination_id=uuid.uuid4(),
                table_name="t",
                write_mode="append",
            ),
            current_user=_user(),
            storage_backend=object(),
        )


def test_validate_table_name_rejects_invalid() -> None:
    from service_destinations.postgres_writer import validate_table_identifier

    with pytest.raises(BadRequestError):
        validate_table_identifier("bad-name!")
