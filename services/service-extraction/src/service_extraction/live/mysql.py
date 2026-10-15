"""Change capture from MySQL's binary log (D1, roadmap Phase 20).

Reads the row-based binary log the way a replica does (`mysql-replication`),
from a saved file and position, in micro-batches: connect, read what is
there without waiting, stop. Positions are kept only at transaction
boundaries (after a commit), so a read that resumes never starts halfway
through a transaction, and the position is saved in the same transaction as
the events: each change is saved once.

Requirements, checked and reported: binary logging on, `binlog_format =
ROW`, `binlog_row_image = FULL`, and a user with REPLICATION SLAVE and
REPLICATION CLIENT. With MySQL's default `binlog_row_metadata = MINIMAL` the
log carries values without column names, so they are named from the table's
definition as it is now; the connection test says to set FULL, which names
them in the log itself and stays right across a column added or removed while
changes are waiting.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from service_extraction.live.base import Batch, ChangeCaptureKind, LiveError, Message, Outcome, plain


def _server_id(source_id: Any) -> int:
    """A replica id of its own: two readers sharing one confuse the server."""
    return 100_000 + int(hashlib.sha1(str(source_id).encode()).hexdigest()[:7], 16) % 2_000_000_000


_UNNAMED = re.compile(r"^UNKNOWN_COL(\d+)$")


def _connect(**settings: Any):
    """PyMySQL under the names it uses now; the replication library still passes
    `db` and `passwd`, which PyMySQL warns are going."""
    import pymysql

    if "db" in settings:
        settings["database"] = settings.pop("db")
    if "passwd" in settings:
        settings["password"] = settings.pop("passwd")
    return pymysql.connect(**settings)


def _split(table: str, default_schema: str) -> tuple[str, str]:
    cleaned = table.strip().replace("`", "")
    if "." in cleaned:
        schema, _, name = cleaned.partition(".")
        return schema, name
    return default_schema, cleaned


def _quote(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


class MySqlChangeCapture(ChangeCaptureKind):
    key = "mysql_cdc"
    label = "MySQL change capture"
    description = "Follow tables through MySQL's binary log and keep each one current."
    connection_types = ("mysql",)
    verified_by = "test_live_change_capture.py"
    driver_module = "pymysqlreplication"
    driver_package = "mysql-replication"

    def _engine(self, settings: dict[str, Any]) -> Engine:
        from service_extraction.connectors import sql_database

        return sql_database.get_engine("mysql", settings["connection"])

    def _database(self, settings: dict[str, Any]) -> str:
        return str(settings["connection"].get("database") or "")

    def _connection_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        connection = settings["connection"]
        return {
            "host": connection.get("host"), "port": int(connection.get("port") or 3306),
            "user": connection.get("username"), "password": connection.get("password") or "",
        }

    def _requirements(self, engine: Engine) -> str | None:
        with engine.connect() as conn:
            log_bin, fmt, image = conn.execute(
                text("SELECT @@log_bin, @@binlog_format, @@binlog_row_image")).one()
        if str(log_bin) not in ("1", "ON"):
            return "Binary logging is off; change capture needs it (start MySQL with log_bin)."
        if str(fmt).upper() != "ROW":
            return f"binlog_format is {fmt}; change capture needs ROW (SET GLOBAL binlog_format = 'ROW')."
        if str(image).upper() != "FULL":
            return f"binlog_row_image is {image}; change capture needs FULL (SET GLOBAL binlog_row_image = 'FULL')."
        return None

    def _status(self, engine: Engine) -> tuple[str, int]:
        with engine.connect() as conn:
            for statement in ("SHOW BINARY LOG STATUS", "SHOW MASTER STATUS"):
                try:
                    row = conn.execute(text(statement)).first()
                except Exception:  # noqa: BLE001 - 8.4 renamed it; older servers lack the new name
                    continue
                if row is not None:
                    return str(row[0]), int(row[1])
        raise LiveError("This user cannot read the binary log's position; it needs REPLICATION CLIENT.")

    def test(self, settings: dict[str, Any]) -> Outcome:
        try:
            engine = self._engine(settings)
            problem = self._requirements(engine)
            if problem:
                return Outcome(False, problem)
            file, pos = self._status(engine)
            self._probe(settings, file, pos)
            details = []
            with engine.connect() as conn:
                metadata = conn.execute(text("SELECT @@binlog_row_metadata")).scalar()
            if str(metadata).upper() != "FULL":
                details.append(
                    f"binlog_row_metadata is {metadata}: columns are named from each table as it is now. "
                    "SET GLOBAL binlog_row_metadata = 'FULL' keeps the names right if a column changes "
                    "while changes are waiting."
                )
            for table in settings.get("tables") or []:
                keys = self.key_columns(settings, table)
                details.append(f"{table}: kept current by {', '.join(keys)}" if keys
                               else f"{table}: has no primary key, so only its changes are kept")
        except LiveError as exc:
            return Outcome(False, str(exc))
        except Exception as exc:  # noqa: BLE001 - the server's own words are the answer
            return Outcome(False, f"Could not reach the database: {str(exc)[:300]}")
        return Outcome(True, f"The binary log is row-based and readable (now at {file}, {pos}).", details)

    def _probe(self, settings: dict[str, Any], file: str, pos: int) -> None:
        from pymysqlreplication import BinLogStreamReader

        stream = BinLogStreamReader(
            connection_settings=self._connection_settings(settings), server_id=_server_id(settings.get("source_id")),
            blocking=False, resume_stream=True, log_file=file, log_pos=pos, enable_logging=False,
            pymysql_wrapper=_connect,
        )
        try:
            for _ in stream:
                break
        except Exception as exc:  # noqa: BLE001 - usually a missing privilege
            raise LiveError(f"This user cannot read the binary log; it needs REPLICATION SLAVE ({str(exc)[:160]}).") from exc
        finally:
            stream.close()

    def start_position(self, settings: dict[str, Any]) -> dict[str, Any]:
        engine = self._engine(settings)
        problem = self._requirements(engine)
        if problem:
            raise LiveError(problem)
        file, pos = self._status(engine)
        return {"file": file, "pos": pos}

    def key_columns(self, settings: dict[str, Any], table: str) -> list[str]:
        schema, name = _split(table, self._database(settings))
        with self._engine(settings).connect() as conn:
            exists = conn.execute(text(
                "SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA = :s AND TABLE_NAME = :t"),
                {"s": schema, "t": name}).scalar()
            if not exists:
                raise LiveError(f"There is no table {schema}.{name} in this database.")
            rows = conn.execute(text(
                "SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA = :s "
                "AND TABLE_NAME = :t AND CONSTRAINT_NAME = 'PRIMARY' ORDER BY ORDINAL_POSITION"),
                {"s": schema, "t": name}).all()
        return [str(row[0]) for row in rows]

    def snapshot(self, settings: dict[str, Any], table: str, *, chunk: int) -> Iterator[list[dict[str, Any]]]:
        schema, name = _split(table, self._database(settings))
        keys = self.key_columns(settings, table)
        order = (" ORDER BY " + ", ".join(_quote(k) for k in keys)) if keys else ""
        with self._engine(settings).connect().execution_options(stream_results=True) as conn:
            result = conn.execute(text(f"SELECT * FROM {_quote(schema)}.{_quote(name)}{order}"))
            columns = list(result.keys())
            while True:
                rows = result.fetchmany(chunk)
                if not rows:
                    break
                yield [{c: plain(v) for c, v in zip(columns, row, strict=True)} for row in rows]

    def read(self, settings: dict[str, Any], cursor: dict[str, Any] | None, *, limit: int) -> Batch:
        from pymysqlreplication import BinLogStreamReader
        from pymysqlreplication.event import XidEvent
        from pymysqlreplication.row_event import DeleteRowsEvent, UpdateRowsEvent, WriteRowsEvent

        if not cursor or "file" not in cursor:
            raise LiveError("This feed has no position in the binary log yet; it takes one before its first copy of each table.")
        database = self._database(settings)
        wanted = {_split(t, database) for t in settings.get("tables") or []}
        stream = BinLogStreamReader(
            connection_settings=self._connection_settings(settings), server_id=_server_id(settings.get("source_id")),
            blocking=False, resume_stream=True, log_file=cursor["file"], log_pos=int(cursor["pos"]),
            only_events=[WriteRowsEvent, UpdateRowsEvent, DeleteRowsEvent, XidEvent],
            only_schemas=sorted({schema for schema, _ in wanted}) or None,
            only_tables=sorted({name for _, name in wanted}) or None,
            enable_logging=False, pymysql_wrapper=_connect,
        )
        names: dict[tuple[str, str], list[str]] = {}

        def named(schema: str, table: str, values: dict[str, Any]) -> dict[str, Any]:
            if not any(_UNNAMED.match(str(key)) for key in values):
                return plain(values)
            if (schema, table) not in names:
                with self._engine(settings).connect() as conn:
                    names[(schema, table)] = [str(r[0]) for r in conn.execute(text(
                        "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = :s "
                        "AND TABLE_NAME = :t ORDER BY ORDINAL_POSITION"), {"s": schema, "t": table}).all()]
            columns = names[(schema, table)]
            out: dict[str, Any] = {}
            for key, value in values.items():
                match = _UNNAMED.match(str(key))
                index = int(match.group(1)) if match else -1
                out[columns[index] if 0 <= index < len(columns) else str(key)] = plain(value)
            return out

        messages: list[Message] = []
        pending: list[Message] = []
        saved = dict(cursor)
        more = False
        try:
            for event in stream:
                end = int(event.packet.log_pos)
                if isinstance(event, XidEvent):
                    messages.extend(pending)
                    pending = []
                    saved = {"file": stream.log_file, "pos": end}
                    if len(messages) >= limit:
                        more = True
                        break
                    continue
                if (event.schema, event.table) not in wanted:
                    continue
                table = f"{event.schema}.{event.table}"
                for index, row in enumerate(event.rows):
                    position = f"{stream.log_file}:{end}:{index}"
                    if isinstance(event, WriteRowsEvent):
                        message = Message("insert", {"row": named(event.schema, event.table, row["values"]),
                                                     "old_key": {}}, position, table)
                    elif isinstance(event, UpdateRowsEvent):
                        message = Message("update", {"row": named(event.schema, event.table, row["after_values"]),
                                                     "old_key": named(event.schema, event.table, row["before_values"])},
                                          position, table)
                    else:
                        message = Message("delete", {"row": {}, "old_key": named(event.schema, event.table, row["values"])},
                                          position, table)
                    pending.append(message)
        except Exception as exc:  # noqa: BLE001 - say what the server said
            detail = str(exc)
            if "purged" in detail.lower() or "could not find first log file" in detail.lower():
                raise LiveError(
                    f"The binary log file {cursor['file']} has been removed from the server, so the changes "
                    "since this feed last read are gone. Start the feed again to take a fresh copy of each table."
                ) from exc
            raise LiveError(f"Reading the binary log failed: {detail[:300]}") from exc
        finally:
            stream.close()
        return Batch(messages=messages, cursor=saved, more=more)
