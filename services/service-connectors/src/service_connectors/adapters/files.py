"""Files, wherever they live.

Object storage and a local directory are the same problem wearing different
clothes: a list of paths, a pattern that selects some of them, and a format
inside each one. So they share an implementation and differ only in how the
listing is fetched.

The part that matters for scheduled work is **incremental discovery**. A folder
that gets a new file every night should not be re-read from the beginning every
night. The cursor is the last-modified time of the newest file already read, so
resuming means listing and filtering rather than remembering every filename ever
seen.
"""

from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from service_connectors.formats import (
    FORMATS_BY_NAME,
    compression_for_path,
    format_for_path,
    read_bytes,
    write_bytes,
)
from service_connectors.protocol import (
    ConfigField,
    ConnectorError,
    ConnectorSpec,
    ReadResult,
    StreamColumn,
    StreamRef,
    TestResult,
    WriteResult,
)

# Reading a thousand files into one frame is not a pipeline, it is an outage.
MAX_FILES_PER_READ = 200


@dataclass(frozen=True)
class RemoteFile:
    path: str
    size_bytes: int
    modified_at: datetime

    def to_detail(self) -> dict[str, Any]:
        return {
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at.isoformat(),
        }


def matches(path: str, pattern: str | None) -> bool:
    """Whether a path is selected by a glob.

    Matched against the full path *and* the bare filename, so `*.csv` does the
    obvious thing on `2026/03/orders.csv` without anyone having to write
    `**/*.csv`.
    """
    if not pattern:
        return True
    name = path.rsplit("/", 1)[-1]
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(name, pattern)


def newer_than(files: list[RemoteFile], cursor: str | None) -> list[RemoteFile]:
    """Only the files modified after the cursor."""
    if not cursor:
        return files
    try:
        since = datetime.fromisoformat(cursor)
    except ValueError:
        return files
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return [file for file in files if file.modified_at > since]


def cursor_for(files: list[RemoteFile]) -> str | None:
    """Where to resume from: the newest file read this time."""
    if not files:
        return None
    return max(file.modified_at for file in files).isoformat()


def combine(frames: list[pd.DataFrame], *, source_paths: list[str]) -> pd.DataFrame:
    """Stack several files into one frame, recording where each row came from.

    The `_source_file` column is added deliberately: when a nightly load goes
    wrong, the first question is always which file it came from, and without
    this the answer is unrecoverable.
    """
    if not frames:
        return pd.DataFrame()
    stamped = []
    for frame, path in zip(frames, source_paths, strict=True):
        copy = frame.copy()
        copy["_source_file"] = path
        stamped.append(copy)
    return pd.concat(stamped, ignore_index=True, sort=False)


class _FileConnectorBase:
    """Shared behaviour; subclasses only have to list and fetch."""

    spec: ConnectorSpec

    def _list(self, config: dict[str, Any]) -> list[RemoteFile]:
        raise NotImplementedError

    def _fetch(self, config: dict[str, Any], path: str) -> bytes:
        raise NotImplementedError

    def _selected(self, config: dict[str, Any]) -> list[RemoteFile]:
        pattern = config.get("pattern")
        return [file for file in self._list(config) if matches(file.path, pattern)]

    def test(self, config: dict[str, Any]) -> TestResult:
        started = time.perf_counter()
        try:
            files = self._selected(config)
        except ConnectorError as exc:
            return TestResult(success=False, message=exc.message)
        except Exception as exc:  # noqa: BLE001
            return TestResult(success=False, message=f"Could not list files: {exc}")

        latency = round((time.perf_counter() - started) * 1000, 2)
        pattern = config.get("pattern")
        if not files:
            return TestResult(
                success=True,
                message=(
                    f"Reachable, but nothing matches '{pattern}'."
                    if pattern
                    else "Reachable, but there are no files here."
                ),
                latency_ms=latency,
                warnings=["Nothing to read yet."],
            )

        unreadable = [file.path for file in files if format_for_path(file.path) is None]
        warnings = (
            [f"{len(unreadable)} file(s) have an unrecognised format and will be skipped."]
            if unreadable
            else []
        )
        return TestResult(
            success=True,
            message=f"Found {len(files)} file(s).",
            latency_ms=latency,
            warnings=warnings,
        )

    def discover(self, config: dict[str, Any]) -> list[StreamRef]:
        return [
            StreamRef(
                name=file.path,
                kind="file",
                detail=file.to_detail(),
            )
            for file in self._selected(config)
        ]

    def columns(self, config: dict[str, Any], stream: StreamRef) -> list[StreamColumn]:
        frame = self._read_one(config, stream.name, limit=50)
        return [
            StreamColumn(name=str(column), data_type=str(frame[column].dtype), nullable=True)
            for column in frame.columns
        ]

    def _read_one(self, config: dict[str, Any], path: str, *, limit: int | None = None) -> pd.DataFrame:
        chosen = str(config.get("format") or "").strip() or format_for_path(path)
        if chosen is None:
            raise ConnectorError(
                f"Cannot tell what format '{path}' is. Set the format explicitly."
            )
        if chosen not in FORMATS_BY_NAME:
            raise ConnectorError(f"Unknown format '{chosen}'.")

        options: dict[str, Any] = {}
        for key in ("delimiter", "sheet", "widths", "names"):
            if config.get(key) is not None:
                options[key] = config[key]

        frame = read_bytes(
            self._fetch(config, path),
            format=chosen,
            compression=compression_for_path(path),
            options=options,
        )
        return frame.head(limit) if limit else frame

    def write(
        self,
        config: dict[str, Any],
        stream: StreamRef | None,
        frame: pd.DataFrame,
        *,
        mode: str = "replace",
    ) -> WriteResult:
        """Push a frame back out as a file.

        `append` is honoured by reading what is there and concatenating rather
        than by appending bytes: for CSV that would work and for Parquet it
        would produce a corrupt file, and a mode that silently means different
        things per format is worse than one that costs a read.
        """
        path = (stream.name if stream is not None else str(config.get("write_path") or "")).strip()
        if not path:
            raise ConnectorError("No path to write to.")
        if mode not in ("replace", "append"):
            raise ConnectorError(f"Files can be replaced or appended to, not '{mode}'.")

        chosen = str(config.get("format") or "").strip() or format_for_path(path)
        if chosen is None:
            raise ConnectorError(f"Cannot tell what format '{path}' should be.")

        outgoing = frame
        warnings: list[str] = []
        if mode == "append":
            try:
                existing = self._read_one(config, path)
                outgoing = pd.concat([existing, frame], ignore_index=True, sort=False)
                if set(existing.columns) != set(frame.columns):
                    warnings.append(
                        "The existing file has different columns; missing values are null."
                    )
            except Exception:  # noqa: BLE001 - nothing there yet is the normal case
                warnings.append("Nothing to append to, so the file was created.")

        self._put(config, path, write_bytes(outgoing, format=chosen))
        return WriteResult(
            rows_written=len(outgoing),
            mode=mode,
            message=f"Wrote {len(outgoing)} row(s) to '{path}'.",
            warnings=warnings,
        )

    def _put(self, config: dict[str, Any], path: str, payload: bytes) -> None:
        raise NotImplementedError

    def read(
        self,
        config: dict[str, Any],
        stream: StreamRef | None = None,
        *,
        limit: int = 100_000,
        cursor: str | None = None,
    ) -> ReadResult:
        if stream is not None and stream.kind == "file":
            files = [
                RemoteFile(
                    path=stream.name,
                    size_bytes=int(stream.detail.get("size_bytes") or 0),
                    modified_at=datetime.now(UTC),
                )
            ]
        else:
            files = newer_than(self._selected(config), cursor)

        files.sort(key=lambda file: file.modified_at)
        truncated = False
        if len(files) > MAX_FILES_PER_READ:
            files = files[:MAX_FILES_PER_READ]
            truncated = True

        frames: list[pd.DataFrame] = []
        paths: list[str] = []
        warnings: list[str] = []
        rows = 0

        for file in files:
            if format_for_path(file.path) is None and not config.get("format"):
                warnings.append(f"Skipped '{file.path}': unrecognised format.")
                continue
            frame = self._read_one(config, file.path)
            frames.append(frame)
            paths.append(file.path)
            rows += len(frame)
            if rows >= limit:
                truncated = True
                break

        combined = combine(frames, source_paths=paths)
        if len(combined) > limit:
            combined = combined.head(limit)
            truncated = True

        return ReadResult(
            dataframe=combined,
            row_count=len(combined),
            truncated=truncated,
            next_cursor=cursor_for(files) or cursor,
            warnings=warnings,
        )


_FORMAT_FIELDS = (
    ConfigField(
        "pattern",
        "File pattern",
        required=False,
        default="*",
        help="A glob such as *.csv or 2026/*/orders-*.parquet.",
    ),
    ConfigField(
        "format",
        "Format",
        kind="select",
        required=False,
        options=tuple(FORMATS_BY_NAME),
        help="Leave blank to work it out from the file extension.",
    ),
    ConfigField("delimiter", "Delimiter", required=False, help="CSV only."),
    ConfigField("sheet", "Sheet", required=False, help="Excel only."),
    ConfigField(
        "write_path",
        "Write path",
        required=False,
        help="Where reverse ETL writes to, relative to the directory or prefix.",
    ),
)


class LocalFileConnector(_FileConnectorBase):
    """A directory the platform can see."""

    spec = ConnectorSpec(
        type="local_files",
        label="Server files",
        category="file",
        description="Read files from a directory on the platform's own filesystem.",
        config_fields=(
            ConfigField(
                "directory",
                "Directory",
                placeholder="/data/incoming",
                help="An absolute path the platform can read.",
            ),
            *_FORMAT_FIELDS,
        ),
        capabilities=frozenset(
            {"test", "discover", "schema", "read", "incremental", "write"}
        ),
    )

    def _root(self, config: dict[str, Any]) -> Path:
        raw = str(config.get("directory") or "").strip()
        if not raw:
            raise ConnectorError("No directory set.")
        root = Path(raw)
        if not root.is_absolute():
            # A relative path resolves against whatever the worker's working
            # directory happens to be, which is not something anyone can reason
            # about from a config screen.
            raise ConnectorError("The directory must be an absolute path.")
        if not root.exists():
            raise ConnectorError(f"'{root}' does not exist.")
        if not root.is_dir():
            raise ConnectorError(f"'{root}' is a file, not a directory.")
        return root

    def _list(self, config: dict[str, Any]) -> list[RemoteFile]:
        root = self._root(config)
        files: list[RemoteFile] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            stat = path.stat()
            files.append(
                RemoteFile(
                    path=str(path.relative_to(root)),
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                )
            )
        return files

    def _resolve_inside(self, config: dict[str, Any], path: str) -> Path:
        root = self._root(config)
        target = (root / path).resolve()
        # Without this, a pattern or a stream name containing '..' reaches
        # anything the process can see.
        if not str(target).startswith(str(root.resolve())):
            raise ConnectorError("That path is outside the configured directory.")
        return target

    def _fetch(self, config: dict[str, Any], path: str) -> bytes:
        return self._resolve_inside(config, path).read_bytes()

    def _put(self, config: dict[str, Any], path: str, payload: bytes) -> None:
        target = self._resolve_inside(config, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


class S3Connector(_FileConnectorBase):
    """S3 and anything that speaks its API."""

    spec = ConnectorSpec(
        type="s3",
        label="S3 object storage",
        category="storage",
        description="Read objects from Amazon S3 or an S3-compatible store such as MinIO or R2.",
        config_fields=(
            ConfigField("bucket", "Bucket"),
            ConfigField("prefix", "Prefix", required=False, help="Only look under this key prefix."),
            ConfigField("region", "Region", required=False, default="us-east-1"),
            ConfigField(
                "endpoint_url",
                "Endpoint URL",
                required=False,
                help="Set this for MinIO, R2, or another S3-compatible store.",
            ),
            ConfigField("access_key_id", "Access key id"),
            ConfigField("secret_access_key", "Secret access key", kind="secret"),
            *_FORMAT_FIELDS,
        ),
        capabilities=frozenset({"test", "discover", "schema", "read", "incremental", "write"}),
        driver_package="boto3",
    )

    def _client(self, config: dict[str, Any]):
        try:
            import boto3
        except ImportError as exc:
            raise ConnectorError("S3 support needs the 'boto3' package.") from exc

        return boto3.client(
            "s3",
            region_name=str(config.get("region") or "us-east-1"),
            endpoint_url=config.get("endpoint_url") or None,
            aws_access_key_id=str(config.get("access_key_id") or ""),
            aws_secret_access_key=str(config.get("secret_access_key") or ""),
        )

    def _list(self, config: dict[str, Any]) -> list[RemoteFile]:
        client = self._client(config)
        bucket = str(config["bucket"])
        prefix = str(config.get("prefix") or "")

        files: list[RemoteFile] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            try:
                response = client.list_objects_v2(**kwargs)
            except Exception as exc:  # noqa: BLE001 - boto raises a family of errors
                raise ConnectorError(f"Could not list '{bucket}': {exc}") from exc

            for entry in response.get("Contents", []):
                key = entry["Key"]
                if key.endswith("/"):
                    continue  # A folder marker, not an object.
                files.append(
                    RemoteFile(
                        path=key,
                        size_bytes=int(entry.get("Size") or 0),
                        modified_at=entry["LastModified"],
                    )
                )

            if not response.get("IsTruncated"):
                break
            token = response.get("NextContinuationToken")
            if not token:
                break
        return files

    def _fetch(self, config: dict[str, Any], path: str) -> bytes:
        client = self._client(config)
        try:
            response = client.get_object(Bucket=str(config["bucket"]), Key=path)
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"Could not read '{path}': {exc}") from exc
        return response["Body"].read()

    def _put(self, config: dict[str, Any], path: str, payload: bytes) -> None:
        client = self._client(config)
        try:
            client.put_object(Bucket=str(config["bucket"]), Key=path, Body=payload)
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"Could not write '{path}': {exc}") from exc


FILE_CONNECTORS = (LocalFileConnector(), S3Connector())
