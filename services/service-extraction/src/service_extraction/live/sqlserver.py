"""Change capture from SQL Server's CDC tables (D1, roadmap Phase 20).

SQL Server's change data capture copies each change to a change table that
`cdc.fn_cdc_get_all_changes_<instance>` reads between two log sequence
numbers. Pipewright reads each followed table from the LSN after the one it
saved, up to a whole number of transactions (every row of one commit shares
its `__$start_lsn`), and saves the LSN with the events: each change is saved
once.

Change capture has to be turned on in SQL Server by someone allowed to: for
the database (`sys.sp_cdc_enable_db`) and for each table
(`sys.sp_cdc_enable_table`), with SQL Server Agent running to fill the change
tables. Pipewright does not change a database's settings; the test names the
exact statements. Connected with `pymssql`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from service_extraction.live.base import (
    Batch, ChangeCaptureKind, LiveError, LiveField, Message, Outcome, host_of, plain, position_of,
)

_OPERATIONS = {1: "delete", 2: "insert", 4: "update"}
_INSTANCE_SAFE = re.compile(r"^[A-Za-z0-9_]+$")


def _split(table: str) -> tuple[str, str]:
    cleaned = table.strip().replace("[", "").replace("]", "")
    if "." in cleaned:
        schema, _, name = cleaned.partition(".")
        return schema, name
    return "dbo", cleaned


def _quoted(table: str) -> str:
    schema, name = _split(table)
    return f"[{schema.replace(']', ']]')}].[{name.replace(']', ']]')}]"


class SqlServerChangeCapture(ChangeCaptureKind):
    key = "sqlserver_cdc"
    label = "SQL Server change capture"
    description = "Follow tables through SQL Server's change data capture and keep each one current."
    fields = (
        LiveField("host", "Server", placeholder="sql.internal"),
        LiveField("port", "Port", kind="number", required=False, default=1433),
        LiveField("database", "Database"),
        LiveField("username", "Username"),
        LiveField("password", "Password", kind="secret"),
    )
    verified_by = "test_live_change_capture.py"
    driver_module = "pymssql"
    driver_package = "pymssql"

    def hosts(self, settings: dict[str, Any]) -> list[str]:
        return [h for h in (host_of(settings.get("host")),) if h]

    def _connect(self, settings: dict[str, Any]):
        import pymssql

        try:
            return pymssql.connect(
                server=settings["host"], port=int(settings.get("port") or 1433), user=settings["username"],
                password=settings["password"], database=settings["database"], login_timeout=10, timeout=120,
            )
        except pymssql.Error as exc:
            raise LiveError(f"Could not reach SQL Server: {str(exc)[:300]}") from exc

    def _instance(self, cursor, table: str) -> tuple[str, bytes | None]:
        cursor.execute(
            "SELECT ct.capture_instance, ct.start_lsn FROM cdc.change_tables ct WHERE ct.source_object_id = OBJECT_ID(%s)",
            (_quoted(table),),
        )
        row = cursor.fetchone()
        if row is None:
            schema, name = _split(table)
            raise LiveError(
                f"Change capture is not on for {schema}.{name}. Someone allowed to can turn it on with: "
                f"EXEC sys.sp_cdc_enable_table @source_schema = N'{schema}', @source_name = N'{name}', @role_name = NULL;"
            )
        instance = str(row[0])
        if not _INSTANCE_SAFE.match(instance):
            raise LiveError(f"The capture instance {instance!r} has a name Pipewright will not put in a query.")
        return instance, row[1]

    def test(self, settings: dict[str, Any]) -> Outcome:
        try:
            conn = self._connect(settings)
        except LiveError as exc:
            return Outcome(False, str(exc))
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT is_cdc_enabled FROM sys.databases WHERE name = DB_NAME()")
            row = cursor.fetchone()
            if not row or not row[0]:
                return Outcome(False, "Change capture is off for this database. Someone allowed to can turn it on "
                                      "with: EXEC sys.sp_cdc_enable_db;")
            details: list[str] = []
            try:
                cursor.execute("SELECT status_desc FROM sys.dm_server_services WHERE servicename LIKE 'SQL Server Agent%'")
                agent = cursor.fetchone()
                if agent and agent[0] != "Running":
                    return Outcome(False, "SQL Server Agent is not running, so the change tables are not being filled.")
            except Exception:  # noqa: BLE001 - needs VIEW SERVER STATE, which a reader may lack
                details.append("Could not see whether SQL Server Agent is running; it must be, to fill the change tables.")
            for table in settings.get("tables") or []:
                self._instance(cursor, table)
                keys = self.key_columns(settings, table, conn=conn)
                details.append(f"{table}: kept current by {', '.join(keys)}" if keys
                               else f"{table}: has no primary key, so only its changes are kept")
        except LiveError as exc:
            return Outcome(False, str(exc))
        except Exception as exc:  # noqa: BLE001 - the server's own words are the answer
            return Outcome(False, f"SQL Server refused: {str(exc)[:300]}")
        finally:
            conn.close()
        return Outcome(True, "Change capture is on and its tables can be read.", details)

    def start_position(self, settings: dict[str, Any]) -> dict[str, Any]:
        conn = self._connect(settings)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT sys.fn_cdc_get_max_lsn()")
            now = cursor.fetchone()[0]
            for table in settings.get("tables") or []:
                self._instance(cursor, table)
            return {"lsn": {table: (now.hex() if now else None) for table in settings.get("tables") or []}}
        finally:
            conn.close()

    def key_columns(self, settings: dict[str, Any], table: str, *, conn=None) -> list[str]:
        own = conn is None
        conn = conn or self._connect(settings)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT OBJECT_ID(%s)", (_quoted(table),))
            found = cursor.fetchone()
            if not found or found[0] is None:
                schema, name = _split(table)
                raise LiveError(f"There is no table {schema}.{name} in this database.")
            cursor.execute(
                "SELECT c.name FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id = i.object_id "
                "AND ic.index_id = i.index_id JOIN sys.columns c ON c.object_id = ic.object_id "
                "AND c.column_id = ic.column_id WHERE i.is_primary_key = 1 AND i.object_id = %s ORDER BY ic.key_ordinal",
                (found[0],),
            )
            return [str(row[0]) for row in cursor.fetchall()]
        finally:
            if own:
                conn.close()

    def snapshot(self, settings: dict[str, Any], table: str, *, chunk: int) -> Iterator[list[dict[str, Any]]]:
        conn = self._connect(settings)
        try:
            keys = self.key_columns(settings, table, conn=conn)
            order = (" ORDER BY " + ", ".join(f"[{k.replace(']', ']]')}]" for k in keys)) if keys else ""
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM {_quoted(table)}{order}")
            columns = [d[0] for d in cursor.description]
            while True:
                rows = cursor.fetchmany(chunk)
                if not rows:
                    break
                yield [{c: plain(v) for c, v in zip(columns, row, strict=True)} for row in rows]
        finally:
            conn.close()

    def read(self, settings: dict[str, Any], cursor: dict[str, Any] | None, *, limit: int) -> Batch:
        saved = dict((cursor or {}).get("lsn") or {})
        conn = self._connect(settings)
        messages: list[Message] = []
        more = False
        try:
            db = conn.cursor()
            db.execute("SELECT sys.fn_cdc_get_max_lsn()")
            newest = db.fetchone()[0]
            for table in settings.get("tables") or []:
                if newest is None or len(messages) >= limit:
                    more = more or newest is not None
                    continue
                instance, started = self._instance(db, table)
                db.execute("SELECT sys.fn_cdc_get_min_lsn(%s)", (instance,))
                oldest = db.fetchone()[0]
                last = bytes.fromhex(saved[table]) if saved.get(table) else None
                if last is not None and started is not None and last >= started and oldest and last < oldest:
                    raise LiveError(
                        f"SQL Server has cleaned up the changes to {table} since this feed last read them. "
                        "Start the feed again to take a fresh copy of each table."
                    )
                if last is None or (oldest and last < oldest):
                    low = oldest
                else:
                    db.execute("SELECT sys.fn_cdc_increment_lsn(%s)", (last,))
                    low = db.fetchone()[0]
                if low is None or low > newest:
                    continue
                room = limit - len(messages)
                # A whole number of transactions: every row of one commit shares its start LSN.
                db.execute(
                    f"SELECT TOP ({int(room) + 1}) __$start_lsn, COUNT(*) FROM cdc.[{instance}_CT] "
                    "WHERE __$start_lsn >= %s AND __$start_lsn <= %s AND __$operation <> 3 "
                    "GROUP BY __$start_lsn ORDER BY __$start_lsn",
                    (low, newest),
                )
                groups = db.fetchall()
                if not groups:
                    saved[table] = newest.hex()
                    continue
                upto, taken = groups[0][0], 0
                for lsn, count in groups:
                    if taken and taken + int(count) > room:
                        more = True
                        break
                    upto, taken = lsn, taken + int(count)
                if len(groups) > room:
                    more = True
                db.execute(
                    f"SELECT * FROM cdc.fn_cdc_get_all_changes_{instance}(%s, %s, N'all') "
                    "ORDER BY __$start_lsn, __$seqval, __$operation",
                    (low, upto),
                )
                columns = [d[0] for d in db.description]
                for row in db.fetchall():
                    record = dict(zip(columns, row, strict=True))
                    operation = _OPERATIONS.get(int(record["__$operation"]))
                    if operation is None:
                        continue
                    values = {k: plain(v) for k, v in record.items() if not str(k).startswith("__$")}
                    position = position_of(
                        f"{table}:{record['__$start_lsn'].hex()}:{record['__$seqval'].hex()}:{record['__$operation']}")
                    if operation == "delete":
                        messages.append(Message("delete", {"row": {}, "old_key": values}, position, table))
                    else:
                        messages.append(Message(operation, {"row": values, "old_key": {}}, position, table))
                saved[table] = upto.hex()
        finally:
            conn.close()
        return Batch(messages=messages, cursor={"lsn": saved}, more=more)
