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
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
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
    SQLAlchemyInstrumentor().instrument(engine=engine, tracer_provider=provider)
    logger.info("tracing_installed service=%s", getattr(settings, "otel_service_name", "pipewright-gateway"))
    return provider
