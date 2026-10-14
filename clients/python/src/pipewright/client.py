"""The Pipewright client: every API operation, plus the few things scripts do most.

    from pipewright import Client

    client = Client("https://pipewright.example.com", token="pw_...")
    for project in client.get_projects()["items"]:
        print(project["name"])

The operations come from `_operations.py`, generated from the API's own
OpenAPI document. The helpers here (`upload`, `download`, `wait_for_run`,
`wait_for_workflow_run`, `project_id`) are the few multi-step jobs a script
needs. Settings come from the arguments, else PIPEWRIGHT_URL and
PIPEWRIGHT_TOKEN, else the file `pipewright login` writes.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from pipewright._operations import Operations

CONFIG_FILE = Path(os.environ.get("PIPEWRIGHT_CONFIG", Path.home() / ".config" / "pipewright" / "config.json"))
FINISHED = {"succeeded", "failed", "cancelled", "partial"}


class PipewrightError(Exception):
    """The API refused a request; `detail` says why, in its words."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


def saved_settings() -> dict[str, str]:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (OSError, ValueError):
        return {}


class Client(Operations):
    def __init__(self, url: str | None = None, token: str | None = None, *, http: httpx.Client | None = None,
                 timeout: float = 120.0) -> None:
        saved = saved_settings()
        self.url = (url or os.environ.get("PIPEWRIGHT_URL") or saved.get("url") or "").rstrip("/")
        token = token or os.environ.get("PIPEWRIGHT_TOKEN") or saved.get("token")
        if http is None:
            if not self.url:
                raise PipewrightError(0, "No address: pass one, set PIPEWRIGHT_URL, or run `pipewright login`.")
            http = httpx.Client(base_url=self.url, timeout=timeout)
        if token:
            http.headers["Authorization"] = f"Bearer {token}"
        http.headers.setdefault("User-Agent", "pipewright-client/0.2")
        self._http = http

    def _call(self, method: str, path: str, *, query: dict[str, Any] | None = None, body: Any = None,
              files: dict[str, Any] | None = None, data: dict[str, Any] | None = None) -> Any:
        params = {key: value for key, value in (query or {}).items() if value is not None}
        response = self._http.request(
            method, path, params=params or None,
            json=body if files is None and body is not None else None, files=files, data=data,
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            if isinstance(detail, list):  # a validation error: name the fields
                detail = "; ".join(f"{'.'.join(map(str, item.get('loc', [])[1:]))}: {item.get('msg')}" for item in detail)
            raise PipewrightError(response.status_code, str(detail or response.reason_phrase))
        if not response.content:
            return None
        if "application/json" in response.headers.get("content-type", ""):
            return response.json()
        return response.content

    # ------------------------------------------------------------ helpers

    def project_id(self, name_or_id: str) -> str:
        """A project's id, from its id or its exact name."""
        for project in self.get_projects()["items"]:
            if name_or_id in (project["id"], project["name"]):
                return project["id"]
        raise PipewrightError(404, f"No project called “{name_or_id}”.")

    def dataset_id(self, project_id: str, name_or_id: str) -> str:
        for dataset in self.get_project_datasets(project_id)["items"]:
            if name_or_id in (dataset["id"], dataset["name"]):
                return dataset["id"]
        raise PipewrightError(404, f"No dataset called “{name_or_id}” in this project.")

    def upload(self, project_id: str, file: str | Path, *, name: str | None = None) -> dict[str, Any]:
        """Upload a file as a new dataset. Large files are read in the background:
        `wait_for_run` on the answer's run to know when the rows are ready."""
        path = Path(file)
        with path.open("rb") as handle:
            return self._call(
                "POST", f"/api/v1/projects/{project_id}/datasets/upload",
                query={"dataset_name": name or path.stem}, files={"file": (path.name, handle)},
            )

    def download(self, project_id: str, dataset_id: str, to: str | Path, *, file_format: str = "csv",
                 version: int | None = None) -> Path:
        content = self._call(
            "GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/download",
            query={"format": file_format, "version": version},
        )
        target = Path(to)
        target.write_bytes(content if isinstance(content, bytes) else json.dumps(content).encode())
        return target

    def wait_for_run(self, project_id: str, run_id: str, *, timeout: float = 3600, every: float = 2.0) -> dict[str, Any]:
        """A run (an import, a recipe, a delivery) once it has finished."""
        deadline = time.monotonic() + timeout
        while True:
            run = self._call("GET", f"/api/v1/projects/{project_id}/runs/{run_id}")
            if run.get("status") in FINISHED or time.monotonic() > deadline:
                return run
            time.sleep(every)

    def wait_for_workflow_run(self, project_id: str, run_id: str, *, timeout: float = 3600,
                              every: float = 2.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            run = self._call("GET", f"/api/v1/projects/{project_id}/workflow-runs/{run_id}")
            if run.get("status") in FINISHED or time.monotonic() > deadline:
                return run
            time.sleep(every)
