"""Object stores, from the store table.

Two kinds come out of `stores.py`, and they are honestly different:

* **S3-compatible** stores are the tested S3 connector with an endpoint filled
  in. MinIO, R2, B2, Spaces, Wasabi and Oracle all publish the S3 API, so this
  is working code rather than a declaration -- the same code path the existing
  S3 tests exercise.
* **Native** stores need their own SDK, and are represented by a connector that
  exists, appears in the catalogue, and answers `test()` with the package to
  install. Hiding them would make the catalogue smaller and less useful; a
  connector that pretends to work would be worse than both.
"""

from __future__ import annotations

from typing import Any

from service_connectors.adapters.files import S3Connector
from service_connectors.protocol import (
    ConnectorError,
    ConnectorSpec,
    ReadResult,
    StreamColumn,
    StreamRef,
    TestResult,
    with_tier_note,
)
from service_connectors.stores import S3_COMPATIBLE, Store, spec_for


class S3CompatibleConnector(S3Connector):
    """An S3-API store whose endpoint comes from the store table."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.spec: ConnectorSpec = spec_for(store)

    def _resolved(self, config: dict[str, Any]) -> dict[str, Any]:
        template = self.store.endpoint_template or ""
        try:
            endpoint = template.format(**{key: str(value) for key, value in config.items()})
        except KeyError as exc:
            raise ConnectorError(
                f"{self.store.label} needs {exc.args[0]} to build its address."
            ) from exc
        if "{" in endpoint:
            raise ConnectorError(f"{self.store.label}'s address is incomplete: {endpoint}")
        # The store's own settings are not S3 settings; only what the S3
        # connector understands is passed through, plus the endpoint it needs.
        return {**config, "endpoint_url": endpoint}

    def test(self, config: dict[str, Any]) -> TestResult:
        return with_tier_note(super().test(self._resolved(config)), self.spec)

    def discover(self, config: dict[str, Any]) -> list[StreamRef]:
        return super().discover(self._resolved(config))

    def columns(self, config: dict[str, Any], stream: StreamRef) -> list[StreamColumn]:
        return super().columns(self._resolved(config), stream)

    def read(self, config: dict[str, Any], stream: StreamRef, **kwargs: Any) -> ReadResult:
        return super().read(self._resolved(config), stream, **kwargs)

    def write(self, config: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        return super().write(self._resolved(config), *args, **kwargs)


class DeclaredStoreConnector:
    """A store whose SDK is not installed here.

    It answers `test()` with the package to install and declares only `test`,
    so `supports("read")` never promises something a caller would discover by
    trying it. Same posture as an unavailable database driver.
    """

    def __init__(self, store: Store) -> None:
        self.store = store
        self.spec: ConnectorSpec = spec_for(store)

    def test(self, config: dict[str, Any]) -> TestResult:
        available, reason = self.store.available()
        if not available:
            return TestResult(success=False, message=reason or f"{self.store.label} is unavailable.")
        return TestResult(
            success=False,
            message=(
                f"The '{self.store.package}' package is installed, but this platform has "
                f"no {self.store.label} client wired up yet. Use an S3-compatible endpoint "
                "if the store offers one."
            ),
        )


class DeclaredEngineConnector:
    """An engine in the catalogue that this platform cannot drive yet.

    Distinct from a *store* only in what it offers instead: a store can often
    be reached over the S3 API, and an engine usually publishes a second
    interface -- Stargate's REST gateway in front of Cassandra, WebHDFS in
    front of HDFS -- that the platform already reads. Saying so is the point of
    the entry; a catalogue that simply omitted Cassandra would leave somebody
    concluding their data was out of reach.
    """

    def __init__(self, store: Any) -> None:
        from service_connectors.datastores import spec_for as engine_spec

        self.store = store
        self.spec: ConnectorSpec = engine_spec(store)

    def test(self, _config: dict[str, Any]) -> TestResult:
        return TestResult(
            success=False,
            message=self.spec.unavailable_reason
            or f"{self.spec.label} is not available on this deployment.",
        )


def connector_for(store: Store):
    """The connector for one store entry."""
    if store.kind == S3_COMPATIBLE:
        return S3CompatibleConnector(store)
    return DeclaredStoreConnector(store)
