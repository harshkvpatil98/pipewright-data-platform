"""The audit log in words (adoption-readiness A5).

The middleware records the request, method and path, because that is the
honest unit: it captures attempts that were refused as well as ones that
worked. People reading the log want the other half: "Ann ran a recipe",
"Bo deleted the dashboard Weekly sales". This module turns a recorded
request into that phrase, and looks up the name of the thing it touched
while the thing still exists. The stored row is unchanged, so entries
written before this module read the same way.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared_python.db import Base

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

# Routes whose meaning is not "verb the last noun", in the order they are tried.
# Paths are skeletons: /api/v1 and the leading /projects/{id} removed.
_RULES: list[tuple[str, str, str]] = [
    ("DELETE", r"", "deleted the project"),
    ("PATCH", r"", "changed the project's settings"),
    ("POST", r"/projects", "created a project"),
    ("POST", r"/projects/demo", "made the demo project"),
    ("POST", r"/pipelines/{id}/run", "ran a recipe"),
    ("POST", r"/extraction/jobs/{id}/run", "ran an import"),
    ("POST", r"/extraction/jobs/{id}/reset-watermark", "started an import over from the beginning"),
    ("POST", r"/extraction/connections/{id}/test", "checked a source connection"),
    ("POST", r"/workflows/{id}/run", "ran a workflow"),
    ("POST", r"/workflows/{id}/backfill", "ran a workflow for past dates"),
    ("POST", r"/workflow-runs/{id}/cancel", "cancelled a workflow run"),
    ("POST", r"/workflow-runs/{id}/resume", "picked up a workflow run from where it failed"),
    ("POST", r"/reports/{id}/run", "sent a report"),
    ("POST", r"/schedules/{id}/toggle", "paused or resumed a schedule"),
    ("POST", r"/schedules/{id}/trigger-now", "ran a schedule straight away"),
    ("POST", r"/workbench/run", "ran SQL in the workbench"),
    ("POST", r"/workbench/notebooks/{id}/run", "ran a notebook"),
    ("POST", r"/tests/saved/{id}/run", "ran a saved comparison"),
    ("POST", r"/datasets/{id}/tests/{id}", "compared two datasets"),
    ("POST", r"/datasets/{id}/data-quality/check", "checked a dataset"),
    ("POST", r"/datasets/{id}/data-quality/evaluate", "checked a dataset"),
    ("POST", r"/datasets/{id}/metrics/capture", "recorded a dataset's health"),
    ("POST", r"/datasets/{id}/deliver", "delivered a dataset"),
    ("POST", r"/datasets/{id}/publish/postgres", "delivered a dataset to PostgreSQL"),
    ("POST", r"/datasets/{id}/publish/power-bi", "sent a dataset to Power BI"),
    ("POST", r"/datasets/{id}/publish/tableau", "sent a dataset to Tableau"),
    ("POST", r"/datasets/{id}/versions/{id}/rollback", "restored an earlier version of a dataset"),
    ("POST", r"/history/{id}/{id}/restore", "restored an earlier version"),
    ("POST", r"/datasets/{id}/pipelines", "created a recipe"),
    ("POST", r"/datasets/{id}/glossary-terms", "tagged a dataset with a glossary term"),
    ("DELETE", r"/datasets/{id}/glossary-terms/{id}", "removed a glossary term from a dataset"),
    ("POST", r"/datasets/upload", "uploaded a file"),
    ("POST", r"/datasets/uploads", "started uploading a file"),
    ("PUT", r"/datasets/uploads/{id}/chunks/{id}", "uploaded part of a file"),
    ("POST", r"/datasets/uploads/{id}/complete", "finished uploading a file"),
    ("DELETE", r"/datasets/uploads/{id}", "cancelled an upload"),
    ("POST", r"/samples/{id}", "added sample data"),
    ("POST", r"/runs/{id}/replay", "replayed a run"),
    ("POST", r"/runs/sample", "started a sample run"),
    ("POST", r"/dashboards/{id}/share", "shared a dashboard by link"),
    ("DELETE", r"/dashboards/{id}/share", "stopped sharing a dashboard"),
    ("POST", r"/pipelines/{id}/suggest", "suggested a change to a recipe"),
    ("POST", r"/pipelines/{id}/shared/discard", "discarded a recipe's unsaved changes"),
    ("POST", r"/discussion/{id}/reopen", "opened a comment thread again"),
    ("PUT", r"/datasets/{id}/contract", "wrote or changed a dataset's contract"),
    ("DELETE", r"/datasets/{id}/contract", "removed a dataset's contract"),
    ("POST", r"/datasets/{id}/contract/check", "checked a dataset against its contract"),
    ("POST", r"/datasets/{id}/contract/follow", "followed a dataset's contract"),
    ("DELETE", r"/datasets/{id}/contract/follow", "stopped following a dataset's contract"),
    ("POST", r"/datasets/{id}/metric-alerts", "added an alert on a dataset's measure"),
    ("PATCH", r"/datasets/{id}/metric-alerts/{id}", "changed an alert on a dataset's measure"),
    ("DELETE", r"/datasets/{id}/metric-alerts/{id}", "removed an alert on a dataset's measure"),
    ("POST", r"/dashboards/{id}/embeds", "made a link to show a dashboard on another site"),
    ("DELETE", r"/dashboards/{id}/embeds/{id}", "turned off a dashboard shown on another site"),
    ("POST", r"/changes", "asked for a change to be approved"),
    ("POST", r"/changes/{id}/approve", "approved a change request"),
    ("POST", r"/changes/{id}/reject", "turned down a change request"),
    ("POST", r"/changes/{id}/withdraw", "withdrew a change request"),
    ("POST", r"/incidents/{id}/acknowledge", "acknowledged an incident"),
    ("POST", r"/incidents/{id}/assign", "assigned an incident"),
    ("POST", r"/incidents/{id}/comments", "commented on an incident"),
    ("POST", r"/incidents/{id}/reopen", "reopened an incident"),
    ("POST", r"/incidents/{id}/resolve", "resolved an incident"),
    ("POST", r"/schema-drift/events/{id}/acknowledge", "marked a schema change as seen"),
    ("POST", r"/connectors/watch", "checked sources for schema changes"),
    ("POST", r"/freshness/check", "checked how fresh the data is"),
    ("POST", r"/discussion", "commented"),
    ("POST", r"/discussion/{id}/resolve", "resolved a comment"),
    ("POST", r"/promote", "copied something to another project"),
    ("POST", r"/retention", "set how long data is kept"),
    ("POST", r"/retention/run", "removed data past its keep-until date"),
    ("POST", r"/erasures", "asked for a person's data to be erased"),
    ("POST", r"/streams/{id}/poll", "checked a live feed for new data"),
    ("POST", r"/streams/{id}/materialise", "saved a live feed's data to its datasets"),
    ("POST", r"/streams/try", "tried a live feed's settings"),
    ("POST", r"/streams/{id}/test", "checked a live feed"),
    ("POST", r"/streams/{id}/start-again", "started a live feed again from a new snapshot"),
    ("POST", r"/streams/{id}/recipes", "added a live recipe"),
    ("PATCH", r"/streams/{id}/recipes/{id}", "changed a live recipe"),
    ("DELETE", r"/streams/{id}/recipes/{id}", "deleted a live recipe"),
    ("POST", r"/streams/{id}/recipes/{id}/start-again", "started a live recipe again"),
    ("POST", r"/database-copies", "copied a database"),
    ("POST", r"/destinations/{id}/test", "checked a destination"),
    ("POST", r"/bi-connections/{id}/test", "checked a BI tool connection"),
    ("POST", r"/notification-targets/{id}/test", "sent a test alert"),
    ("POST", r"/notification-targets/{id}/rotate-secret", "made a new signing secret for a webhook"),
    ("POST", r"/bundle/import", "imported a bundle of recipes, checks and dashboards"),
    ("POST", r"/writeback/change-sets", "started editing a live table"),
    ("POST", r"/writeback/change-sets/{id}/edits", "edited a live table"),
    ("DELETE", r"/writeback/change-sets/{id}/edits/{id}", "undid an edit to a live table"),
    ("POST", r"/writeback/change-sets/{id}/plan", "previewed edits to a live table"),
    ("POST", r"/writeback/change-sets/{id}/commit", "saved edits to a live table"),
    ("POST", r"/writeback/change-sets/{id}/discard", "discarded edits to a live table"),
    ("POST", r"/members", "added a member"),
    ("PATCH", r"/members/{id}", "changed a member's role"),
    ("DELETE", r"/members/{id}", "removed a member"),
    ("POST", r"/auth/invite", "invited someone"),
    ("POST", r"/auth/users", "created an account"),
    ("PATCH", r"/auth/users/{id}", "changed an account"),
    ("DELETE", r"/auth/users/{id}", "deleted an account"),
    ("POST", r"/auth/users/{id}/mfa/reset", "reset someone's two-step sign-in"),
    ("POST", r"/auth/users/{id}/reset-code", "made a password reset code for someone"),
    ("PATCH", r"/auth/me", "changed their profile"),
    ("PATCH", r"/auth/me/preferences", "changed their preferences"),
    ("POST", r"/auth/me/mfa/enroll", "started setting up two-step sign-in"),
    ("POST", r"/auth/me/mfa/activate", "turned on two-step sign-in"),
    ("POST", r"/auth/me/mfa/disable", "turned off two-step sign-in"),
    ("POST", r"/auth/me/mfa/recovery-codes", "made new recovery codes"),
    ("POST", r"/auth/me/sign-out-everywhere", "signed out everywhere"),
    ("PATCH", r"/notifications/read-all", "marked every notification read"),
    ("PATCH", r"/notifications/{id}/read", "marked a notification read"),
    ("PUT", r"/notifications/preferences", "changed their notification settings"),
    ("POST", r"/organisations/{id}/users/{id}", "added someone to an organisation"),
    ("DELETE", r"/organisations/{id}/users/{id}", "removed someone from an organisation"),
    ("POST", r"/organisations/{id}/projects/{id}", "moved a project into an organisation"),
    ("DELETE", r"/organisations/{id}/projects/{id}", "took a project out of an organisation"),
    ("POST", r"/connectors/test", "checked a connection"),
    ("POST", r"/connectors/{id}/streams", "listed what a source holds"),
    ("POST", r"/hooks/{id}", "sent events to a live feed"),
    ("POST", r"/internal/schedules/run-due-once", "ran the schedules that were due"),
    ("POST", r"/internal/workflows/run-queue-once", "ran the workflows waiting in the queue"),
]

_COMPILED = [
    (method, re.compile("^" + re.escape(pattern).replace(re.escape("{id}"), r"\{id\}") + "$"), words)
    for method, pattern, words in _RULES
]

#: The thing a route's last noun names, in the product's words (A0, S2).
NOUNS: dict[str, str] = {
    "datasets": "a dataset",
    "pipelines": "a recipe",
    "charts": "a chart",
    "dashboards": "a dashboard",
    "reports": "a report",
    "metrics": "a metric",
    "schedules": "a schedule",
    "workflows": "a workflow",
    "destinations": "a destination",
    "bi-connections": "a BI tool connection",
    "connections": "a source connection",
    "jobs": "an import",
    "rules": "a check",
    "saved": "a saved comparison",
    "notification-targets": "an alert channel",
    "security-policies": "an access policy",
    "freshness-policies": "a freshness limit",
    "glossary": "a glossary term",
    "catalog": "a dataset's catalogue entry",
    "notebooks": "a notebook",
    "queries": "a saved query",
    "streams": "a live feed",
    "ingest-specs": "a saved upload setting",
    "sources": "a source",
    "organisations": "an organisation",
}

_VERBS = {"POST": "created", "PUT": "changed", "PATCH": "changed", "DELETE": "deleted"}

#: Where each kind of thing keeps its name, for "the dashboard Weekly sales".
_NAME_COLUMNS: dict[str, tuple[str, str]] = {
    "datasets": ("datasets", "name"),
    "pipelines": ("transformation_pipelines", "name"),
    "charts": ("saved_charts", "name"),
    "dashboards": ("dashboards", "name"),
    "reports": ("scheduled_reports", "name"),
    "metrics": ("metrics", "name"),
    "schedules": ("scheduled_operations", "name"),
    "workflows": ("workflows", "name"),
    "destinations": ("destination_configs", "name"),
    "rules": ("data_quality_rules", "name"),
    "jobs": ("extraction_jobs", "name"),
    "connections": ("extraction_connections", "name"),
    "incidents": ("incidents", "title"),
    "changes": ("change_requests", "title"),
    "notebooks": ("workbench_notebooks", "name"),
    "queries": ("workbench_saved_queries", "name"),
    "streams": ("stream_sources", "name"),
    "recipes": ("live_recipes", "name"),
    "saved": ("saved_statistical_tests", "name"),
    "notification-targets": ("external_notification_targets", "name"),
    "security-policies": ("security_policies", "name"),
    "organisations": ("organisations", "name"),
}


def skeleton(path: str) -> str:
    """The route with identifiers as {id}, without /api/v1 and the project prefix."""
    route = _UUID.sub("{id}", path.split("?")[0]).rstrip("/")
    route = re.sub(r"^/api/v1", "", route)
    return re.sub(r"^/projects/\{id\}", "", route)


def summarise(method: str, path: str) -> str:
    """What a request did, as the words after the person's name: "ran a recipe"."""
    method = method.upper()
    route = skeleton(path)
    for rule_method, pattern, words in _COMPILED:
        if rule_method == method and pattern.match(route):
            return words
    nouns = [segment for segment in route.split("/") if segment and segment != "{id}"]
    for noun in reversed(nouns):
        if noun in NOUNS:
            return f"{_VERBS.get(method, 'changed')} {NOUNS[noun]}"
    return f"{_VERBS.get(method, 'changed')} something"


def nouns_matching(text: str) -> list[str]:
    """Route nouns whose product word contains the text: "recipe" gives ["pipelines"]."""
    needle = text.strip().lower()
    if len(needle) < 3:
        return []
    return [noun for noun, words in NOUNS.items() if needle in words.lower()]


def _target(path: str) -> tuple[str, uuid.UUID] | None:
    """The deepest named thing in the path, with its id: ("dashboards", <id>)."""
    segments = [segment for segment in path.split("?")[0].split("/") if segment]
    found: tuple[str, uuid.UUID] | None = None
    for previous, segment in zip(segments, segments[1:], strict=False):
        if previous in _NAME_COLUMNS and _UUID.fullmatch(segment):
            found = (previous, uuid.UUID(segment))
    return found


class _Entry(Protocol):
    id: uuid.UUID
    path: str
    resource_type: str | None
    resource_id: str | None


def target_of(entry: _Entry) -> tuple[str, uuid.UUID] | None:
    """The thing a recorded request touched, as ("dashboards", <id>): what it
    made, when it made something the log knows the name of, else the deepest
    named thing in its path."""
    made, kind = getattr(entry, "resource_id", None), getattr(entry, "resource_type", None)
    if made and kind and made not in entry.path and f"{kind}s" in _NAME_COLUMNS:
        try:
            return f"{kind}s", uuid.UUID(made)
        except ValueError:
            pass
    return _target(entry.path)


def current_name(db: Session, path: str) -> str | None:
    """The name, now, of the deepest named thing in a request's path."""
    target = _target(path)
    if target is None:
        return None
    table_name, column = _NAME_COLUMNS[target[0]]
    table = Base.metadata.tables.get(table_name)
    if table is None or column not in table.c:
        return None
    name = db.execute(select(table.c[column]).where(table.c.id == target[1])).scalar()
    return str(name) if name else None


def object_names(db: Session, entries: list[_Entry]) -> dict[uuid.UUID, str]:
    """The current name of what each entry touched, by entry id; for a deletion,
    the name it had before it went; missing when it has gone otherwise."""
    wanted: dict[str, set[uuid.UUID]] = defaultdict(set)
    targets: dict[uuid.UUID, tuple[str, uuid.UUID]] = {}
    for entry in entries:
        target = target_of(entry)
        if target is not None:
            targets[entry.id] = target
            wanted[target[0]].add(target[1])
    names: dict[tuple[str, uuid.UUID], str] = {}
    for noun, ids in wanted.items():
        table_name, column = _NAME_COLUMNS[noun]
        table = Base.metadata.tables.get(table_name)
        if table is None or column not in table.c:
            continue
        for row_id, name in db.execute(select(table.c.id, table.c[column]).where(table.c.id.in_(ids))).all():
            if name:
                names[(noun, row_id)] = str(name)
    found = {entry_id: names[target] for entry_id, target in targets.items() if target in names}
    for entry in entries:
        kept = getattr(entry, "object_name", None)
        if entry.id not in found and kept:
            found[entry.id] = kept
    return found
