"""Document stores, read as tables.

The interesting work is not the driver, it is the translation: a collection has
no schema, so two documents in it may share nothing. Reading one as a table means
deciding what a column is, and that decision lives in `service_connectors.flatten`
so the API connector makes it identically.

The drivers are optional. Declaring the connectors without them is not
pretending -- the spec is what the UI renders and what config validation
enforces, and `test()` says which package is missing rather than raising an
ImportError somewhere inside a scheduled run.
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from service_connectors.flatten import flatten_records
from service_connectors.protocol import (
    ConfigField,
    ConnectorError,
    ConnectorSpec,
    ReadResult,
    StreamColumn,
    StreamRef,
    TestResult,
    with_tier_note,
)

# How many documents to look at when working out what the columns are. A
# collection with no schema needs a sample; the whole thing would be a scan.
SCHEMA_SAMPLE_SIZE = 200


def infer_columns(records: list[dict[str, Any]]) -> list[StreamColumn]:
    """Work out a table shape from a sample of documents.

    A field missing from some documents is nullable -- that is what a document
    store means by leaving it out. A field present in every one is not.
    """
    if not records:
        return []

    rows = flatten_records(records)
    counts: dict[str, int] = {}
    types: dict[str, set[str]] = {}

    for row in rows:
        for key, value in row.items():
            counts[key] = counts.get(key, 0) + 1
            if value is not None:
                types.setdefault(key, set()).add(type(value).__name__)

    columns: list[StreamColumn] = []
    for key in rows[0].keys() | set(counts):
        seen = sorted(types.get(key, set()))
        # More than one type across the sample is worth surfacing rather than
        # picking a winner: it is usually a bug upstream.
        data_type = seen[0] if len(seen) == 1 else ("mixed" if seen else "unknown")
        columns.append(
            StreamColumn(
                name=key,
                data_type=data_type,
                nullable=counts.get(key, 0) < len(rows),
            )
        )
    return sorted(columns, key=lambda column: column.name)


class MongoConnector:
    """MongoDB, flattened on read."""

    spec = ConnectorSpec(
        type="mongodb",
        label="MongoDB",
        category="nosql",
        description="Read a MongoDB collection as a table, flattening nested fields.",
        config_fields=(
            ConfigField(
                "connection_string",
                "Connection string",
                kind="secret",
                placeholder="mongodb://host:27017",
                help="Includes the credentials, so it is stored encrypted.",
            ),
            ConfigField("database", "Database"),
            ConfigField(
                "collection",
                "Collection",
                required=False,
                help="Leave blank to list every collection instead.",
            ),
            ConfigField(
                "filter_json",
                "Filter",
                kind="text",
                required=False,
                help="A MongoDB query document, as JSON.",
            ),
        ),
        capabilities=frozenset({"test", "discover", "schema", "read"}),
        driver_package="pymongo",
    )

    def _client(self, config: dict[str, Any]):
        try:
            import pymongo
        except ImportError as exc:
            raise ConnectorError(
                "MongoDB support needs the 'pymongo' package, which is not installed "
                "on this deployment."
            ) from exc

        return pymongo.MongoClient(
            str(config["connection_string"]), serverSelectionTimeoutMS=5000
        )

    def test(self, config: dict[str, Any]) -> TestResult:
        started = time.perf_counter()
        try:
            client = self._client(config)
            info = client.server_info()
            names = client[str(config["database"])].list_collection_names()
        except ConnectorError as exc:
            return TestResult(success=False, message=exc.message)
        except Exception as exc:  # noqa: BLE001 - any driver failure is a failed test
            return TestResult(success=False, message=f"Could not connect: {exc}")

        return TestResult(
            success=True,
            message=f"Connected. {len(names)} collection(s) in this database.",
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            server_version=str(info.get("version")) if isinstance(info, dict) else None,
        )

    def discover(self, config: dict[str, Any]) -> list[StreamRef]:
        client = self._client(config)
        database = str(config["database"])
        return [
            StreamRef(name=name, namespace=database, kind="collection")
            for name in sorted(client[database].list_collection_names())
        ]

    def _query(self, config: dict[str, Any]) -> dict[str, Any]:
        import json

        raw = str(config.get("filter_json") or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise ConnectorError(f"The filter is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ConnectorError("The filter must be a JSON object.")
        return parsed

    def _collection(self, config: dict[str, Any], stream: StreamRef | None):
        client = self._client(config)
        name = stream.name if stream is not None else str(config.get("collection") or "")
        if not name:
            raise ConnectorError("No collection chosen.")
        return client[str(config["database"])][name]

    def columns(self, config: dict[str, Any], stream: StreamRef) -> list[StreamColumn]:
        documents = list(
            self._collection(config, stream).find(self._query(config)).limit(SCHEMA_SAMPLE_SIZE)
        )
        return infer_columns([_drop_object_ids(doc) for doc in documents])

    def read(
        self,
        config: dict[str, Any],
        stream: StreamRef | None = None,
        *,
        limit: int = 10_000,
        cursor: str | None = None,
    ) -> ReadResult:
        collection = self._collection(config, stream)
        # One more than asked for, so "there was more" is a fact rather than a guess.
        documents = list(collection.find(self._query(config)).limit(limit + 1))
        truncated = len(documents) > limit
        documents = documents[:limit]

        rows = flatten_records([_drop_object_ids(doc) for doc in documents])
        frame = pd.DataFrame(rows)
        return with_tier_note(
            ReadResult(dataframe=frame, row_count=len(frame), truncated=truncated),
            self.spec,
        )


def _drop_object_ids(document: Any) -> dict[str, Any]:
    """Turn driver-native types into something a dataframe can hold."""
    if not isinstance(document, dict):
        return {"value": str(document)}
    cleaned: dict[str, Any] = {}
    for key, value in document.items():
        if type(value).__name__ == "ObjectId":
            cleaned[str(key)] = str(value)
        elif isinstance(value, dict):
            cleaned[str(key)] = _drop_object_ids(value)
        else:
            cleaned[str(key)] = value
    return cleaned


class DynamoConnector:
    """DynamoDB, read a table at a time."""

    spec = ConnectorSpec(
        type="dynamodb",
        label="DynamoDB",
        category="nosql",
        description="Scan an Amazon DynamoDB table, flattening nested attributes.",
        config_fields=(
            ConfigField("region", "Region", default="us-east-1"),
            ConfigField("table", "Table", required=False, help="Leave blank to list tables."),
            ConfigField("access_key_id", "Access key id"),
            ConfigField("secret_access_key", "Secret access key", kind="secret"),
            ConfigField(
                "endpoint_url",
                "Endpoint URL",
                required=False,
                help="Set this for DynamoDB Local.",
            ),
        ),
        capabilities=frozenset({"test", "discover", "schema", "read"}),
        driver_package="boto3",
    )

    def _resource(self, config: dict[str, Any]):
        try:
            import boto3
        except ImportError as exc:
            raise ConnectorError("DynamoDB support needs the 'boto3' package.") from exc

        return boto3.resource(
            "dynamodb",
            region_name=str(config.get("region") or "us-east-1"),
            endpoint_url=config.get("endpoint_url") or None,
            aws_access_key_id=str(config.get("access_key_id") or ""),
            aws_secret_access_key=str(config.get("secret_access_key") or ""),
        )

    def test(self, config: dict[str, Any]) -> TestResult:
        started = time.perf_counter()
        try:
            tables = list(self._resource(config).tables.all())
        except ConnectorError as exc:
            return TestResult(success=False, message=exc.message)
        except Exception as exc:  # noqa: BLE001
            return TestResult(success=False, message=f"Could not connect: {exc}")

        return TestResult(
            success=True,
            message=f"Connected. {len(tables)} table(s) visible.",
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    def discover(self, config: dict[str, Any]) -> list[StreamRef]:
        return [
            StreamRef(name=table.name, kind="table")
            for table in self._resource(config).tables.all()
        ]

    def columns(self, config: dict[str, Any], stream: StreamRef) -> list[StreamColumn]:
        table = self._resource(config).Table(stream.name)
        response = table.scan(Limit=SCHEMA_SAMPLE_SIZE)
        return infer_columns(response.get("Items", []))

    def read(
        self,
        config: dict[str, Any],
        stream: StreamRef | None = None,
        *,
        limit: int = 10_000,
        cursor: str | None = None,
    ) -> ReadResult:
        name = stream.name if stream is not None else str(config.get("table") or "")
        if not name:
            raise ConnectorError("No table chosen.")

        table = self._resource(config).Table(name)
        items: list[dict[str, Any]] = []
        start_key: dict[str, Any] | None = None

        while len(items) < limit:
            kwargs: dict[str, Any] = {"Limit": min(limit - len(items), 1000)}
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key
            response = table.scan(**kwargs)
            items.extend(response.get("Items", []))
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break

        truncated = bool(start_key)
        frame = pd.DataFrame(flatten_records(items[:limit]))
        return with_tier_note(
            ReadResult(dataframe=frame, row_count=len(frame), truncated=truncated),
            self.spec,
        )


NOSQL_CONNECTORS = (MongoConnector(), DynamoConnector())
