"""Audit entries carry the request's correlation id (found in A7).

The middleware read a header nothing set, so every entry's correlation id was
empty and an audit line could not be matched to its log lines or trace. This
runs the two middlewares in the gateway's order.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api_gateway.metadata  # noqa: F401  - registers every model mapping
from service_governance import AuditMiddleware
from service_governance.models import AuditEntry
from shared_python.db import Base
from shared_python.logging import get_logger
from shared_python.tracing import CorrelationIdMiddleware


def test_an_audit_entry_records_the_correlation_id_the_response_carries() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)

    application = FastAPI()

    @application.post("/api/v1/projects")
    def create() -> dict:
        return {"ok": True}

    application.add_middleware(CorrelationIdMiddleware, logger=get_logger("test"))
    application.add_middleware(AuditMiddleware, session_factory=sessions)  # outermost, as in main.py

    client = TestClient(application)
    given = client.post("/api/v1/projects", headers={"X-Request-ID": "req-given"})
    made = client.post("/api/v1/projects")

    with sessions() as db:
        recorded = [entry.correlation_id for entry in db.scalars(select(AuditEntry).order_by(AuditEntry.created_at))]
    assert given.headers["x-request-id"] == "req-given"
    assert recorded == ["req-given", made.headers["x-request-id"]]
