"""The suite every connector has to pass.

This is what makes the tenth connector cheap. Without it, each new backend
brings its own idea of what "list the tables" returns and its own set of tests,
and the differences only surface when a pipeline built against one is pointed at
another.

The checks are deliberately about *contract*, not behaviour: they do not care
what a connector returns, only that what it returns has the shape it promised
and that it refuses configurations it said were invalid. A connector that needs
a live server can run the subset that does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared_python.errors import ApplicationError

from service_connectors.protocol import (
    CAPABILITIES,
    Connector,
    ReadResult,
    StreamColumn,
    StreamRef,
    TestResult,
)
from service_connectors.registry import validate_config


@dataclass
class ConformanceReport:
    connector_type: str
    passed: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_type": self.connector_type,
            "ok": self.ok,
            "passed": list(self.passed),
            "failures": list(self.failures),
            "skipped": list(self.skipped),
        }


def check_spec(connector: Connector) -> ConformanceReport:
    """Everything checkable without touching a remote system."""
    report = ConformanceReport(connector_type=getattr(connector.spec, "type", "?"))
    spec = connector.spec

    _expect(report, "has a type", bool(spec.type and spec.type.strip()))
    _expect(report, "has a label", bool(spec.label and spec.label.strip()))
    _expect(report, "has a description", len(spec.description.strip()) >= 10)
    _expect(
        report,
        "declares only known capabilities",
        set(spec.capabilities) <= set(CAPABILITIES),
    )
    _expect(report, "declares at least one capability", bool(spec.capabilities))

    names = [field.name for field in spec.config_fields]
    _expect(report, "config field names are unique", len(names) == len(set(names)))
    _expect(
        report,
        "every config field has a label",
        all(field.label.strip() for field in spec.config_fields),
    )

    # A connector that declares a capability must actually have the method, or
    # callers branching on the declaration will hit an AttributeError.
    for capability, method in (
        ("test", "test"),
        ("discover", "discover"),
        ("schema", "columns"),
        ("read", "read"),
        ("write", "write"),
    ):
        if spec.supports(capability):
            _expect(
                report,
                f"implements {method}() as declared by '{capability}'",
                callable(getattr(connector, method, None)),
            )

    _check_required_config_rejected(report, connector)
    return report


def _check_required_config_rejected(report: ConformanceReport, connector: Connector) -> None:
    """An empty config must be refused, not accepted and failed later."""
    if not connector.spec.required_fields:
        report.skipped.append("rejects an empty config (nothing is required)")
        return
    try:
        validate_config(connector.spec.type, {})
    except ApplicationError:
        report.passed.append("rejects an empty config")
    else:
        report.failures.append("accepts an empty config despite requiring fields")


def check_live(connector: Connector, config: dict[str, Any]) -> ConformanceReport:
    """The checks that need a reachable system, run against a real config."""
    report = ConformanceReport(connector_type=connector.spec.type)
    spec = connector.spec

    if spec.supports("test"):
        result = connector.test(config)  # type: ignore[attr-defined]
        _expect(report, "test() returns a TestResult", isinstance(result, TestResult))
        _expect(report, "test() explains itself", bool(getattr(result, "message", "")))

    streams: list[StreamRef] = []
    if spec.supports("discover"):
        streams = list(connector.discover(config))  # type: ignore[attr-defined]
        _expect(
            report,
            "discover() returns StreamRefs",
            all(isinstance(stream, StreamRef) for stream in streams),
        )

    if spec.supports("schema") and streams:
        columns = list(connector.columns(config, streams[0]))  # type: ignore[attr-defined]
        _expect(
            report,
            "columns() returns StreamColumns",
            all(isinstance(column, StreamColumn) for column in columns),
        )

    if spec.supports("read") and streams:
        result = connector.read(config, streams[0], limit=5)  # type: ignore[attr-defined]
        _expect(report, "read() returns a ReadResult", isinstance(result, ReadResult))
        if isinstance(result, ReadResult):
            _expect(
                report,
                "read() honours the row limit",
                result.row_count <= 5,
            )
            _expect(
                report,
                "read() reports a row count matching its frame",
                result.row_count == len(result.dataframe),
            )
    elif spec.supports("read"):
        report.skipped.append("read() (nothing discovered to read)")

    return report


def _expect(report: ConformanceReport, name: str, condition: bool) -> None:
    if condition:
        report.passed.append(name)
    else:
        report.failures.append(name)
