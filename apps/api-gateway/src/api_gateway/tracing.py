"""OpenTelemetry traces, when OTEL_ENABLED is set (adoption-readiness A7, X6).

Off by default: nothing is imported or wrapped, and requests cost what they
did. On, every request becomes a trace with a span per database statement,
exported over OTLP/HTTP to wherever OTEL_EXPORTER_OTLP_ENDPOINT points (an
OpenTelemetry Collector, Jaeger, Honeycomb, Grafana Tempo...; the standard
OTEL_* variables configure the exporter as they do anywhere). Each request's
span carries the correlation id that is already in its log lines, so a
trace and the logs of the same request can be found from each other.

Health checks and /metrics are left out: they are polled constantly and
would bury the requests worth looking at.
"""

from __future__ import annotations

from typing import Any

from shared_python.logging import get_logger

logger = get_logger(__name__)

EXCLUDED_URLS = "api/v1/health/live,api/v1/health/ready,metrics"


def install_tracing(application: Any, engine: Any, settings: Any, *, exporter: Any = None) -> Any | None:
    """Instrument the app and its database when tracing is on; return the provider, or None.

    `exporter` replaces the OTLP exporter (a test passes an in-memory one);
    without it the provider also becomes the process's global one.
    """
    if not getattr(settings, "otel_enabled", False):
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
    except ImportError:
        logger.warning("tracing_unavailable reason=opentelemetry packages are not installed")
        return None

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": getattr(settings, "otel_service_name", "pipewright-gateway"),
                "service.version": getattr(settings, "app_version", ""),
                "deployment.environment": getattr(settings, "app_env", ""),
            }
        )
    )
    if exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
    else:
        provider.add_span_processor(SimpleSpanProcessor(exporter))

    # The correlation id is put on each request's span by
    # shared_python.tracing.CorrelationIdMiddleware, inside this one.
    FastAPIInstrumentor.instrument_app(application, tracer_provider=provider, excluded_urls=EXCLUDED_URLS)
    trace_statements(engine, provider.get_tracer("pipewright.database"))
    logger.info("tracing_installed service=%s", getattr(settings, "otel_service_name", "pipewright-gateway"))
    return provider


def trace_statements(engine: Any, tracer: Any) -> None:
    """A span for each SQL statement, from SQLAlchemy's own engine events.

    The OpenTelemetry SQLAlchemy package refuses SQLAlchemy 2.1 and later
    ("nothing can be instrumented"), which a fresh install gets, so database
    spans silently vanished there (found in A7 CI). The engine events are the
    same on every version this platform supports.
    """
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode
    from sqlalchemy import event

    system = engine.dialect.name
    database = engine.url.database or ""

    @event.listens_for(engine, "before_cursor_execute")
    def _start(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        verb = (statement.lstrip().split(None, 1) or ["SQL"])[0].upper()
        span = tracer.start_span(
            f"{verb} {database}".strip(),
            kind=trace.SpanKind.CLIENT,
            attributes={"db.system": system, "db.name": database, "db.statement": statement[:2000]},
        )
        if context is not None:
            context._pipewright_span = span

    @event.listens_for(engine, "after_cursor_execute")
    def _end(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        span = getattr(context, "_pipewright_span", None)
        if span is not None:
            span.end()
            context._pipewright_span = None

    @event.listens_for(engine, "handle_error")
    def _failed(exception_context):  # noqa: ANN001
        context = exception_context.execution_context
        span = getattr(context, "_pipewright_span", None)
        if span is not None:
            span.set_status(Status(StatusCode.ERROR, str(exception_context.original_exception)[:200]))
            span.end()
            context._pipewright_span = None
