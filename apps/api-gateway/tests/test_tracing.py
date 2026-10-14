"""OpenTelemetry traces behind OTEL_ENABLED (adoption-readiness A7, X6)."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import create_engine, text

from api_gateway.tracing import install_tracing
from shared_python.tracing import CorrelationIdMiddleware
from shared_python.logging import get_logger


def _app_and_engine():
    engine = create_engine("sqlite://")
    application = FastAPI()

    @application.get("/api/v1/things")
    def things() -> dict:
        with engine.connect() as connection:
            return {"n": connection.execute(text("SELECT 1")).scalar()}

    @application.get("/api/v1/health/live")
    def live() -> dict:
        return {"ok": True}

    application.add_middleware(CorrelationIdMiddleware, logger=get_logger("test"))
    return application, engine


def test_off_by_default_nothing_is_traced() -> None:
    application, engine = _app_and_engine()
    assert install_tracing(application, engine, SimpleNamespace(otel_enabled=False)) is None


def test_on_a_request_and_its_statements_are_traced_with_the_correlation_id() -> None:
    application, engine = _app_and_engine()
    exporter = InMemorySpanExporter()
    settings = SimpleNamespace(otel_enabled=True, otel_service_name="pipewright-test", app_version="1", app_env="test")
    assert install_tracing(application, engine, settings, exporter=exporter) is not None

    client = TestClient(application)
    client.get("/api/v1/things", headers={"X-Request-ID": "req-123"})
    client.get("/api/v1/health/live")

    spans = exporter.get_finished_spans()
    request = next(span for span in spans if span.name == "GET /api/v1/things")
    assert request.attributes["pipewright.correlation_id"] == "req-123"
    assert request.resource.attributes["service.name"] == "pipewright-test"
    statements = [span for span in spans if span.attributes.get("db.statement") == "SELECT 1"]
    assert statements and statements[0].attributes["db.system"] == "sqlite"
    assert statements[0].parent is not None and statements[0].parent.trace_id == request.context.trace_id
    assert not any("health" in span.name for span in spans)  # polled constantly; left out
