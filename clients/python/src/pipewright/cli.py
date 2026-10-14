"""The `pipewright` command line (A8, Y3).

    pipewright login https://pipewright.example.com --token pw_...
    pipewright projects
    pipewright datasets "Regional sales"
    pipewright upload "Regional sales" orders.csv --name Orders --wait
    pipewright download "Regional sales" Orders -o orders.csv
    pipewright run recipe "Regional sales" "Clean orders" --wait
    pipewright run workflow "Regional sales" Nightly --wait
    pipewright runs "Regional sales"
    pipewright bundle export "Regional sales" -o sales.json
    pipewright bundle import "Another project" sales.json [--preview]
    pipewright api GET /api/v1/projects

Projects, datasets, recipes and workflows can be named or given by id. Add
`--json` before the command for the API's own answers. The exit status is 0
on success, 1 when the API refused (with its reason) and 2 for a run that
finished without succeeding.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from pipewright.client import CONFIG_FILE, Client, PipewrightError


def _table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "Nothing here yet."
    widths = [max(len(title), *(len(str(row.get(key) or "")) for row in rows)) for key, title in columns]
    lines = ["  ".join(title.ljust(width) for (_, title), width in zip(columns, widths))]
    for row in rows:
        lines.append("  ".join(str(row.get(key) or "").ljust(width) for (key, _), width in zip(columns, widths)))
    return "\n".join(lines)


# The words the web uses for a run (apps/web/src/lib/run-labels.ts).
RUN_WORDS = {
    "sample_orchestration": "Sample run",
    "dataset_ingestion": "File upload",
    "dataset_upload": "File upload",
    "database_extraction": "Import",
    "dataset_transformation": "Recipe run",
    "dataset_transformation_replay": "Recipe replay",
    "dataset_publish_postgres": "Delivered to PostgreSQL",
    "dataset_delivery": "Delivery",
    "database_copy": "Database copy",
    "dataset_publish_power_bi": "Sent to Power BI",
    "dataset_publish_tableau": "Sent to Tableau",
}
STATUS_WORDS = {"queued": "Waiting", "running": "Running", "succeeded": "Succeeded", "failed": "Failed"}


def _named(items: list[dict[str, Any]], name_or_id: str, kind: str) -> dict[str, Any]:
    for item in items:
        if name_or_id in (item.get("id"), item.get("name")):
            return item
    raise PipewrightError(404, f"No {kind} called “{name_or_id}”.")


def _finished(run: dict[str, Any]) -> int:
    status = run.get("status")
    print(f"Finished: {status}.", file=sys.stderr)
    return 0 if status == "succeeded" else 2


def main(argv: list[str] | None = None, *, client: Client | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipewright", description="Work with Pipewright from a terminal or a script.")
    parser.add_argument("--json", action="store_true", help="print the API's answers as JSON")
    commands = parser.add_subparsers(dest="command", required=True)

    login = commands.add_parser("login", help="save the address and an API token for later commands")
    login.add_argument("url")
    login.add_argument("--token", required=True, help="an API token from Your settings → API tokens")

    commands.add_parser("projects", help="list projects")
    datasets = commands.add_parser("datasets", help="list a project's datasets")
    datasets.add_argument("project")

    upload = commands.add_parser("upload", help="upload a file as a new dataset")
    upload.add_argument("project")
    upload.add_argument("file")
    upload.add_argument("--name")
    upload.add_argument("--wait", action="store_true", help="wait until a large file has been read")

    download = commands.add_parser("download", help="download a dataset")
    download.add_argument("project")
    download.add_argument("dataset")
    download.add_argument("-o", "--output", required=True)
    download.add_argument("--format", choices=("csv", "parquet"), default="csv")
    download.add_argument("--version", type=int)

    run = commands.add_parser("run", help="run a recipe or a workflow")
    run.add_argument("kind", choices=("recipe", "workflow"))
    run.add_argument("project")
    run.add_argument("name")
    run.add_argument("--wait", action="store_true", help="wait for it to finish")

    runs = commands.add_parser("runs", help="a project's recent runs")
    runs.add_argument("project")

    bundle = commands.add_parser("bundle", help="move a project's recipes, checks, dashboards and workflows")
    bundle_commands = bundle.add_subparsers(dest="bundle_command", required=True)
    export = bundle_commands.add_parser("export")
    export.add_argument("project")
    export.add_argument("-o", "--output", required=True)
    bring = bundle_commands.add_parser("import")
    bring.add_argument("project")
    bring.add_argument("file")
    bring.add_argument("--preview", action="store_true", help="say what would happen, change nothing")

    raw = commands.add_parser("api", help="call any API operation")
    raw.add_argument("method", choices=("GET", "POST", "PUT", "PATCH", "DELETE"))
    raw.add_argument("path", help="for example /api/v1/projects")
    raw.add_argument("--data", help="a JSON body")

    args = parser.parse_args(argv)

    if args.command == "login":
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps({"url": args.url.rstrip("/"), "token": args.token}))
        os.chmod(CONFIG_FILE, 0o600)
        try:
            me = (client or Client(args.url, args.token))._call("GET", "/api/v1/auth/me")
        except PipewrightError as exc:
            print(f"Saved, but signing in failed: {exc.detail}", file=sys.stderr)
            return 1
        print(f"Signed in as {me.get('display_name') or me.get('username')}. Saved to {CONFIG_FILE}.")
        return 0

    try:
        api = client or Client()
        return _run(api, args)
    except PipewrightError as exc:
        print(f"Refused: {exc.detail}", file=sys.stderr)
        return 1


def _run(api: Client, args: argparse.Namespace) -> int:
    def show(value: Any, text: str) -> None:
        print(json.dumps(value, indent=2, default=str) if args.json else text)

    if args.command == "projects":
        items = api.get_projects()["items"]
        show(items, _table(items, [("name", "Name"), ("id", "Id")]))
        return 0

    project = api.project_id(args.project) if hasattr(args, "project") else None

    if args.command == "datasets":
        items = api.get_project_datasets(project)["items"]
        show(items, _table(items, [("name", "Name"), ("row_count", "Rows"), ("ingestion_status", "Read"), ("id", "Id")]))
        return 0
    if args.command == "upload":
        answer = api.upload(project, args.file, name=args.name)
        dataset, run_ = answer["dataset"], answer.get("run") or {}
        print(f"Uploaded as “{dataset['name']}” ({dataset['id']}).", file=sys.stderr)
        if args.wait and run_.get("status") not in ("succeeded", "failed"):
            return _finished(api.wait_for_run(project, run_["id"]))
        if args.json:
            show(answer, "")
        return 0
    if args.command == "download":
        dataset = api.dataset_id(project, args.dataset)
        target = api.download(project, dataset, args.output, file_format=args.format, version=args.version)
        print(f"Saved {target}.", file=sys.stderr)
        return 0
    if args.command == "run":
        if args.kind == "recipe":
            recipe = _named(api.get_project_pipelines(project)["items"], args.name, "recipe")
            answer = api.post_run_transformation_pipeline(project, recipe["id"])
            run_id = (answer.get("run") or answer).get("id")
            print(f"Started “{recipe['name']}”.", file=sys.stderr)
            if args.wait and run_id:
                return _finished(api.wait_for_run(project, run_id))
        else:
            workflow = _named(api.get_workflows(project)["items"], args.name, "workflow")
            answer = api.post_workflow_run(project, workflow["id"], body={})
            print(f"Queued “{workflow['name']}”.", file=sys.stderr)
            if args.wait:
                return _finished(api.wait_for_workflow_run(project, answer["id"]))
        if args.json:
            show(answer, "")
        return 0
    if args.command == "runs":
        items = api.get_project_runs(project)["items"]
        rows = [
            {
                **item,
                "what": RUN_WORDS.get(item.get("run_type"), str(item.get("run_type") or "").replace("_", " ").capitalize()),
                "result": STATUS_WORDS.get(item.get("status"), item.get("status")),
                "when": str(item.get("created_at") or "")[:16].replace("T", " "),
            }
            for item in items[:20]
        ]
        show(items, _table(rows, [("what", "What"), ("result", "Result"), ("when", "When"), ("id", "Id")]))
        return 0
    if args.command == "bundle":
        if args.bundle_command == "export":
            Path(args.output).write_text(json.dumps(api.get_bundle(project), indent=2))
            print(f"Saved {args.output}.", file=sys.stderr)
            return 0
        payload = {"bundle": json.loads(Path(args.file).read_text()), "mapping": {}}
        answer = api.post_bundle_preview(project, body=payload) if args.preview else api.post_bundle_import(project, body=payload)
        lines = [f"{'Would make' if args.preview else 'Made'} {answer['creates']}; left out {answer['skips']}."]
        lines += [f"  left out {item['kind']} “{item['name']}”: {item['reason']}" for item in answer["items"] if item["action"] == "skip"]
        show(answer, "\n".join(lines))
        return 0
    if args.command == "api":
        body = json.loads(args.data) if args.data else None
        answer = api._call(args.method, args.path, body=body)
        print(json.dumps(answer, indent=2, default=str) if not isinstance(answer, bytes) else answer.decode(errors="replace"))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
