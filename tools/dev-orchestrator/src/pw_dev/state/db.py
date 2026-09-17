"""Transactional run state in SQLite, plus the append-only event log.

Three things make this recoverable rather than merely persistent:

* every state change and its event are written in the *same* transaction, so the
  log can never disagree with the row it describes;
* the controller holds an ownership lock per run, with the pid recorded, so a
  second controller cannot dispatch duplicate workers -- and a lock whose pid is
  gone can be reclaimed rather than leaving the run wedged;
* tasks carry leases with heartbeats, so a crash mid-task is distinguishable
  from a task that is still running. A lease that expired while its process is
  gone means the task must be reconciled, not assumed untouched.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..errors import StateError
from ..util.hashing import digest_bytes
from ..util.jsonio import utc_now, write_bytes_atomic
from .machine import RunState, TaskState, transition_allowed

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id            TEXT PRIMARY KEY,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    state             TEXT NOT NULL,
    state_detail      TEXT,
    brain             TEXT NOT NULL,
    phase_id          TEXT,
    base_commit       TEXT,
    spec_digest       TEXT,
    candidate_fingerprint TEXT,
    approved_fingerprint  TEXT,
    config_digest     TEXT NOT NULL,
    config_json       TEXT NOT NULL,
    publication_mode  TEXT NOT NULL,
    deadline_epoch    REAL,
    plan_only         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS run_locks (
    run_id      TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
    owner_pid   INTEGER NOT NULL,
    owner_token TEXT NOT NULL,
    hostname    TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    run_id        TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    task_id       TEXT NOT NULL,
    title         TEXT NOT NULL,
    role          TEXT NOT NULL,
    state         TEXT NOT NULL,
    state_detail  TEXT,
    depends_on    TEXT NOT NULL,
    allowed_paths TEXT NOT NULL,
    forbidden_paths TEXT NOT NULL,
    exclusive_resources TEXT NOT NULL,
    verification_ids TEXT NOT NULL,
    repair_rounds INTEGER NOT NULL DEFAULT 0,
    attempt       INTEGER NOT NULL DEFAULT 0,
    worktree      TEXT,
    patch_digest  TEXT,
    report_digest TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (run_id, task_id)
);

CREATE TABLE IF NOT EXISTS leases (
    run_id      TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    lease_token TEXT NOT NULL,
    owner_pid   INTEGER NOT NULL,
    child_pid   INTEGER,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at_epoch REAL NOT NULL,
    PRIMARY KEY (run_id, task_id)
);

CREATE TABLE IF NOT EXISTS resource_locks (
    run_id      TEXT NOT NULL,
    resource    TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    PRIMARY KEY (run_id, resource)
);

CREATE TABLE IF NOT EXISTS events (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    task_id    TEXT,
    at         TEXT NOT NULL,
    kind       TEXT NOT NULL,
    message    TEXT NOT NULL,
    payload    TEXT
);

CREATE TABLE IF NOT EXISTS artifacts (
    run_id     TEXT NOT NULL,
    digest     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    task_id    TEXT,
    path       TEXT NOT NULL,
    bytes      INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, digest, kind)
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    task_id     TEXT,
    verification_id TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    candidate_fingerprint TEXT NOT NULL,
    spec_digest TEXT NOT NULL,
    environment_digest TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    document    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    task_id    TEXT,
    role       TEXT NOT NULL,
    provider   TEXT NOT NULL,
    model      TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd   REAL,
    cost_known INTEGER NOT NULL,
    at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS events_run_idx ON events(run_id, seq);
CREATE INDEX IF NOT EXISTS evidence_run_idx ON evidence(run_id, verification_id);
CREATE INDEX IF NOT EXISTS artifacts_run_idx ON artifacts(run_id, kind);
"""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class RunStore:
    """All durable controller state. Nothing else writes to this database."""

    def __init__(self, db_path: Path, artifacts_root: Path) -> None:
        self.db_path = Path(db_path)
        self.artifacts_root = Path(artifacts_root)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        # Worker threads write task state and events while the controller thread
        # reads them, so the connection is shared and every access is serialized
        # by `self._lock`. `transaction()` still uses BEGIN IMMEDIATE, so a
        # second *process* is excluded by SQLite itself; the lock only orders
        # threads inside this one.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self.db_path, isolation_level=None, timeout=30.0, check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        row = self._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),)
            )
            return
        found = int(row["value"])
        if found > SCHEMA_VERSION:
            raise StateError(
                f"{self.db_path} was written by a newer pw-dev (schema {found}, "
                f"this build understands {SCHEMA_VERSION}). Refusing to read it."
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """A locked read. Reads share the connection with worker-thread writes."""
        with self._lock:
            return list(self._conn.execute(sql, params))

    def _query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def __enter__(self) -> "RunStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One writer, all-or-nothing.

        State rows and their events are written inside the same block, which is
        what makes the event log an account of what happened rather than a
        best-effort narration alongside it.
        """
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    # --------------------------------------------------------------- run rows
    def create_run(
        self,
        *,
        brain: str,
        config_snapshot: dict,
        publication_mode: str,
        deadline_epoch: float | None,
        plan_only: bool = False,
        run_id: str | None = None,
    ) -> str:
        run_id = run_id or f"run-{utc_now()[:10].replace('-', '')}-{uuid.uuid4().hex[:8]}"
        payload = _json(config_snapshot)
        now = utc_now()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO runs(run_id, created_at, updated_at, state, state_detail, brain,"
                " config_digest, config_json, publication_mode, deadline_epoch, plan_only)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, now, now, RunState.DISCOVER.value,
                    "capturing baseline", brain,
                    digest_bytes(payload.encode()), payload, publication_mode,
                    deadline_epoch, int(plan_only),
                ),
            )
            self._append_event(conn, run_id, None, "run.created", f"run created ({brain} brain)", {
                "publication_mode": publication_mode, "plan_only": plan_only,
            })
        return run_id

    def get_run(self, run_id: str) -> sqlite3.Row:
        row = self._query_one("SELECT * FROM runs WHERE run_id=?", (run_id,))
        if row is None:
            raise StateError(f"no such run: {run_id}")
        return row

    def list_runs(self, limit: int = 50) -> list[sqlite3.Row]:
        return self._query("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))

    def set_run_state(
        self, run_id: str, state: RunState, detail: str, *, payload: dict | None = None,
        force: bool = False,
    ) -> None:
        """Move a run, refusing transitions the machine does not allow."""
        with self.transaction() as conn:
            row = conn.execute("SELECT state FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise StateError(f"no such run: {run_id}")
            current = RunState(row["state"])
            if current is not state and not force and not transition_allowed(current, state):
                raise StateError(f"{run_id}: {current.value} -> {state.value} is not a legal transition")
            conn.execute(
                "UPDATE runs SET state=?, state_detail=?, updated_at=? WHERE run_id=?",
                (state.value, detail, utc_now(), run_id),
            )
            self._append_event(
                conn, run_id, None, "run.state",
                f"{current.value} -> {state.value}: {detail}",
                {"from": current.value, "to": state.value, **(payload or {})},
            )

    def update_run_fields(self, run_id: str, **fields: Any) -> None:
        allowed = {
            "phase_id", "base_commit", "spec_digest", "candidate_fingerprint",
            "approved_fingerprint", "deadline_epoch", "plan_only", "publication_mode",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise StateError(f"run fields not updatable: {sorted(unknown)}")
        if not fields:
            return
        assignments = ", ".join(f"{name}=?" for name in fields)
        with self.transaction() as conn:
            conn.execute(
                f"UPDATE runs SET {assignments}, updated_at=? WHERE run_id=?",
                (*fields.values(), utc_now(), run_id),
            )

    # ------------------------------------------------------- ownership locking
    def acquire_run_lock(
        self, run_id: str, *, steal_dead: bool = True, existing_token: str | None = None,
    ) -> str:
        """Take exclusive control of a run.

        A lock left by a crashed controller is reclaimed only when its pid is
        genuinely gone. A live pid always wins, which is what stops two
        controllers dispatching the same task twice.

        Re-entrancy is by *token*, not by pid: two controllers inside one process
        are still two controllers, and letting the second inherit the first's
        lock because they share a pid would produce exactly the duplicate
        dispatch this lock exists to prevent.
        """
        token = uuid.uuid4().hex
        now = utc_now()
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM run_locks WHERE run_id=?", (run_id,)).fetchone()
            if row is not None:
                holder = int(row["owner_pid"])
                same_host = row["hostname"] == os.uname().nodename
                if existing_token is not None and row["owner_token"] == existing_token:
                    conn.execute(
                        "UPDATE run_locks SET heartbeat_at=? WHERE run_id=?", (now, run_id)
                    )
                    return str(row["owner_token"])
                alive = same_host and _pid_alive(holder)
                if alive or not steal_dead:
                    raise StateError(
                        f"run {run_id} is owned by pid {holder} on {row['hostname']} "
                        f"(locked at {row['acquired_at']}). Stop it, or wait for it to finish."
                    )
                conn.execute("DELETE FROM run_locks WHERE run_id=?", (run_id,))
                self._append_event(
                    conn, run_id, None, "run.lock.reclaimed",
                    f"reclaimed the lock from pid {holder}, which is no longer running",
                    {"previous_pid": holder},
                )
            conn.execute(
                "INSERT INTO run_locks(run_id, owner_pid, owner_token, hostname, acquired_at,"
                " heartbeat_at) VALUES(?,?,?,?,?,?)",
                (run_id, os.getpid(), token, os.uname().nodename, now, now),
            )
        return token

    def heartbeat_run_lock(self, run_id: str, token: str) -> None:
        with self.transaction() as conn:
            updated = conn.execute(
                "UPDATE run_locks SET heartbeat_at=? WHERE run_id=? AND owner_token=?",
                (utc_now(), run_id, token),
            ).rowcount
        if not updated:
            raise StateError(f"lost the controller lock on {run_id}")

    def release_run_lock(self, run_id: str, token: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM run_locks WHERE run_id=? AND owner_token=?", (run_id, token)
            )

    def run_lock_holder(self, run_id: str) -> sqlite3.Row | None:
        return self._query_one("SELECT * FROM run_locks WHERE run_id=?", (run_id,))

    # -------------------------------------------------------------- task rows
    def create_tasks(self, run_id: str, tasks: list[dict]) -> None:
        now = utc_now()
        with self.transaction() as conn:
            for task in tasks:
                conn.execute(
                    "INSERT OR REPLACE INTO tasks(run_id, task_id, title, role, state,"
                    " state_detail, depends_on, allowed_paths, forbidden_paths,"
                    " exclusive_resources, verification_ids, created_at, updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        run_id, task["id"], task["title"], task["role"],
                        TaskState.PENDING.value, "waiting on dependencies",
                        _json(task.get("depends_on", [])),
                        _json(task.get("allowed_paths", [])),
                        _json(task.get("forbidden_paths", [])),
                        _json(task.get("exclusive_resources", [])),
                        _json(task.get("verification_ids", [])),
                        now, now,
                    ),
                )
            self._append_event(
                conn, run_id, None, "tasks.created",
                f"{len(tasks)} tasks registered", {"task_ids": [t["id"] for t in tasks]},
            )

    def get_tasks(self, run_id: str) -> list[sqlite3.Row]:
        return self._query("SELECT * FROM tasks WHERE run_id=? ORDER BY task_id", (run_id,))

    def get_task(self, run_id: str, task_id: str) -> sqlite3.Row:
        row = self._query_one(
            "SELECT * FROM tasks WHERE run_id=? AND task_id=?", (run_id, task_id)
        )
        if row is None:
            raise StateError(f"no such task {task_id} in {run_id}")
        return row

    def set_task_state(
        self, run_id: str, task_id: str, state: TaskState, detail: str,
        *, payload: dict | None = None, **fields: Any,
    ) -> None:
        allowed = {"worktree", "patch_digest", "report_digest", "repair_rounds", "attempt"}
        unknown = set(fields) - allowed
        if unknown:
            raise StateError(f"task fields not updatable: {sorted(unknown)}")
        assignments = "".join(f", {name}=?" for name in fields)
        with self.transaction() as conn:
            conn.execute(
                f"UPDATE tasks SET state=?, state_detail=?, updated_at=?{assignments}"
                " WHERE run_id=? AND task_id=?",
                (state.value, detail, utc_now(), *fields.values(), run_id, task_id),
            )
            self._append_event(
                conn, run_id, task_id, "task.state", f"{task_id} -> {state.value}: {detail}",
                {"to": state.value, **(payload or {})},
            )

    def bump_repair_round(self, run_id: str, task_id: str) -> int:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE tasks SET repair_rounds = repair_rounds + 1, updated_at=?"
                " WHERE run_id=? AND task_id=?", (utc_now(), run_id, task_id),
            )
            row = conn.execute(
                "SELECT repair_rounds FROM tasks WHERE run_id=? AND task_id=?", (run_id, task_id)
            ).fetchone()
        return int(row["repair_rounds"])

    # ----------------------------------------------------------------- leases
    def acquire_lease(
        self, run_id: str, task_id: str, *, ttl_seconds: float, child_pid: int | None = None
    ) -> str:
        """Claim a task. A live lease on the same task is refused."""
        import time

        token = uuid.uuid4().hex
        now = utc_now()
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM leases WHERE run_id=? AND task_id=?", (run_id, task_id)
            ).fetchone()
            if row is not None:
                still_valid = row["expires_at_epoch"] > time.time() and _pid_alive(int(row["owner_pid"]))
                if still_valid:
                    raise StateError(
                        f"{task_id} already leased by pid {row['owner_pid']} until "
                        f"{row['expires_at_epoch']}"
                    )
                conn.execute("DELETE FROM leases WHERE run_id=? AND task_id=?", (run_id, task_id))
                self._append_event(
                    conn, run_id, task_id, "task.lease.expired",
                    f"reclaimed an expired lease from pid {row['owner_pid']}",
                    {"previous_pid": row["owner_pid"], "child_pid": row["child_pid"]},
                )
            conn.execute(
                "INSERT INTO leases(run_id, task_id, lease_token, owner_pid, child_pid,"
                " acquired_at, heartbeat_at, expires_at_epoch) VALUES(?,?,?,?,?,?,?,?)",
                (run_id, task_id, token, os.getpid(), child_pid, now, now, time.time() + ttl_seconds),
            )
        return token

    def heartbeat_lease(self, run_id: str, task_id: str, token: str, *, ttl_seconds: float,
                        child_pid: int | None = None) -> None:
        import time

        with self.transaction() as conn:
            updated = conn.execute(
                "UPDATE leases SET heartbeat_at=?, expires_at_epoch=?, child_pid=COALESCE(?, child_pid)"
                " WHERE run_id=? AND task_id=? AND lease_token=?",
                (utc_now(), time.time() + ttl_seconds, child_pid, run_id, task_id, token),
            ).rowcount
        if not updated:
            raise StateError(f"lost the lease on {task_id}")

    def release_lease(self, run_id: str, task_id: str, token: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM leases WHERE run_id=? AND task_id=? AND lease_token=?",
                (run_id, task_id, token),
            )

    def stale_leases(self, run_id: str) -> list[sqlite3.Row]:
        """Leases whose owner is gone. Each one needs reconciliation, not a retry."""
        import time

        rows = self._query("SELECT * FROM leases WHERE run_id=?", (run_id,))
        now = time.time()
        return [r for r in rows if r["expires_at_epoch"] <= now or not _pid_alive(int(r["owner_pid"]))]

    # -------------------------------------------------------- resource locks
    def acquire_resource(self, run_id: str, resource: str, task_id: str) -> bool:
        """Serialize a named shared resource. Returns False when already held."""
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT task_id FROM resource_locks WHERE run_id=? AND resource=?",
                (run_id, resource),
            ).fetchone()
            if row is not None:
                return row["task_id"] == task_id
            conn.execute(
                "INSERT INTO resource_locks(run_id, resource, task_id, acquired_at)"
                " VALUES(?,?,?,?)", (run_id, resource, task_id, utc_now()),
            )
        return True

    def release_resource(self, run_id: str, resource: str, task_id: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM resource_locks WHERE run_id=? AND resource=? AND task_id=?",
                (run_id, resource, task_id),
            )

    def held_resources(self, run_id: str) -> dict[str, str]:
        return {
            r["resource"]: r["task_id"]
            for r in self._query(
                "SELECT resource, task_id FROM resource_locks WHERE run_id=?", (run_id,)
            )
        }

    # ------------------------------------------------------------- event log
    def _append_event(self, conn: sqlite3.Connection, run_id: str, task_id: str | None,
                      kind: str, message: str, payload: dict | None = None) -> None:
        from ..util.redact import redact

        conn.execute(
            "INSERT INTO events(run_id, task_id, at, kind, message, payload)"
            " VALUES(?,?,?,?,?,?)",
            (run_id, task_id, utc_now(), kind, redact(message),
             _json(payload) if payload is not None else None),
        )

    def event(self, run_id: str, kind: str, message: str, *, task_id: str | None = None,
              payload: dict | None = None) -> None:
        with self.transaction() as conn:
            self._append_event(conn, run_id, task_id, kind, message, payload)

    def events(self, run_id: str, *, since: int = 0, limit: int = 1000) -> list[sqlite3.Row]:
        return self._query(
            "SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
            (run_id, since, limit),
        )

    # ------------------------------------------------------------- artifacts
    def put_artifact(self, run_id: str, kind: str, data: bytes, *, task_id: str | None = None,
                     suffix: str = ".json") -> str:
        """Store a large output by content hash and record where it went."""
        digest = digest_bytes(data)
        directory = self.artifacts_root / run_id / kind
        path = directory / f"{digest[:16]}{suffix}"
        write_bytes_atomic(path, data)
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO artifacts(run_id, digest, kind, task_id, path, bytes,"
                " created_at) VALUES(?,?,?,?,?,?,?)",
                (run_id, digest, kind, task_id, str(path), len(data), utc_now()),
            )
        return digest

    def put_json_artifact(self, run_id: str, kind: str, document: Any, *,
                          task_id: str | None = None) -> str:
        return self.put_artifact(
            run_id, kind, (json.dumps(document, indent=2, sort_keys=True) + "\n").encode(),
            task_id=task_id,
        )

    def artifact_path(self, run_id: str, kind: str, digest: str) -> Path:
        row = self._query_one(
            "SELECT path FROM artifacts WHERE run_id=? AND kind=? AND digest=?",
            (run_id, kind, digest),
        )
        if row is None:
            raise StateError(f"no {kind} artifact {digest[:12]} for {run_id}")
        return Path(row["path"])

    def load_json_artifact(self, run_id: str, kind: str, digest: str) -> Any:
        return json.loads(self.artifact_path(run_id, kind, digest).read_text(encoding="utf-8"))

    def latest_artifact(self, run_id: str, kind: str) -> sqlite3.Row | None:
        return self._query_one(
            "SELECT * FROM artifacts WHERE run_id=? AND kind=? ORDER BY created_at DESC LIMIT 1",
            (run_id, kind),
        )

    # -------------------------------------------------------------- evidence
    def record_evidence(self, document: dict) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO evidence(evidence_id, run_id, task_id, verification_id,"
                " outcome, candidate_fingerprint, spec_digest, environment_digest, created_at,"
                " document) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    document["evidence_id"], document["run_id"], document["task_id"],
                    document["verification_id"], document["outcome"],
                    document["candidate_fingerprint"], document["spec_digest"],
                    document["environment_digest"], document["started_at"], _json(document),
                ),
            )
            self._append_event(
                conn, document["run_id"], document["task_id"], "verification",
                f"{document['verification_id']}: {document['outcome']}",
                {"evidence_id": document["evidence_id"], "outcome": document["outcome"]},
            )

    def evidence_for(self, run_id: str, *, candidate_fingerprint: str | None = None) -> list[dict]:
        if candidate_fingerprint is None:
            rows = self._query(
                "SELECT document FROM evidence WHERE run_id=? ORDER BY created_at", (run_id,)
            )
        else:
            rows = self._query(
                "SELECT document FROM evidence WHERE run_id=? AND candidate_fingerprint=?"
                " ORDER BY created_at", (run_id, candidate_fingerprint),
            )
        return [json.loads(r["document"]) for r in rows]

    # ----------------------------------------------------------------- usage
    def record_usage(self, run_id: str, *, role: str, provider: str, model: str | None,
                     input_tokens: int | None, output_tokens: int | None,
                     cost_usd: float | None, task_id: str | None = None) -> None:
        """Record what the provider actually reported.

        `cost_known` is stored separately from `cost_usd` so a run whose provider
        supplies no dollar figure reports unknown rather than zero. Zero is a
        number; unknown is the truth.
        """
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO usage(run_id, task_id, role, provider, model, input_tokens,"
                " output_tokens, cost_usd, cost_known, at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (run_id, task_id, role, provider, model, input_tokens, output_tokens,
                 cost_usd, int(cost_usd is not None), utc_now()),
            )

    def usage_summary(self, run_id: str) -> dict:
        rows = self._query("SELECT * FROM usage WHERE run_id=?", (run_id,))
        known = [r for r in rows if r["cost_known"]]
        return {
            "calls": len(rows),
            "input_tokens": sum(r["input_tokens"] or 0 for r in rows),
            "output_tokens": sum(r["output_tokens"] or 0 for r in rows),
            "cost_usd_known": round(sum(r["cost_usd"] or 0.0 for r in known), 6) if known else None,
            "calls_without_cost": len(rows) - len(known),
            "by_provider": sorted({r["provider"] for r in rows}),
        }


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
