"""A long run keeps its lease while it works (adoption-readiness A7).

Before this, a workflow longer than its lease, or a delivery that reported
no progress for its lease, was failed as stalled by a second worker while it
was still running.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Column, DateTime, MetaData, String, Table, Uuid, create_engine, select

from shared_python.lease import kept, renew

METADATA = MetaData()
RUNS = Table(
    "runs", METADATA,
    Column("id", Uuid, primary_key=True),
    Column("claim_owner_id", String(128)),
    Column("claim_expires_at", DateTime(timezone=True)),
)


def _engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'runs.db'}")  # a file, so threads share it
    METADATA.create_all(engine)
    return engine


def _claimed(engine, owner="worker-1", seconds=1) -> uuid.UUID:
    row_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(RUNS.insert().values(
            id=row_id, claim_owner_id=owner, claim_expires_at=datetime.now(UTC) + timedelta(seconds=seconds)))
    return row_id


def _expires(engine, row_id):
    with engine.connect() as connection:
        value = connection.execute(select(RUNS.c.claim_expires_at).where(RUNS.c.id == row_id)).scalar()
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def test_the_lease_is_renewed_while_the_work_goes_on(tmp_path) -> None:
    engine = _engine(tmp_path)
    row_id = _claimed(engine, seconds=1)
    with kept(engine, table=RUNS, row_id=row_id, owner="worker-1", lease_seconds=600, every_seconds=0.05):
        time.sleep(0.3)  # longer than the one-second lease would allow, many times over in a real run
    assert _expires(engine, row_id) > datetime.now(UTC) + timedelta(seconds=500)


def test_only_the_owner_renews(tmp_path) -> None:
    engine = _engine(tmp_path)
    row_id = _claimed(engine, owner="worker-2")
    assert not renew(engine, table=RUNS, row_id=row_id, owner="worker-1", lease_seconds=600)
    with engine.begin() as connection:
        connection.execute(RUNS.update().values(claim_expires_at=None))  # finished
    assert not renew(engine, table=RUNS, row_id=row_id, owner="worker-2", lease_seconds=600)


def test_nothing_is_kept_after_the_block(tmp_path) -> None:
    engine = _engine(tmp_path)
    row_id = _claimed(engine, seconds=1)
    with kept(engine, table=RUNS, row_id=row_id, owner="worker-1", lease_seconds=600, every_seconds=0.05):
        pass
    before = _expires(engine, row_id)
    time.sleep(0.2)
    assert _expires(engine, row_id) == before
