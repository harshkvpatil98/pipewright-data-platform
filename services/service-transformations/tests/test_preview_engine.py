from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_auth.schemas import UserRead
from service_transformations.executor import apply_transformation_steps
from service_transformations.router import build_router
from service_transformations.steps.cast_column_types import apply_cast_column_types
from service_transformations.steps.drop_columns import apply_drop_columns
from service_transformations.steps.drop_null_rows import apply_drop_null_rows
from service_transformations.steps.fill_nulls import apply_fill_nulls
from service_transformations.steps.filter_rows import apply_filter_rows
from service_transformations.steps.parse_dates import apply_parse_dates
from service_transformations.steps.remove_duplicates import apply_remove_duplicates
from service_transformations.steps.rename_columns import apply_rename_columns
from service_transformations.steps.select_columns import apply_select_columns
from service_transformations.steps.trim_strings import apply_trim_strings
from shared_python.errors import BadRequestError, NotFoundError, UnauthorizedError, register_exception_handlers


def _csv_bytes() -> bytes:
    return b"name,amount\nalice,10\nbob,20\n"


def test_rename_columns_step() -> None:
    df = pd.DataFrame({"name": ["a"], "old_name": [1]})
    out, _ = apply_rename_columns(df, {"mappings": {"old_name": "new_name"}})
    assert list(out.columns) == ["name", "new_name"]


def test_rename_columns_rejects_collision() -> None:
    df = pd.DataFrame({"a": [1], "b": [2]})
    with pytest.raises(BadRequestError, match="duplicate"):
        apply_rename_columns(df, {"mappings": {"a": "b"}})


def test_cast_column_types_step() -> None:
    df = pd.DataFrame({"x": ["1", "2"]})
    out, warnings = apply_cast_column_types(df, {"mappings": {"x": "int"}})
    assert out["x"].iloc[0] == 1
    assert not warnings


def test_cast_invalid_type() -> None:
    df = pd.DataFrame({"x": [1]})
    with pytest.raises(BadRequestError):
        apply_cast_column_types(df, {"mappings": {"x": "bigint"}})


def test_trim_strings_step() -> None:
    df = pd.DataFrame({"t": ["  hi  "]})
    out, _ = apply_trim_strings(df, {"columns": ["t"]})
    assert out["t"].iloc[0] == "hi"


def test_drop_columns_step() -> None:
    df = pd.DataFrame({"a": [1], "b": [2]})
    out, _ = apply_drop_columns(df, {"columns": ["a"]})
    assert list(out.columns) == ["b"]


def test_drop_columns_cannot_drop_all() -> None:
    df = pd.DataFrame({"a": [1]})
    with pytest.raises(BadRequestError, match="all columns"):
        apply_drop_columns(df, {"columns": ["a"]})


def test_select_columns_step() -> None:
    df = pd.DataFrame({"a": [1], "b": [2]})
    out, w = apply_select_columns(df, {"columns": ["b"]})
    assert list(out.columns) == ["b"]
    assert w


def test_fill_nulls_constant() -> None:
    df = pd.DataFrame({"a": [1, None]})
    out, _ = apply_fill_nulls(df, {"strategy": "constant", "columns": ["a"], "constant_value": 0})
    assert out["a"].tolist() == [1, 0]


def test_fill_nulls_mean_requires_numeric() -> None:
    df = pd.DataFrame({"a": ["x", "y"]})
    with pytest.raises(BadRequestError, match="numeric"):
        apply_fill_nulls(df, {"strategy": "mean", "columns": ["a"]})


def test_fill_nulls_constant_requires_value() -> None:
    df = pd.DataFrame({"a": [1]})
    with pytest.raises(BadRequestError, match="constant_value"):
        apply_fill_nulls(df, {"strategy": "constant", "columns": ["a"]})


def test_drop_null_rows() -> None:
    df = pd.DataFrame({"a": [1, None], "b": [2, 3]})
    out, _ = apply_drop_null_rows(df, {"how": "any", "columns": ["a"]})
    assert len(out) == 1


def test_remove_duplicates_keep_none() -> None:
    df = pd.DataFrame({"a": [1, 1, 2]})
    out, _ = apply_remove_duplicates(df, {"keep": "none"})
    # Rows that participate in any duplicate group are removed entirely.
    assert len(out) == 1
    assert int(out["a"].iloc[0]) == 2


def test_filter_rows_contains() -> None:
    df = pd.DataFrame({"note": ["hello world", "bye"]})
    out, _ = apply_filter_rows(
        df,
        {"conditions": [{"column": "note", "operator": "contains", "value": "world"}]},
    )
    assert len(out) == 1


def test_filter_rows_in_operator() -> None:
    df = pd.DataFrame({"k": ["a", "b", "c"]})
    out, _ = apply_filter_rows(
        df,
        {"conditions": [{"column": "k", "operator": "in", "value": ["a", "c"]}]},
    )
    assert len(out) == 2


def test_filter_rows_invalid_in_value() -> None:
    df = pd.DataFrame({"k": [1]})
    with pytest.raises(BadRequestError, match="list"):
        apply_filter_rows(df, {"conditions": [{"column": "k", "operator": "in", "value": "a"}]})


def test_parse_dates_coerce_warning() -> None:
    df = pd.DataFrame({"d": ["2020-01-01", "not-a-date"]})
    out, w = apply_parse_dates(df, {"columns": ["d"], "errors": "coerce"})
    assert pd.isna(out["d"].iloc[1])
    assert w


def test_apply_transformation_steps_ordered() -> None:
    df = pd.DataFrame({"a": [1], "b": [2]})
    steps = [
        {"step_type": "select_columns", "config": {"columns": ["a"]}},
        {"step_type": "rename_columns", "config": {"mappings": {"a": "alpha"}}},
    ]
    out, _ = apply_transformation_steps(df, steps)
    assert list(out.columns) == ["alpha"]


def test_apply_transformation_steps_rejects_bad_structure() -> None:
    df = pd.DataFrame({"a": [1]})
    with pytest.raises(BadRequestError):
        apply_transformation_steps(df, [{"step_type": "rename_columns"}])


def _build_preview_client():
    current_user = UserRead(
        id=uuid.uuid4(),
        username="tester",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db = MagicMock()
    storage = MagicMock()
    storage.read_bytes.return_value = _csv_bytes()
    settings = MagicMock()
    settings.preview_row_limit = 50

    def get_db():
        return db

    def get_current_user():
        return current_user

    def get_storage_backend():
        return storage

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_router(get_db, get_current_user, get_storage_backend, settings))
    return TestClient(app), db, storage, current_user


@patch("service_transformations.preview.get_dataset_model_for_project")
@patch("service_transformations.preview.ensure_owned_project")
def test_preview_endpoint_success(mock_ensure, mock_get_dataset) -> None:
    ds = MagicMock()
    ds.file_path = "uploads/p/d/file.csv"
    ds.file_type = "csv"
    mock_get_dataset.return_value = ds
    client, _db, storage, _user = _build_preview_client()
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    response = client.post(
        f"/projects/{project_id}/datasets/{dataset_id}/pipelines/preview",
        json={"steps": []},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["row_count_before"] == 2
    assert body["row_count_after"] == 2
    assert "name" in body["preview_columns"]
    storage.read_bytes.assert_called_once_with("uploads/p/d/file.csv")


@patch("service_transformations.preview.get_dataset_model_for_project")
@patch(
    "service_transformations.preview.ensure_owned_project",
    side_effect=NotFoundError("Project not found."),
)
def test_preview_endpoint_ownership(mock_ensure, mock_get_dataset) -> None:
    client, _db, _storage, _user = _build_preview_client()
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    response = client.post(
        f"/projects/{project_id}/datasets/{dataset_id}/pipelines/preview",
        json={"steps": []},
    )

    assert response.status_code == 404


def test_preview_endpoint_unauthenticated() -> None:
    def get_db():
        return MagicMock()

    def get_current_user():
        raise UnauthorizedError("Authentication required.")

    def get_storage_backend():
        return MagicMock()

    settings = MagicMock()
    settings.preview_row_limit = 50

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_router(get_db, get_current_user, get_storage_backend, settings))
    client = TestClient(app)

    response = client.post(
        f"/projects/{uuid.uuid4()}/datasets/{uuid.uuid4()}/pipelines/preview",
        json={"steps": []},
    )
    assert response.status_code == 401
