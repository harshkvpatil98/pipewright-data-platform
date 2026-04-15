from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from service_transformations.models import TransformationPipeline
from service_schedules.validators import validate_and_normalize_target_config, validate_cron_expression
from shared_python.errors import BadRequestError


def test_validate_cron_expression_accepts_standard_five_field() -> None:
    assert validate_cron_expression("0 9 * * *").startswith("0 9")


def test_validate_cron_expression_rejects_garbage() -> None:
    with pytest.raises(BadRequestError):
        validate_cron_expression("not a cron")


def test_validate_target_transformation_pipeline() -> None:
    db = MagicMock()
    pid = uuid.uuid4()
    pl_id = uuid.uuid4()
    pipeline = MagicMock(spec=TransformationPipeline)
    with patch("service_schedules.validators.get_transformation_pipeline_for_project", return_value=pipeline):
        out = validate_and_normalize_target_config(
            db,
            project_id=pid,
            schedule_type="transformation_pipeline_run",
            target={"pipeline_id": str(pl_id)},
        )
    assert out == {"pipeline_id": str(pl_id)}


def test_validate_target_transformation_rejects_extra_keys() -> None:
    db = MagicMock()
    with pytest.raises(BadRequestError):
        validate_and_normalize_target_config(
            db,
            project_id=uuid.uuid4(),
            schedule_type="transformation_pipeline_run",
            target={"pipeline_id": str(uuid.uuid4()), "extra": "x"},
        )


def test_validate_target_postgres_publish() -> None:
    db = MagicMock()
    pid = uuid.uuid4()
    ds_id = uuid.uuid4()
    dest_id = uuid.uuid4()

    ds = MagicMock()
    ds.file_path = "p"
    ds.file_type = "csv"
    dest = MagicMock()
    dest.destination_type = "postgres"
    dest.status = "active"

    with (
        patch("service_schedules.validators.get_dataset_model_for_project", return_value=ds),
        patch("service_schedules.validators.get_destination_model", return_value=dest),
    ):
        out = validate_and_normalize_target_config(
            db,
            project_id=pid,
            schedule_type="postgres_publish",
            target={
                "dataset_id": str(ds_id),
                "destination_id": str(dest_id),
                "table_name": "ok_table",
                "write_mode": "append",
            },
        )
    assert out["table_name"] == "ok_table"
    assert out["write_mode"] == "append"


def test_validate_table_name_rejected() -> None:
    db = MagicMock()
    with pytest.raises(BadRequestError):
        validate_and_normalize_target_config(
            db,
            project_id=uuid.uuid4(),
            schedule_type="postgres_publish",
            target={
                "dataset_id": str(uuid.uuid4()),
                "destination_id": str(uuid.uuid4()),
                "table_name": "bad-name",
                "write_mode": "replace",
            },
        )
