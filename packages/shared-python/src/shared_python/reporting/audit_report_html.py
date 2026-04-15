from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from typing import Any

# Self-contained print stylesheet. PDF generation can reuse the same document shell later.
_AUDIT_REPORT_CSS = """
  :root { color-scheme: light; }
  body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         font-size: 14px; line-height: 1.45; color: #0f172a; background: #f8fafc; margin: 0; padding: 24px; }
  .doc { max-width: 880px; margin: 0 auto; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px;
         padding: 28px 32px 36px; box-shadow: 0 1px 2px rgba(15,23,42,0.06); }
  h1 { font-size: 22px; font-weight: 650; margin: 0 0 8px; letter-spacing: -0.02em; }
  .meta { font-size: 12px; color: #64748b; margin-bottom: 24px; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; color: #475569;
       border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; margin: 28px 0 12px; }
  h2:first-of-type { margin-top: 0; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px 10px; border: 1px solid #e2e8f0; vertical-align: top; }
  th { background: #f1f5f9; font-weight: 600; width: 32%; }
  ul.notes { margin: 0; padding-left: 18px; }
  ul.notes li { margin-bottom: 6px; }
  pre.raw { font-size: 11px; line-height: 1.4; background: #0f172a; color: #e2e8f0; padding: 12px 14px;
             border-radius: 6px; overflow: auto; white-space: pre-wrap; word-break: break-word; }
  .muted { color: #64748b; font-size: 12px; }
  @media print { body { background: #fff; padding: 0; } .doc { box-shadow: none; border: none; } }
"""


def sanitize_audit_filename_component(value: str, *, fallback: str = "audit") -> str:
    """ASCII-safe single path segment for Content-Disposition filenames."""
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-._")
    if not cleaned:
        return fallback
    return cleaned[:120]


def _esc(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return html.escape(str(value))


def _json_pre(data: Any) -> str:
    try:
        text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    except TypeError:
        text = repr(data)
    return f"<pre class=\"raw\">{_esc(text)}</pre>"


def render_dataset_audit_report_html(payload: dict[str, Any]) -> str:
    """Render a full HTML document from a JSON-serializable dataset audit summary dict."""
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    project = payload.get("project") or {}
    artifact = payload.get("artifact") or {}
    metrics = payload.get("metrics") or {}
    ph = payload.get("profile_highlights") or {}
    lineage = payload.get("lineage") or {}
    schema = payload.get("schema_summary") or {}
    warnings = payload.get("warnings") or []

    notes_html = (
        "<ul class=\"notes\">" + "".join(f"<li>{_esc(w)}</li>" for w in warnings) + "</ul>"
        if warnings
        else "<p class=\"muted\">No audit notes.</p>"
    )

    rows_identity = [
        ("Dataset id", _esc(payload.get("id"))),
        ("Name", _esc(payload.get("name"))),
        ("Derived", _esc(payload.get("is_derived"))),
        ("Parent dataset id", _esc(payload.get("parent_dataset_id"))),
        ("Project id", _esc(project.get("id"))),
        ("Project name", _esc(project.get("name"))),
        ("Uploaded by (user id)", _esc((payload.get("ownership") or {}).get("uploaded_by_user_id"))),
    ]

    rows_metrics = [
        ("Row count", _esc(metrics.get("row_count"))),
        ("Column count", _esc(metrics.get("column_count"))),
        ("Ingestion status", _esc(metrics.get("ingestion_status"))),
        ("Created at", _esc(metrics.get("created_at"))),
        ("Updated at", _esc(metrics.get("updated_at"))),
        ("Last profiled at", _esc(metrics.get("last_profiled_at"))),
    ]

    rows_artifact = [
        ("Original filename", _esc(artifact.get("original_filename"))),
        ("Stored file name", _esc(artifact.get("file_name"))),
        ("File type", _esc(artifact.get("file_type"))),
        ("File size (bytes)", _esc(artifact.get("file_size_bytes"))),
        ("Storage path (safe)", _esc(artifact.get("file_path"))),
    ]

    rows_quality = [
        ("Duplicate rows", _esc(ph.get("duplicate_row_count"))),
        ("Duplicate row %", _esc(ph.get("duplicate_row_percentage"))),
        ("Completeness score", _esc(ph.get("completeness_score"))),
        ("High-null columns", _esc(", ".join(ph.get("high_null_columns") or []) or "—")),
        ("Constant columns", _esc(", ".join(ph.get("constant_value_columns") or []) or "—")),
        ("Potential id columns", _esc(", ".join(ph.get("potential_id_columns") or []) or "—")),
    ]

    rows_lineage = [
        ("Parent dataset id", _esc(lineage.get("parent_dataset_id"))),
        ("Created from pipeline id", _esc(lineage.get("created_from_pipeline_id"))),
        ("Pipeline run id", _esc(lineage.get("pipeline_run_id"))),
    ]

    sample_cols = schema.get("sample_column_names") or []
    schema_extra = (
        "<p><strong>Sample columns:</strong> "
        + (_esc(", ".join(str(c) for c in sample_cols)) if sample_cols else "<span class=\"muted\">—</span>")
        + "</p>"
    )

    def _table(rows: list[tuple[str, str]]) -> str:
        body = "".join(f"<tr><th>{a}</th><td>{b}</td></tr>" for a, b in rows)
        return f"<table><tbody>{body}</tbody></table>"

    title = f"Dataset audit — {_esc(payload.get('name'))}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>{_AUDIT_REPORT_CSS}</style>
</head>
<body>
<div class="doc">
  <h1>Dataset audit report</h1>
  <p class="meta">Generated { _esc(generated) } · Read-only summary from persisted platform metadata.</p>

  <h2>Identity &amp; project</h2>
  {_table(rows_identity)}

  <h2>Audit notes</h2>
  {notes_html}

  <h2>Metrics</h2>
  {_table(rows_metrics)}

  <h2>Artifact</h2>
  {_table(rows_artifact)}

  <h2>Quality / profile highlights</h2>
  {_table(rows_quality)}

  <h2>Schema summary</h2>
  <p>Column count: {_esc(schema.get("column_count"))}</p>
  {schema_extra}

  <h2>Lineage</h2>
  {_table(rows_lineage)}

  <h2>Technical details</h2>
  <p class="muted">Structured audit fields above reflect persisted dataset metadata. This export does not include raw schema_json or profile_json blobs; use the API or product UI for full JSON inspection if needed.</p>
</div>
</body>
</html>"""


def render_run_audit_report_html(payload: dict[str, Any]) -> str:
    """Render a full HTML document from a JSON-serializable run audit summary dict."""
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    h = payload.get("highlights") or {}
    warnings = payload.get("warnings") or []
    related = payload.get("related_dataset_ids") or []

    notes_html = (
        "<ul class=\"notes\">" + "".join(f"<li>{_esc(w)}</li>" for w in warnings) + "</ul>"
        if warnings
        else "<p class=\"muted\">No audit notes.</p>"
    )

    rows_identity = [
        ("Run id", _esc(payload.get("id"))),
        ("Project id", _esc(payload.get("project_id"))),
        ("Run type", _esc(payload.get("run_type"))),
        ("Status", _esc(payload.get("status"))),
        ("Triggered by (user id)", _esc(payload.get("triggered_by_user_id"))),
        ("Pipeline id", _esc(payload.get("pipeline_id"))),
        ("Created at", _esc(payload.get("created_at"))),
        ("Started at", _esc(payload.get("started_at"))),
        ("Completed at", _esc(payload.get("completed_at"))),
    ]

    rows_highlights = [
        ("Logged stages", _esc(h.get("stage_count"))),
        ("Failed stage", _esc(h.get("failed_stage"))),
        ("Derived dataset created", _esc(h.get("derived_dataset_created"))),
        ("Ingestion type", _esc(h.get("ingestion_type"))),
        ("Transformation type", _esc(h.get("transformation_type"))),
    ]

    related_html = (
        "<ul class=\"notes\">"
        + "".join(f"<li>{_esc(str(rid))}</li>" for rid in related)
        + "</ul>"
        if related
        else "<p class=\"muted\">None inferred from summary_json.</p>"
    )

    events: list[dict[str, Any]] = []
    logs = payload.get("logs_json")
    if isinstance(logs, dict):
        raw_events = logs.get("events")
        if isinstance(raw_events, list):
            events = [e for e in raw_events if isinstance(e, dict)]

    if events:
        log_rows = []
        for ev in events:
            log_rows.append(
                (
                    _esc(ev.get("stage")),
                    _esc(ev.get("message")),
                )
            )
        stages_table = (
            "<table><thead><tr><th>Stage</th><th>Message</th></tr></thead><tbody>"
            + "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in log_rows)
            + "</tbody></table>"
        )
    else:
        stages_table = "<p class=\"muted\">No structured log events in logs_json.</p>"

    summary_block = _json_pre(payload.get("summary_json"))
    logs_block = _json_pre(payload.get("logs_json"))

    title = f"Run audit — {_esc(payload.get('id'))}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>{_AUDIT_REPORT_CSS}</style>
</head>
<body>
<div class="doc">
  <h1>Pipeline run audit report</h1>
  <p class="meta">Generated { _esc(generated) } · Read-only summary from persisted run metadata.</p>

  <h2>Identity &amp; status</h2>
  <table><tbody>
  {"".join(f"<tr><th>{a}</th><td>{b}</td></tr>" for a, b in rows_identity)}
  </tbody></table>

  <h2>Audit notes</h2>
  {notes_html}

  <h2>Highlights</h2>
  <table><tbody>
  {"".join(f"<tr><th>{a}</th><td>{b}</td></tr>" for a, b in rows_highlights)}
  </tbody></table>

  <h2>Related dataset ids</h2>
  {related_html}

  <h2>Stage / log overview</h2>
  {stages_table}

  <h2>Raw summary_json</h2>
  {summary_block}

  <h2>Raw logs_json</h2>
  {logs_block}
</div>
</body>
</html>"""
