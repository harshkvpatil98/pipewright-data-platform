"""A plugin's connectors, made into catalogue connectors (X1).

A REST manifest becomes a `ManifestConnector`, exactly as one of the
catalogue's own manifests does; a class written to the SDK is wrapped in a
connector that speaks the protocol (`protocol.Connector`), turning its rows
into a frame and anything it raises into a `ConnectorError` that names the
plugin. Either is checked by the conformance suite like any connector, and
is not yet tested here (tier 4) whatever it says, because nothing here has
run it against the system it reaches.
"""

from __future__ import annotations

import dataclasses
import itertools
from typing import Any

from service_connectors.protocol import (
    ConfigField,
    ConnectorError,
    ConnectorSpec,
    ReadResult,
    StreamRef,
    TestResult,
    Tier,
)


class PluginConnector:
    """An SDK ``Connector`` behind the catalogue's protocol."""

    def __init__(self, plugin: str, connector: Any) -> None:
        self._plugin = plugin
        self._connector = connector
        kind = type(connector)
        capabilities = {"test"}
        if kind.can("streams"):
            capabilities.add("discover")
        if kind.can("read"):
            capabilities.add("read")
        self.spec = ConnectorSpec(
            type=f"{plugin}_{connector.name}",
            label=connector.label,
            category=connector.category,
            description=connector.description,
            config_fields=tuple(
                ConfigField(name=field.name, label=field.label, kind=field.kind, required=field.required,
                            default=field.default, help=field.help or None, options=tuple(field.options))
                for field in connector.fields
            ),
            capabilities=frozenset(capabilities),
            tier=Tier.SPEC_ONLY,
            origin="plugin",
        )

    def _call(self, what: str, *args: Any) -> Any:
        try:
            return getattr(self._connector, what)(*args)
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001 - said where the connection is used, naming the plugin
            raise ConnectorError(f"{self.spec.label} (from the {self._plugin} plugin) failed: {exc}") from exc

    def test(self, config: dict[str, Any]) -> TestResult:
        answer = self._call("test", dict(config))
        ok, message = answer if isinstance(answer, tuple) else (bool(answer), "")
        return TestResult(success=bool(ok), message=str(message) or ("Connected." if ok else "Not connected."))

    def discover(self, config: dict[str, Any]) -> list[StreamRef]:
        return [StreamRef(name=str(name)) for name in self._call("streams", dict(config))]

    def read(self, config: dict[str, Any], stream: StreamRef | None = None, *, limit: int = 10_000,
             cursor: str | None = None) -> ReadResult:
        import pandas as pd

        if stream is None:
            raise ConnectorError(f"{self.spec.label} reads a stream; choose one of what it lists.")
        rows = list(itertools.islice(self._call("read", dict(config), stream.name, limit + 1), limit + 1))
        frame = pd.DataFrame([dict(row) for row in rows[:limit]])
        return ReadResult(dataframe=frame, row_count=len(frame), truncated=len(rows) > limit)


def manifest_connector(document: dict[str, Any]) -> Any:
    """A plugin's REST manifest as the catalogue's own manifests become connectors."""
    from service_connectors.adapters.manifest_rest import ManifestConnector
    from service_connectors.manifest import parse

    connector = ManifestConnector(parse(document))
    connector.spec = dataclasses.replace(connector.spec, origin="plugin", tier=Tier.SPEC_ONLY, verified_by=None)
    return connector
