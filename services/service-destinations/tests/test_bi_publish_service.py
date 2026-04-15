from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from service_auth.schemas import UserRead
from service_destinations.bi_publish_service import publish_dataset_to_power_bi
from service_destinations.connectors.power_bi_publish import (
    PowerBiPublishOutcome,
    validate_power_bi_target_dataset_name,
)
from service_destinations.models import DestinationConfig
from service_destinations.publish_schemas import DatasetPublishPowerBiRequest
from service_datasets.models import Dataset
from shared_python.errors import BadRequestError


def _user() -> UserRead:
    return UserRead(
        id=uuid.uuid4(),
        username="u",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _pbi_conn() -> DestinationConfig:
    row = DestinationConfig(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="PBI",
        destination_type="power_bi",
        status="active",
        config_json={"tenant_id": "t", "client_id": "c", "client_secret": "s"},
        created_by_user_id=_user().id,
    )
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    return row


def _dataset(pid: uuid.UUID) -> Dataset:
    d = Dataset(
        id=uuid.uuid4(),
        project_id=pid,
        source_id=None,
        uploaded_by_user_id=None,
        pipeline_run_id=None,
        parent_dataset_id=None,
        created_from_pipeline_id=None,
        name="ds",
        original_filename="f.csv",
        file_name="f.csv",
        file_type="csv",
        file_size_bytes=100,
        is_derived=False,
        status="ready",
        ingestion_status="succeeded",
        row_count=2,
        column_count=1,
        schema_json={"columns": [{"name": "a", "inferred_type": "string"}]},
        profile_json=None,
        preview_json=None,
        ingestion_error=None,
        last_profiled_at=None,
        file_path="path/to.csv",
    )
    d.created_at = datetime.now(UTC)
    d.updated_at = datetime.now(UTC)
    return d


@patch("service_destinations.bi_publish_service.publish_dataframe_power_bi_push")
@patch("service_destinations.bi_publish_service._load_dataframe")
@patch("service_destinations.bi_publish_service.get_dataset_model_for_project")
@patch("service_destinations.bi_publish_service.get_bi_connection_model")
@patch("service_destinations.bi_publish_service.ensure_owned_project")
@patch("service_destinations.bi_publish_service.mark_pipeline_run_succeeded")
@patch("service_destinations.bi_publish_service.mark_pipeline_run_running")
@patch("service_destinations.bi_publish_service.create_pipeline_run")
def test_publish_power_bi_success(
    create_run,
    mark_running,
    mark_ok,
    ensure_owned,
    get_conn,
    get_ds,
    load_df,
    push_fn,
) -> None:
    ensure_owned.return_value = None
    conn = _pbi_conn()
    get_conn.return_value = conn
    ds = _dataset(conn.project_id)
    get_ds.return_value = ds
    load_df.return_value = pd.DataFrame({"a": [1, 2]})

    run = MagicMock()
    run.id = uuid.uuid4()
    create_run.return_value = run

    def running_side_effect(db, *, run, logs_json=None):
        return run

    mark_running.side_effect = running_side_effect

    mark_ok.return_value = MagicMock(
        id=uuid.uuid4(),
        project_id=conn.project_id,
        triggered_by_user_id=_user().id,
        pipeline_id=None,
        triggered_by_username=None,
        run_type="dataset_publish_power_bi",
        status="succeeded",
        started_at=None,
        completed_at=None,
        summary_json={},
        logs_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    push_fn.return_value = PowerBiPublishOutcome(
        dataset_id="did",
        workspace_id=str(uuid.uuid4()),
        target_dataset_name="MySet",
        target_table_name="PublishedData",
        rows_published=2,
        publish_mode="created",
    )

    payload = DatasetPublishPowerBiRequest(
        connection_id=conn.id,
        workspace_id=uuid.uuid4(),
        target_dataset_name="MySet",
        write_mode="replace",
    )
    out = publish_dataset_to_power_bi(
        MagicMock(),
        project_id=conn.project_id,
        dataset_id=ds.id,
        payload=payload,
        current_user=_user(),
        storage_backend=object(),
    )
    assert out.success is True
    assert out.row_count_published == 2
    push_fn.assert_called_once()


@patch("service_destinations.bi_publish_service.publish_dataframe_power_bi_push")
@patch("service_destinations.bi_publish_service._load_dataframe")
@patch("service_destinations.bi_publish_service.get_dataset_model_for_project")
@patch("service_destinations.bi_publish_service.get_bi_connection_model")
@patch("service_destinations.bi_publish_service.ensure_owned_project")
@patch("service_destinations.bi_publish_service.mark_pipeline_run_failed")
@patch("service_destinations.bi_publish_service.mark_pipeline_run_running")
@patch("service_destinations.bi_publish_service.create_pipeline_run")
def test_publish_power_bi_push_failure(
    create_run,
    mark_running,
    mark_fail,
    ensure_owned,
    get_conn,
    get_ds,
    load_df,
    push_fn,
) -> None:
    ensure_owned.return_value = None
    conn = _pbi_conn()
    get_conn.return_value = conn
    ds = _dataset(conn.project_id)
    get_ds.return_value = ds
    load_df.return_value = pd.DataFrame({"a": [1]})
    push_fn.side_effect = BadRequestError("Power BI API rejected the publish request.")

    run = MagicMock()
    run.id = uuid.uuid4()
    create_run.return_value = run
    mark_running.side_effect = lambda db, *, run, logs_json=None: run
    mark_fail.return_value = MagicMock(
        id=uuid.uuid4(),
        project_id=conn.project_id,
        triggered_by_user_id=_user().id,
        pipeline_id=None,
        triggered_by_username=None,
        run_type="dataset_publish_power_bi",
        status="failed",
        started_at=None,
        completed_at=None,
        summary_json={},
        logs_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    payload = DatasetPublishPowerBiRequest(
        connection_id=conn.id,
        workspace_id=uuid.uuid4(),
        target_dataset_name="MySet",
        write_mode="append",
    )
    out = publish_dataset_to_power_bi(
        MagicMock(),
        project_id=conn.project_id,
        dataset_id=ds.id,
        payload=payload,
        current_user=_user(),
        storage_backend=object(),
    )
    assert out.success is False
    assert "Power BI API rejected" in out.message


@patch("service_destinations.bi_publish_service.get_bi_connection_model")
@patch("service_destinations.bi_publish_service.ensure_owned_project")
def test_publish_rejects_non_power_bi(mock_ensure_owned, mock_get_conn) -> None:
    mock_ensure_owned.return_value = None
    conn = _pbi_conn()
    conn.destination_type = "tableau"
    mock_get_conn.return_value = conn
    payload = DatasetPublishPowerBiRequest(
        connection_id=conn.id,
        workspace_id=uuid.uuid4(),
        target_dataset_name="X",
        write_mode="replace",
    )
    with pytest.raises(BadRequestError, match="Power BI"):
        publish_dataset_to_power_bi(
            MagicMock(),
            project_id=conn.project_id,
            dataset_id=uuid.uuid4(),
            payload=payload,
            current_user=_user(),
            storage_backend=object(),
        )


def test_validate_target_dataset_name() -> None:
    assert validate_power_bi_target_dataset_name("  My DS  ") == "My DS"
    with pytest.raises(BadRequestError):
        validate_power_bi_target_dataset_name("")
