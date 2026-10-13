"""Delivering a dataset to a destination (adoption-readiness A4, U3).

The folder tests always run. The table tests need the servers from
`docker-compose.connectors.yml` and skip with the reason otherwise; the S3
test needs an S3-compatible store (MinIO) and DELIVERY_TEST_S3_* variables.
"""

from __future__ import annotations

import io
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
import service_access  # noqa: F401
from api_gateway.config import settings
from service_auth.models import User
from service_auth.schemas import UserRead
from service_destinations.deliver import deliver_dataset, preview_delivery
from service_destinations.publish_schemas import DeliveryRequest
from service_destinations.schemas import DestinationCreate
from service_destinations.service import create_destination
from service_ingestion.schemas import IngestionUpload
from service_ingestion.service import ingest_project_file
from service_pipeline_runs.models import PipelineRun
from service_projects.schemas import ProjectCreate
from service_projects.service import create_project
from shared_python.db import Base
from shared_python.errors import BadRequestError
from shared_python.storage.local import LocalStorageBackend

CSV = b"order_id,customer,amount\n1,ann,10\n2,bo,20\n3,cy,30\n"


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def server_files(tmp_path, monkeypatch):
    root = tmp_path / "server-files"
    (root / "exports").mkdir(parents=True)
    monkeypatch.setenv("SERVER_FILES_ROOT", str(root))
    return root


@pytest.fixture()
def world(db: Session, tmp_path) -> dict:
    row = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=row.id, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)
    storage = LocalStorageBackend(str(tmp_path / "storage"))
    project = create_project(db, ProjectCreate(name="Shop", description=None), user)
    uploaded = ingest_project_file(
        db, project_id=project.id, dataset_name="Orders",
        upload_file=IngestionUpload(file_name="o.csv", content_type="text/csv", file_bytes=CSV),
        storage_backend=storage, settings=settings, current_user=user,
    )
    return {"project": project, "dataset": uploaded.dataset, "user": user, "storage": storage}


def _destination(db, world, kind: str, config: dict):
    return create_destination(
        db, world["project"].id,
        DestinationCreate(name=f"{kind} target", destination_type=kind, config_json=config), world["user"],
    )


def _deliver(db, world, **request):
    return deliver_dataset(
        db, world["project"].id, world["dataset"].id, DeliveryRequest(**request), world["user"], world["storage"],
        notify_on_complete=False,
    )


# ------------------------------------------------------------ server folder


def test_a_folder_destination_writes_csv_and_parquet(db, world, server_files) -> None:
    folder = _destination(db, world, "local_export", {"path": "exports"})
    preview = preview_delivery(
        db, world["project"].id, world["dataset"].id,
        DeliveryRequest(destination_id=folder.id, file_name="orders", file_format="parquet"),
        world["user"], world["storage"],
    )
    assert preview.kind == "file"
    assert preview.target.endswith("exports/orders.parquet")
    assert [c.name for c in preview.columns] == ["order_id", "customer", "amount"]

    _deliver(db, world, destination_id=folder.id, file_name="orders", file_format="parquet")
    _deliver(db, world, destination_id=folder.id, file_name="daily/orders", file_format="csv")
    assert len(pd.read_parquet(server_files / "exports" / "orders.parquet")) == 3
    assert len(pd.read_csv(server_files / "exports" / "daily" / "orders.csv")) == 3


def test_appending_to_a_file_adds_rows(db, world, server_files) -> None:
    folder = _destination(db, world, "local_export", {"path": "exports"})
    _deliver(db, world, destination_id=folder.id, file_name="log.csv", mode="append")
    result = _deliver(db, world, destination_id=folder.id, file_name="log.csv", mode="append")
    assert result.status == "succeeded"
    assert len(pd.read_csv(server_files / "exports" / "log.csv")) == 6


def test_a_delivery_is_recorded_as_a_run(db, world, server_files) -> None:
    folder = _destination(db, world, "local_export", {"path": "exports"})
    result = _deliver(db, world, destination_id=folder.id, file_name="orders.csv")
    run = db.get(PipelineRun, result.run_id)
    assert run.run_type == "dataset_delivery"
    assert run.status == "succeeded"
    assert run.summary_json["rows_written"] == 3
    assert run.summary_json["destination"]["label"] == "Server folder"


def test_a_folder_outside_the_server_files_folder_cannot_be_saved(db, world, server_files) -> None:
    with pytest.raises(BadRequestError, match="Only folders inside"):
        _destination(db, world, "local_export", {"path": "/etc"})


@pytest.mark.parametrize("name", ["../escape.csv", "a/../../b.csv"])
def test_a_file_name_cannot_climb_out_of_the_folder(db, world, server_files, name) -> None:
    folder = _destination(db, world, "local_export", {"path": "exports"})
    with pytest.raises(BadRequestError):
        _deliver(db, world, destination_id=folder.id, file_name=name)


def test_files_cannot_update_matching_rows(db, world, server_files) -> None:
    folder = _destination(db, world, "local_export", {"path": "exports"})
    with pytest.raises(BadRequestError, match="needs a database"):
        _deliver(db, world, destination_id=folder.id, file_name="x.csv", mode="update", key_columns=["order_id"])


# ------------------------------------------------------------ real servers


@pytest.fixture(params=["postgres", "mysql"])
def table_destination(request, db, world):
    url = os.environ.get(f"CONNECTORS_TEST_{request.param.upper()}_URL")
    if not url:
        pytest.skip(f"Set CONNECTORS_TEST_{request.param.upper()}_URL to deliver into a real {request.param} server.")
    parsed = make_url(url)
    config = {"host": parsed.host, "port": parsed.port, "database": parsed.database,
              "username": parsed.username, "password": parsed.password}
    if request.param == "postgres":
        config["ssl_mode"] = "disable"
    table = f"delivered_{uuid.uuid4().hex[:8]}"
    engine = create_engine(url)
    yield _destination(db, world, request.param, config), table, engine
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
    engine.dispose()


def test_updating_matching_rows_twice_leaves_no_duplicates(db, world, table_destination) -> None:
    destination, table, engine = table_destination
    first = _deliver(db, world, destination_id=destination.id, table_name=table, mode="update", key_columns=["order_id"])
    second = _deliver(db, world, destination_id=destination.id, table_name=table, mode="update", key_columns=["order_id"])
    assert first.status == second.status == "succeeded", (first.message, second.message)
    assert first.table_created and second.rows_updated == 3 and second.rows_added == 0
    with engine.connect() as conn:
        assert conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() == 3


def test_a_refused_delivery_is_a_failed_run_with_the_reason(db, world, table_destination) -> None:
    destination, table, engine = table_destination
    with engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE {table} (order_id INTEGER)"))
    result = _deliver(db, world, destination_id=destination.id, table_name=table, mode="append")
    assert result.status == "failed"
    assert "has no column" in result.message
    assert db.get(PipelineRun, result.run_id).status == "failed"


# ------------------------------------------------------------------ S3


def test_an_s3_compatible_store_receives_the_file(db, world) -> None:
    endpoint = os.environ.get("DELIVERY_TEST_S3_ENDPOINT")
    if not endpoint:
        pytest.skip("Set DELIVERY_TEST_S3_ENDPOINT, _BUCKET, _KEY and _SECRET to deliver to an S3-compatible store.")
    import boto3

    config = {
        "bucket": os.environ["DELIVERY_TEST_S3_BUCKET"], "endpoint_url": endpoint, "prefix": "deliveries",
        "access_key_id": os.environ["DELIVERY_TEST_S3_KEY"], "secret_access_key": os.environ["DELIVERY_TEST_S3_SECRET"],
    }
    client = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=config["access_key_id"],
                          aws_secret_access_key=config["secret_access_key"], region_name="us-east-1")
    if config["bucket"] not in [bucket["Name"] for bucket in client.list_buckets().get("Buckets", [])]:
        client.create_bucket(Bucket=config["bucket"])
    store = _destination(db, world, "s3", config)
    name = f"orders-{uuid.uuid4().hex[:6]}"
    result = _deliver(db, world, destination_id=store.id, file_name=name, file_format="csv")
    assert result.target == f"s3://{config['bucket']}/deliveries/{name}.csv"
    body = client.get_object(Bucket=config["bucket"], Key=f"deliveries/{name}.csv")["Body"].read()
    assert len(pd.read_csv(io.BytesIO(body))) == 3


def test_a_workflow_deliver_task_writes_to_any_destination(db, world, server_files) -> None:
    """A workflow's Deliver task used to write to PostgreSQL only, while its
    settings offered every destination; a folder (or MySQL, or S3) failed
    when the run reached it. It now delivers the way Send to does."""
    from service_workflows.nodes import NodeContext, run_publish_node, table_name_for

    folder = _destination(db, world, "local_export", {"path": "exports"})
    context = NodeContext(
        db=db, project_id=world["project"].id, current_user=world["user"],
        storage_backend=world["storage"], settings=settings,
    )
    result = run_publish_node(
        {"destination_id": str(folder.id), "dataset_id": str(world["dataset"].id),
         "file_name": "nightly", "file_format": "csv"},
        context,
    )
    assert result.success, result.message
    assert len(pd.read_csv(server_files / "exports" / "nightly.csv")) == 3
    assert result.output["target"].endswith("exports/nightly.csv")
    assert table_name_for("Sample customers 2026") == "sample_customers_2026"
    assert table_name_for("2026 orders") == "t_2026_orders"
