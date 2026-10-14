"""Reading a stored dataset back, with its import settings and from its copy (A8).

Two faults: a dataset whose import needed an answer (ambiguous dates) could
not be read again anywhere, because every reader parsed the file afresh
without the answer; and every read of a large dataset parsed its whole file.
"""

from __future__ import annotations

import io
import os
import random
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
import service_access  # noqa: F401
from api_gateway.config import settings
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.download import download_dataset
from service_datasets.models import Dataset, DatasetVersion
from service_ingestion import read_copy
from service_ingestion.analysis_service import analyse_upload
from service_ingestion.schemas import IngestionUpload
from service_ingestion.service import ingest_project_file
from service_projects.schemas import ProjectCreate
from service_projects.service import create_project
from shared_python.db import Base
from shared_python.storage.encrypted import EncryptedStorageBackend, is_encrypted
from shared_python.storage.local import LocalStorageBackend

AMBIGUOUS = b"id,when,amount\n1,01/02/2026,10\n2,03/04/2026,20\n3,05/06/2026,30\n"


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
def world(db: Session, tmp_path) -> dict:
    row = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=row.id, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)
    project = create_project(db, ProjectCreate(name="Shop", description=None), user)
    storage = EncryptedStorageBackend(LocalStorageBackend(str(tmp_path / "files")), os.urandom(32))
    return {"user": user, "project": project, "storage": storage, "root": tmp_path / "files"}


def _import(db, world, payload: bytes, name: str, *, answer_dates: bool = False):
    spec = None
    if answer_dates:
        analysis = analyse_upload(
            db, project_id=world["project"].id, file_name=f"{name}.csv", content_type="text/csv",
            payload=payload, current_user=world["user"],
        )
        assert analysis["questions"], "the dates really are ambiguous"
        spec = analysis["spec"]
        for column in spec["columns"]:
            if column["name"] == "when":
                column.update(type="date", date_format="%d/%m/%Y")  # day first, as confirmed
    return ingest_project_file(
        db, project_id=world["project"].id, dataset_name=name,
        upload_file=IngestionUpload(file_name=f"{name}.csv", content_type="text/csv", file_bytes=payload),
        storage_backend=world["storage"], settings=settings, current_user=world["user"], ingest_spec=spec,
    ).dataset


def test_a_dataset_whose_dates_were_confirmed_reads_back_everywhere(db: Session, world: dict) -> None:
    dataset = _import(db, world, AMBIGUOUS, "Ambiguous", answer_dates=True)
    stored = db.get(Dataset, dataset.id)

    # Before A8 each of these refused: "Analyse this file first and choose".
    content, _media, _name = download_dataset(db, world["project"].id, dataset.id, world["user"], world["storage"])
    assert pd.read_csv(io.BytesIO(content))["when"].tolist() == ["2026-02-01", "2026-04-03", "2026-06-05"]

    from service_quality.service import _load_dataset_frame

    _dataset, frame = _load_dataset_frame(db, world["project"].id, dataset.id, world["storage"])
    assert frame["when"].tolist() == [date(2026, 2, 1), date(2026, 4, 3), date(2026, 6, 5)]

    version = db.query(DatasetVersion).filter_by(dataset_id=dataset.id).one()
    assert version.ingest_spec_json == stored.ingest_spec_json  # the settings belong to the file


def _large_csv(rows: int = 40_000) -> bytes:
    rng = random.Random(3)
    lines = ["order_id,customer,amount,ordered_on,paid"]
    for index in range(rows):
        lines.append(f"{index},customer {rng.randint(1, 900)},{rng.randint(1, 9999) / 100},"
                     f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d},{rng.choice(['true', 'false', ''])}")
    payload = ("\n".join(lines) + "\n").encode()
    assert len(payload) > read_copy.MIN_BYTES
    return payload


def test_a_large_dataset_is_read_from_its_copy_exactly(db: Session, world: dict, monkeypatch) -> None:
    payload = _large_csv()
    dataset = _import(db, world, payload, "Orders")
    stored = db.get(Dataset, dataset.id)
    copy_file = world["root"] / read_copy.copy_path(stored.file_path)
    assert copy_file.exists(), "ingestion keeps a copy of what it read"
    assert is_encrypted(copy_file.read_bytes()), "the copy is encrypted like the file"

    parsed = read_copy.parse(payload, file_type="csv", spec=stored.ingest_spec_json)

    def no_parsing(*_args, **_kwargs):
        raise AssertionError("the copy should answer without parsing")

    monkeypatch.setattr(read_copy, "parse", no_parsing)
    from_copy = read_copy.frame_of(
        world["storage"], stored.file_path, payload, file_type="csv", spec=stored.ingest_spec_json
    )
    assert read_copy._same(parsed, from_copy)  # same values, same Python types, same Nones


def test_a_copy_of_other_bytes_or_other_settings_is_never_used(db: Session, world: dict) -> None:
    payload = _large_csv()
    dataset = _import(db, world, payload, "Orders")
    stored = db.get(Dataset, dataset.id)

    changed = payload.replace(b"customer 1,", b"customer 1x,", 1)
    frame = read_copy.frame_of(world["storage"], stored.file_path, changed, file_type="csv", spec=stored.ingest_spec_json)
    assert "customer 1x" in set(frame["customer"]), "the stale copy was ignored and the file read"

    other_settings = dict(stored.ingest_spec_json, note="different")
    assert read_copy.fingerprint(payload, "csv", other_settings) != read_copy.fingerprint(
        payload, "csv", stored.ingest_spec_json
    )


def test_forgetting_removes_the_copy(db: Session, world: dict) -> None:
    payload = _large_csv()
    dataset = _import(db, world, payload, "Orders")
    path = db.get(Dataset, dataset.id).file_path
    read_copy.forget_copy(world["storage"], path)
    assert not (world["root"] / read_copy.copy_path(path)).exists()
    read_copy.forget_copy(world["storage"], path)  # a copy that is not there is no error


def test_a_table_that_would_not_read_back_exactly_gets_no_copy(world: dict) -> None:
    mixed = pd.DataFrame({"value": [1, "two", 3.5, None]})  # pyarrow cannot hold this column
    assert not read_copy.keep_copy(
        world["storage"], "x/mixed.csv", b"x" * read_copy.MIN_BYTES, mixed, file_type="csv", spec=None
    )
    assert not (world["root"] / read_copy.copy_path("x/mixed.csv")).exists()


def test_erasure_leaves_no_copy_of_the_erased_values(db: Session, world: dict) -> None:
    from service_enterprise.schemas import ErasureCreate
    from service_enterprise.service import request_erasure

    rows = ["id,email,amount"] + [f"{index},person{index}@example.com,{index}" for index in range(60_000)]
    payload = ("\n".join(rows) + "\n").encode()
    dataset = _import(db, world, payload, "People")
    path = db.get(Dataset, dataset.id).file_path
    copy_file = world["root"] / read_copy.copy_path(path)
    assert copy_file.exists()

    request_erasure(
        db, world["project"].id,
        ErasureCreate(subject_kind="email", subject_value="person7@example.com", apply=True, mode="destructive"),
        world["user"], world["storage"],
    )
    db.commit()
    if copy_file.exists():
        frame = read_copy._restore(world["storage"].read_bytes(read_copy.copy_path(path)))
        assert "person7@example.com" not in set(frame["email"])
    assert not db.get(Dataset, dataset.id).ingest_spec_json, "the rewritten file is read automatically"
