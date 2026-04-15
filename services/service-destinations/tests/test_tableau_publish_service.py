from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from service_auth.schemas import UserRead
from service_destinations.connectors.tableau_publish import TableauPublishOutcome, validate_tableau_datasource_name
from service_destinations.models import DestinationConfig
from service_destinations.publish_schemas import DatasetPublishTableauRequest
from service_destinations.tableau_publish_service import publish_dataset_to_tableau
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


def _tab_conn() -> DestinationConfig:
    row = DestinationConfig(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="TAB",
        destination_type="tableau",
        status="active",
        config_json={
            "server_url": "https://tableau.example.com",
            "auth_mode": "password",
            "username": "u",
            "password": "p",
        },
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
        schema_json=None,
        profile_json=None,
        preview_json=None,
        ingestion_error=None,
        last_profiled_at=None,
        file_path="path/to.csv",
    )
    d.created_at = datetime.now(UTC)
    d.updated_at = datetime.now(UTC)
    return d


@patch("service_destinations.tableau_publish_service.publish_dataframe_to_tableau_datasource")
@patch("service_destinations.tableau_publish_service._load_dataframe")
@patch("service_destinations.tableau_publish_service.get_dataset_model_for_project")
@patch("service_destinations.tableau_publish_service.get_bi_connection_model")
@patch("service_destinations.tableau_publish_service.ensure_owned_project")
@patch("service_destinations.tableau_publish_service.mark_pipeline_run_succeeded")
@patch("service_destinations.tableau_publish_service.mark_pipeline_run_running")
@patch("service_destinations.tableau_publish_service.create_pipeline_run")
def test_publish_tableau_success(
    create_run,
    mark_running,
    mark_ok,
    ensure_owned,
    get_conn,
    get_ds,
    load_df,
    publish_fn,
) -> None:
    ensure_owned.return_value = None
    conn = _tab_conn()
    get_conn.return_value = conn
    ds = _dataset(conn.project_id)
    get_ds.return_value = ds
    load_df.return_value = pd.DataFrame({"a": [1]})

    run = MagicMock()
    run.id = uuid.uuid4()
    create_run.return_value = run
    mark_running.side_effect = lambda db, *, run, logs_json=None: run
    mark_ok.return_value = MagicMock(
        id=uuid.uuid4(),
        project_id=conn.project_id,
        triggered_by_user_id=_user().id,
        pipeline_id=None,
        triggered_by_username=None,
        run_type="dataset_publish_tableau",
        status="succeeded",
        started_at=None,
        completed_at=None,
        summary_json={},
        logs_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    publish_fn.return_value = TableauPublishOutcome(
        datasource_id="ds-id",
        site_id="site-id",
        tableau_project_id=str(uuid.uuid4()),
        datasource_name="MyDS",
        rows_published=1,
        publish_mode="create_only",
    )

    tid = uuid.uuid4()
    payload = DatasetPublishTableauRequest(
        connection_id=conn.id,
        tableau_project_id=tid,
        datasource_name="MyDS",
        write_mode="create_only",
    )
    out = publish_dataset_to_tableau(
        MagicMock(),
        project_id=conn.project_id,
        dataset_id=ds.id,
        payload=payload,
        current_user=_user(),
        storage_backend=object(),
    )
    assert out.success is True
    assert out.row_count_published == 1
    publish_fn.assert_called_once()


@patch("service_destinations.tableau_publish_service.publish_dataframe_to_tableau_datasource")
@patch("service_destinations.tableau_publish_service._load_dataframe")
@patch("service_destinations.tableau_publish_service.get_dataset_model_for_project")
@patch("service_destinations.tableau_publish_service.get_bi_connection_model")
@patch("service_destinations.tableau_publish_service.ensure_owned_project")
@patch("service_destinations.tableau_publish_service.mark_pipeline_run_failed")
@patch("service_destinations.tableau_publish_service.mark_pipeline_run_running")
@patch("service_destinations.tableau_publish_service.create_pipeline_run")
def test_publish_tableau_failure(
    create_run,
    mark_running,
    mark_fail,
    ensure_owned,
    get_conn,
    get_ds,
    load_df,
    publish_fn,
) -> None:
    ensure_owned.return_value = None
    conn = _tab_conn()
    get_conn.return_value = conn
    ds = _dataset(conn.project_id)
    get_ds.return_value = ds
    load_df.return_value = pd.DataFrame({"a": [1]})
    publish_fn.side_effect = BadRequestError("Tableau Server rejected the datasource publish request.")

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
        run_type="dataset_publish_tableau",
        status="failed",
        started_at=None,
        completed_at=None,
        summary_json={},
        logs_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    tid = uuid.uuid4()
    payload = DatasetPublishTableauRequest(
        connection_id=conn.id,
        tableau_project_id=tid,
        datasource_name="X",
        write_mode="replace",
    )
    out = publish_dataset_to_tableau(
        MagicMock(),
        project_id=conn.project_id,
        dataset_id=ds.id,
        payload=payload,
        current_user=_user(),
        storage_backend=object(),
    )
    assert out.success is False


@patch("service_destinations.tableau_publish_service.get_bi_connection_model")
@patch("service_destinations.tableau_publish_service.ensure_owned_project")
def test_publish_rejects_non_tableau(mock_ensure_owned, mock_get_conn) -> None:
    mock_ensure_owned.return_value = None
    conn = _tab_conn()
    conn.destination_type = "power_bi"
    mock_get_conn.return_value = conn
    tid = uuid.uuid4()
    payload = DatasetPublishTableauRequest(
        connection_id=conn.id,
        tableau_project_id=tid,
        datasource_name="X",
        write_mode="create_only",
    )
    with pytest.raises(BadRequestError, match="Tableau"):
        publish_dataset_to_tableau(
            MagicMock(),
            project_id=conn.project_id,
            dataset_id=uuid.uuid4(),
            payload=payload,
            current_user=_user(),
            storage_backend=object(),
        )


def test_validate_datasource_name() -> None:
    assert validate_tableau_datasource_name("  A DS  ") == "A DS"
    with pytest.raises(BadRequestError):
        validate_tableau_datasource_name("")
