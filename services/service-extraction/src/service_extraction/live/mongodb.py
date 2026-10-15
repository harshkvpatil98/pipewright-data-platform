"""Change capture from MongoDB change streams (D1, roadmap Phase 20).

Opens a change stream on the database, narrowed to the followed
collections, from a saved resume token (or, the first time, from the
cluster time taken before the snapshot), reads what is there and closes it.
Inserts, updates and replacements carry the whole document as it is now
(`updateLookup`); deletes carry its `_id`. The resume token is saved with
the events, so each change is saved once.

Change streams need a replica set or a sharded cluster; a standalone server
has no change log to read, and the test says so.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC
from typing import Any

from service_extraction.live.base import (
    Batch, ChangeCaptureKind, LiveError, Message, Outcome, plain, position_of,
)


def _bson_plain(value: Any) -> Any:
    """BSON's own types as plain values: ids and decimals as text and numbers."""
    try:
        from bson import Decimal128, ObjectId
        from bson.timestamp import Timestamp
    except ImportError:  # pragma: no cover - pymongo ships bson
        return plain(value)
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, Decimal128):
        return plain(value.to_decimal())
    if isinstance(value, Timestamp):
        return value.as_datetime().astimezone(UTC).isoformat()
    if isinstance(value, dict):
        return {str(k): _bson_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_bson_plain(v) for v in value]
    return plain(value)


#: Changes after which the stream cannot go on, in words.
_ENDED = {"drop": "dropped", "rename": "renamed", "dropDatabase": "dropped with its database",
          "invalidate": "removed"}


class MongoChangeCapture(ChangeCaptureKind):
    key = "mongodb_cdc"
    label = "MongoDB change capture"
    description = "Follow collections through MongoDB change streams and keep each one current."
    connection_types = ("mongodb",)
    verified_by = "test_live_change_capture.py"
    driver_module = "pymongo"
    driver_package = "pymongo"

    def _client(self, settings: dict[str, Any]):
        import pymongo

        return pymongo.MongoClient(
            str(settings["connection"]["connection_string"]), serverSelectionTimeoutMS=5000, tz_aware=True,
        )

    def _database(self, client, settings: dict[str, Any]):
        name = settings["connection"].get("database")
        if not name:
            raise LiveError("The connection names no database.")
        return client[str(name)]

    def test(self, settings: dict[str, Any]) -> Outcome:
        client = None
        try:
            client = self._client(settings)
            hello = client.admin.command("hello")
            if "setName" not in hello and hello.get("msg") != "isdbgrid":
                return Outcome(False, "This MongoDB server is standalone. Change streams need a replica set or a "
                                      "sharded cluster (a one-member replica set is enough).")
            database = self._database(client, settings)
            existing = set(database.list_collection_names())
            missing = [name for name in settings.get("tables") or [] if name not in existing]
            if missing:
                return Outcome(False, f"There is no collection {', '.join(missing)} in {database.name}.")
        except LiveError as exc:
            return Outcome(False, str(exc))
        except Exception as exc:  # noqa: BLE001 - the server's own words are the answer
            return Outcome(False, f"Could not reach MongoDB: {str(exc)[:300]}")
        finally:
            if client is not None:
                client.close()
        return Outcome(True, f"Change streams are available on {hello.get('setName') or 'this cluster'}.",
                       [f"{name}: kept current by _id" for name in settings.get("tables") or []])

    def start_position(self, settings: dict[str, Any]) -> dict[str, Any]:
        client = self._client(settings)
        try:
            hello = client.admin.command("hello")
            moment = hello.get("operationTime")
            if moment is None:
                raise LiveError("This MongoDB server reports no cluster time, so it has no change log to follow.")
            return {"start_at": [moment.time, moment.inc]}
        finally:
            client.close()

    def key_columns(self, settings: dict[str, Any], table: str) -> list[str]:
        return ["_id"]

    def snapshot(self, settings: dict[str, Any], table: str, *, chunk: int) -> Iterator[list[dict[str, Any]]]:
        client = self._client(settings)
        try:
            collection = self._database(client, settings)[table]
            rows: list[dict[str, Any]] = []
            for document in collection.find({}, sort=[("_id", 1)], batch_size=chunk):
                rows.append(_bson_plain(document))
                if len(rows) >= chunk:
                    yield rows
                    rows = []
            if rows:
                yield rows
        finally:
            client.close()

    def read(self, settings: dict[str, Any], cursor: dict[str, Any] | None, *, limit: int) -> Batch:
        from bson.timestamp import Timestamp

        cursor = cursor or {}
        options: dict[str, Any] = {"full_document": "updateLookup", "max_await_time_ms": 200}
        if cursor.get("resume"):
            options["resume_after"] = cursor["resume"]
        elif cursor.get("start_at"):
            options["start_at_operation_time"] = Timestamp(*cursor["start_at"])
        else:
            raise LiveError("This feed has no place in the change log yet; it takes one before its first copy of each table.")
        collections = list(settings.get("tables") or [])
        client = self._client(settings)
        messages: list[Message] = []
        more = False
        try:
            database = self._database(client, settings)
            pipeline = [{"$match": {"ns.coll": {"$in": collections}}}] if collections else []
            with database.watch(pipeline, **options) as stream:
                while True:
                    change = stream.try_next()
                    if change is None:
                        break
                    token = change["_id"]
                    position = position_of(str(token.get("_data") if isinstance(token, dict) else token))
                    table = change.get("ns", {}).get("coll")
                    operation = change.get("operationType")
                    key = _bson_plain(change.get("documentKey") or {})
                    if operation == "insert":
                        messages.append(Message("insert", {"row": _bson_plain(change["fullDocument"]), "old_key": key},
                                                position, table))
                    elif operation in ("update", "replace"):
                        document = change.get("fullDocument")
                        if document is None:
                            continue  # deleted since; its delete follows
                        messages.append(Message("update", {"row": _bson_plain(document), "old_key": key}, position, table))
                    elif operation == "delete":
                        messages.append(Message("delete", {"row": {}, "old_key": key}, position, table))
                    elif operation in _ENDED:
                        raise LiveError(f"A followed collection was {_ENDED[operation]}; "
                                        "start the source again to follow what is there now.")
                    if len(messages) >= limit:
                        more = True
                        break
                resume = stream.resume_token
        except LiveError:
            raise
        except Exception as exc:  # noqa: BLE001 - say what the server said
            detail = str(exc)
            if "resume" in detail.lower() and ("not found" in detail.lower() or "history" in detail.lower()):
                raise LiveError("The change log no longer goes back to where this feed stopped (the oplog moved "
                                "on). Start the feed again to take a fresh copy of each collection.") from exc
            raise LiveError(f"Reading the change stream failed: {detail[:300]}") from exc
        finally:
            client.close()
        return Batch(messages=messages, cursor={"resume": resume} if resume else cursor, more=more)
