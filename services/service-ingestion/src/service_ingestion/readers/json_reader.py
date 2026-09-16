"""JSON, JSON Lines, and the several things people mean by "a JSON file".

Three shapes arrive under the same extension and need different handling:

* **One array** of objects — the common export.
* **JSON Lines** — one object per line, the common log or stream dump.
* **Concatenated documents** — `{...}{...}{...}` with no separator, which is
  what you get from appending to a file in a loop. It is not valid JSON and
  every naive reader fails on it with a message about column 1 of line 1.

Then there is the question a tabular reader has to answer and usually does not:
**where the records are**. A response envelope puts them under `data.items`,
and reading the top level gives one row with a column called `data`. The path
is found by looking for the deepest array of objects, reported so it can be
changed, and never silently assumed.

Nested objects become dotted columns; arrays stay as JSON text rather than
being exploded, because exploding changes what one row means. `explode` is a
transformation the user asks for, in the Studio, where they can see it happen.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

from service_ingestion.readers.base import ReadResult, normalise_columns
from service_ingestion.sniff.evidence import Candidate, Certainty, Finding, certain

#: How deep into a document the record array is looked for.
MAX_DEPTH = 6


def _decode(payload: bytes) -> str:
    from service_ingestion.sniff import pipeline

    text, _ = pipeline.text_of(payload)
    return text


def find_records_path(document: Any, *, depth: int = 0, path: str = "") -> tuple[str, int] | None:
    """The path to the array of objects that is the table.

    Depth-first and widest-wins: a document with `{"meta": [...], "data": [...]}`
    has two arrays, and the one with more objects in it is the records.
    """
    if depth > MAX_DEPTH or not isinstance(document, dict):
        return None
    best: tuple[str, int] | None = None
    for key, value in document.items():
        here = f"{path}.{key}" if path else str(key)
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            if best is None or len(value) > best[1]:
                best = (here, len(value))
        elif isinstance(value, dict):
            deeper = find_records_path(value, depth=depth + 1, path=here)
            if deeper and (best is None or deeper[1] > best[1]):
                best = deeper
    return best


def _walk(document: Any, path: str) -> Any:
    current = document
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def read_json(
    payload: bytes, *, overrides: dict[str, Any] | None = None, limit: int | None = None
) -> ReadResult:
    overrides = dict(overrides or {})
    text = _decode(payload).strip()
    if not text:
        raise BadRequestError("This JSON file is empty.")

    findings: list[Finding] = []
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        # Concatenated documents are the common cause, and are recoverable.
        records = _concatenated(text)
        if records is None:
            raise BadRequestError(
                f"Could not parse this as JSON: {exc.msg} at line {exc.lineno}, "
                f"column {exc.colno}."
            ) from exc
        findings.append(
            certain(
                "json_shape",
                "concatenated",
                (
                    f"{len(records)} JSON documents written one after another with no "
                    "separating array. Read as one record each."
                ),
            )
        )
        return _frame_from(records, findings, {"shape": "concatenated"}, limit)

    if isinstance(document, list):
        if not document:
            raise BadRequestError("This JSON file contains an empty array.")
        if not all(isinstance(item, dict) for item in document):
            scalars = [item for item in document if not isinstance(item, dict)]
            findings.append(
                certain(
                    "json_shape",
                    "array_of_scalars",
                    (
                        f"An array containing {len(scalars)} non-object value(s); each becomes "
                        "a row with a single 'value' column."
                    ),
                    evidence=[json.dumps(item)[:60] for item in scalars[:3]],
                )
            )
            document = [item if isinstance(item, dict) else {"value": item} for item in document]
        else:
            findings.append(
                certain("json_shape", "array", f"A top-level array of {len(document)} objects.")
            )
        return _frame_from(document, findings, {"shape": "array"}, limit)

    if not isinstance(document, dict):
        raise BadRequestError("A JSON file must hold an object or an array to be read as a table.")

    supplied = overrides.get("records_path")
    if supplied:
        records = _walk(document, str(supplied))
        if not isinstance(records, list):
            raise BadRequestError(f"There is no array at '{supplied}' in this document.")
        findings.append(
            certain(
                "records_path",
                supplied,
                "Records path supplied with the file rather than inferred.",
            )
        )
        return _frame_from(records, findings, {"shape": "envelope", "records_path": supplied}, limit)

    found = find_records_path(document)
    if found is None:
        findings.append(
            certain(
                "json_shape",
                "single_object",
                "One object with no array inside it; read as a single row.",
            )
        )
        return _frame_from([document], findings, {"shape": "object"}, limit)

    path, count = found
    alternatives = _all_arrays(document)
    findings.append(
        Finding(
            stage="records_path",
            value=path,
            certainty=Certainty.LIKELY if len(alternatives) <= 1 else Certainty.UNCERTAIN,
            confidence=0.9 if len(alternatives) <= 1 else 0.6,
            reason=(
                f"The records are the {count}-object array at '{path}'"
                + (
                    f". {len(alternatives) - 1} other array(s) are present; change the path "
                    "if one of those is the table."
                    if len(alternatives) > 1
                    else "."
                )
            ),
            candidates=[
                Candidate(name, size / max(count, 1), f"{size} objects")
                for name, size in alternatives[:4]
            ],
            evidence=[json.dumps(_walk(document, path)[0])[:120]] if count else [],
        )
    )
    records = _walk(document, path)
    return _frame_from(records, findings, {"shape": "envelope", "records_path": path}, limit)


def read_jsonl(
    payload: bytes, *, overrides: dict[str, Any] | None = None, limit: int | None = None
) -> ReadResult:
    """One JSON document per line."""
    text = _decode(payload)
    records: list[dict[str, Any]] = []
    malformed: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            malformed.append((number, exc.msg))
            continue
        records.append(parsed if isinstance(parsed, dict) else {"value": parsed})
        if limit and len(records) >= limit:
            break

    if not records:
        raise BadRequestError("No line of this file parses as JSON.")

    findings: list[Finding] = [
        certain("json_shape", "jsonl", f"{len(records)} record(s), one JSON object per line.")
    ]
    if malformed:
        findings.append(
            Finding(
                stage="malformed_lines",
                value=len(malformed),
                certainty=Certainty.CERTAIN,
                confidence=1.0,
                reason=(
                    f"{len(malformed)} line(s) are not valid JSON and were skipped. A truncated "
                    "final line is the usual cause when a file was still being written."
                ),
                evidence=[f"line {number}: {message}" for number, message in malformed[:5]],
            )
        )
    return _frame_from(records, findings, {"shape": "jsonl"}, limit)


def read_yaml(
    payload: bytes, *, overrides: dict[str, Any] | None = None, limit: int | None = None
) -> ReadResult:
    import yaml

    try:
        document = yaml.safe_load(_decode(payload))
    except yaml.YAMLError as exc:
        raise BadRequestError(f"Could not parse this as YAML: {exc}") from exc
    if document is None:
        raise BadRequestError("This YAML file is empty.")
    records = document if isinstance(document, list) else [document]
    records = [item if isinstance(item, dict) else {"value": item} for item in records]
    return _frame_from(
        records,
        [certain("json_shape", "yaml", f"A YAML document holding {len(records)} record(s).")],
        {"shape": "yaml"},
        limit,
    )


def _concatenated(text: str) -> list[dict[str, Any]] | None:
    """`{...}{...}` with nothing between them, which is not valid JSON."""
    decoder = json.JSONDecoder()
    records: list[dict[str, Any]] = []
    index = 0
    length = len(text)
    while index < length:
        while index < length and text[index] in " \t\r\n,":
            index += 1
        if index >= length:
            break
        try:
            value, index = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            return None
        records.append(value if isinstance(value, dict) else {"value": value})
    return records or None


def _all_arrays(document: Any, *, depth: int = 0, path: str = "") -> list[tuple[str, int]]:
    if depth > MAX_DEPTH or not isinstance(document, dict):
        return []
    found: list[tuple[str, int]] = []
    for key, value in document.items():
        here = f"{path}.{key}" if path else str(key)
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            found.append((here, len(value)))
        elif isinstance(value, dict):
            found.extend(_all_arrays(value, depth=depth + 1, path=here))
    return sorted(found, key=lambda item: item[1], reverse=True)


def _frame_from(
    records: list[dict[str, Any]],
    findings: list[Finding],
    options: dict[str, Any],
    limit: int | None,
) -> ReadResult:
    """Records to a frame: nested objects dotted, arrays kept as JSON."""
    if limit:
        records = records[:limit]
    frame = pd.json_normalize(records, sep=".", max_level=MAX_DEPTH)

    arrays = [
        column for column in frame.columns
        if frame[column].map(lambda value: isinstance(value, (list, tuple))).any()
    ]
    for column in arrays:
        frame[column] = frame[column].map(
            lambda value: json.dumps(value, default=str) if isinstance(value, (list, tuple)) else value
        )
    if arrays:
        findings.append(
            certain(
                "nested_arrays",
                arrays,
                (
                    f"{len(arrays)} column(s) hold arrays, kept as JSON text. Use the "
                    "'explode' tool to turn one into rows — it changes what a row means, "
                    "so it is a transformation rather than a reading decision."
                ),
                evidence=arrays[:6],
            )
        )

    heterogeneous = _heterogeneity(records)
    if heterogeneous:
        findings.append(
            Finding(
                stage="heterogeneous_records",
                value=len(heterogeneous),
                certainty=Certainty.CERTAIN,
                confidence=1.0,
                reason=(
                    f"{len(heterogeneous)} field(s) are absent from some records. They become "
                    "null where absent, which is what a missing key means."
                ),
                evidence=[f"{name}: in {count} of {len(records)}" for name, count in heterogeneous[:6]],
            )
        )

    return ReadResult(
        frame=normalise_columns(frame), options=options, findings=findings
    )


def _heterogeneity(records: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """Fields that only some records have, which is normal in JSON and not in a table."""
    if len(records) < 2:
        return []
    counts: dict[str, int] = {}
    for record in records[:1000]:
        for key in record:
            counts[key] = counts.get(key, 0) + 1
    total = min(len(records), 1000)
    return sorted(
        ((name, count) for name, count in counts.items() if count < total),
        key=lambda item: item[1],
    )
