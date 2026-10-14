"""Reading a stored dataset back: with its import settings, and fast (A8).

Two faults this answers.

Every read of a dataset (charts, checks, downloads, deliveries, comparisons,
the assistant, recipes) parsed the original file again with the whole
sniffing pipeline: about 20 seconds and over a gigabyte for a 200MB file,
every time anyone looked.

And it parsed without the settings the person confirmed at import. A file
whose dates were ambiguous imported correctly, showed its preview, and then
could not be charted, checked, downloaded or delivered: each read asked again
to "Analyse this file first and choose".

`frame_of` reads with the dataset's saved settings and keeps a columnar copy
next to the stored file (`<file>.read-copy.parquet`), written through the
storage backend so it is encrypted like the file. The copy records a
fingerprint of the file's bytes, its type and the settings, and is used only
when all three match; it is written only when it reads back to exactly the
same values and types, so reading from it cannot change an answer. Whatever
deletes or rewrites a stored file calls `forget_copy`, so no copy outlives
its file (erasure depends on that).
"""

from __future__ import annotations

import hashlib
import io
import json
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.logging import get_logger

logger = get_logger(__name__)

#: Bump when parsing changes what a file reads as: every copy is then ignored.
READ_COPY_VERSION = 1
SUFFIX = ".read-copy.parquet"
#: Smaller files parse in well under a second; a copy would only add a file.
MIN_BYTES = 1024 * 1024
_FINGERPRINT_KEY = b"pipewright.read_copy"


def copy_path(path: str) -> str:
    return f"{path}{SUFFIX}"


def fingerprint(payload: bytes, file_type: str | None, spec: dict[str, Any] | None) -> str:
    digest = hashlib.sha256()
    digest.update(f"v{READ_COPY_VERSION}\0{file_type or ''}\0".encode())
    digest.update(json.dumps(spec, sort_keys=True, default=str).encode() if spec else b"")
    digest.update(b"\0")
    digest.update(payload)
    return digest.hexdigest()


def parse(payload: bytes, *, file_type: str, spec: dict[str, Any] | None) -> pd.DataFrame:
    """The file read with its saved settings, or automatically when it has none.

    Settings that no longer fit the file (an older version of a dataset whose
    later import was read differently) fall back to reading it automatically;
    if that cannot decide either, the settings' own refusal is the answer.
    """
    from service_ingestion.parsers import parse_tabular_file

    try:
        return parse_tabular_file(file_bytes=payload, file_type=file_type, ingest_spec=spec or None).dataframe
    except BadRequestError:
        if not spec:
            raise
        try:
            return parse_tabular_file(file_bytes=payload, file_type=file_type).dataframe
        except BadRequestError:
            pass
        raise


def frame_of(
    storage: Any, path: str, payload: bytes, *, file_type: str, spec: dict[str, Any] | None = None
) -> pd.DataFrame:
    """The table in the stored file at `path`, whose bytes the caller has read."""
    if len(payload) < MIN_BYTES:
        return parse(payload, file_type=file_type, spec=spec)
    print_ = fingerprint(payload, file_type, spec)
    kept = _read_copy(storage, path, print_)
    if kept is not None:
        return kept
    frame = parse(payload, file_type=file_type, spec=spec)
    keep_copy(storage, path, payload, frame, file_type=file_type, spec=spec)
    return frame


def keep_copy(
    storage: Any, path: str, payload: bytes, frame: pd.DataFrame, *, file_type: str, spec: dict[str, Any] | None
) -> bool:
    """Write the copy if it reads back exactly. Best effort: never fails a read."""
    if len(payload) < MIN_BYTES:
        return False
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.Table.from_pandas(frame, preserve_index=False)
        table = table.replace_schema_metadata(
            {**(table.schema.metadata or {}), _FINGERPRINT_KEY: fingerprint(payload, file_type, spec).encode()}
        )
        buffer = io.BytesIO()
        pq.write_table(table, buffer)
        raw = buffer.getvalue()
        if not _same(frame, _restore(raw)):
            logger.info("read_copy_skipped path=%s reason=does not read back exactly", path)
            return False
        storage.save_upload(relative_path=copy_path(path), file_bytes=raw)
        return True
    except Exception:  # noqa: BLE001 - a table pyarrow cannot hold is read the slow way
        logger.info("read_copy_skipped path=%s", path, exc_info=True)
        return False


def forget_copy(storage: Any, path: str, *, strict: bool = False) -> None:
    """Delete the copy of the file at `path`; call it wherever the file goes.

    Deleting a copy that is not there is silent, as for any stored file. With
    `strict`, any other failure is raised: erasure must not report success
    while a copy of the erased values remains.
    """
    if not hasattr(storage, "delete"):
        return  # a store that cannot delete could not have been given a copy
    try:
        exists = getattr(storage, "exists", None)
        if exists is not None and not exists(copy_path(path)):
            return
        storage.delete(copy_path(path))
    except Exception:  # noqa: BLE001
        if strict:
            raise
        logger.warning("read_copy_not_removed path=%s", path, exc_info=True)


def _read_copy(storage: Any, path: str, expected: str) -> pd.DataFrame | None:
    try:
        raw = storage.read_bytes(copy_path(path))
    except FileNotFoundError:
        return None
    except Exception:  # noqa: BLE001 - an unreadable copy is ignored and rewritten
        logger.warning("read_copy_unreadable path=%s", path, exc_info=True)
        return None
    try:
        import pyarrow.parquet as pq

        metadata = pq.read_schema(io.BytesIO(raw)).metadata or {}
        if metadata.get(_FINGERPRINT_KEY, b"").decode() != expected:
            return None
        return _restore(raw)
    except Exception:  # noqa: BLE001
        logger.warning("read_copy_unreadable path=%s", path, exc_info=True)
        return None


def _restore(raw: bytes) -> pd.DataFrame:
    """Back to what parsing makes: Python values in object columns, None for missing."""
    back = pd.read_parquet(io.BytesIO(raw), dtype_backend="numpy_nullable")
    columns = {name: back[name].astype(object).where(back[name].notna(), None) for name in back.columns}
    return pd.DataFrame(columns, columns=back.columns)


def _same(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    if list(left.columns) != list(right.columns) or len(left) != len(right):
        return False
    for name in left.columns:
        if not (left[name].map(type).to_numpy() == right[name].map(type).to_numpy()).all():
            return False
    return left.equals(right)
