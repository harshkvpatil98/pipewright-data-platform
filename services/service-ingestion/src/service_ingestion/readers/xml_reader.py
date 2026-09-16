"""XML, where the question is which element is a row.

A document has one repeated element that represents a record and a lot of
structure around it. `<invoices><invoice/><invoice/></invoices>` is obvious;
`<soap:Envelope><soap:Body><GetOrdersResponse><Orders><Order/>…` is the same
shape buried four levels down, and that is what actually arrives.

So the record element is found by looking for the deepest element that repeats,
reported with the alternatives, and overridable. Attributes become columns
prefixed `@`, because `<order id="7">` carries its id in an attribute and
dropping attributes loses the key.

`xml.etree` rather than `lxml`, which is not installed. Entity expansion is
disabled either way: an XML file from outside can declare entities that expand
exponentially (the "billion laughs" attack), and a parser that resolves them
is a way to exhaust memory with a 1KB file.
"""

from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree

import pandas as pd

from shared_python.errors import BadRequestError

from service_ingestion.readers.base import ReadResult, normalise_columns
from service_ingestion.sniff.evidence import Candidate, Certainty, Finding, certain

#: Namespace prefix in a tag: `{http://...}Order`. Stripped for column names,
#: reported once so the namespace is not simply lost.
_NAMESPACE = re.compile(r"^\{([^}]*)\}(.+)$")

#: A DTD is the vector for entity-expansion attacks and carries nothing this
#: reader needs.
_DOCTYPE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)


def _local(tag: str) -> tuple[str, str | None]:
    match = _NAMESPACE.match(tag)
    if match:
        return match.group(2), match.group(1)
    return tag, None


def _flatten(element: Any, prefix: str = "", out: dict[str, Any] | None = None) -> dict[str, Any]:
    """One record element as a flat mapping.

    Children become dotted names, attributes get an `@`, and a repeated child
    becomes `name[0]`, `name[1]` rather than one of them overwriting the other.
    """
    row: dict[str, Any] = {} if out is None else out
    for key, value in element.attrib.items():
        name, _ = _local(key)
        row[f"{prefix}@{name}" if prefix else f"@{name}"] = value

    seen: dict[str, int] = {}
    children = list(element)
    if not children:
        text = (element.text or "").strip()
        if text or not element.attrib:
            row[prefix.rstrip(".") or "value"] = text
        return row

    for child in children:
        name, _ = _local(child.tag)
        index = seen.get(name, 0)
        seen[name] = index + 1
        repeats = sum(1 for other in children if _local(other.tag)[0] == name) > 1
        label = f"{name}[{index}]" if repeats else name
        _flatten(child, f"{prefix}{label}." if prefix else f"{label}.", row)
    return row


def _candidates(root: Any) -> list[tuple[str, int, int]]:
    """Every element name that repeats, with how often and how deep."""
    counts: dict[tuple[str, int], int] = {}

    def walk(element: Any, depth: int) -> None:
        children = list(element)
        grouped: dict[str, int] = {}
        for child in children:
            name, _ = _local(child.tag)
            grouped[name] = grouped.get(name, 0) + 1
        for name, count in grouped.items():
            if count > 1:
                key = (name, depth + 1)
                counts[key] = max(counts.get(key, 0), count)
        for child in children:
            walk(child, depth + 1)

    walk(root, 0)
    return sorted(
        ((name, count, depth) for (name, depth), count in counts.items()),
        key=lambda item: (-item[1], item[2]),
    )


def read_xml(
    payload: bytes, *, overrides: dict[str, Any] | None = None, limit: int | None = None
) -> ReadResult:
    overrides = dict(overrides or {})

    if _DOCTYPE.search(payload[:4096]):
        raise BadRequestError(
            "This XML declares a DOCTYPE. Document type definitions can declare entities "
            "that expand to exhaust memory, so they are not processed. Remove the DOCTYPE "
            "and upload again."
        )

    parser = ElementTree.XMLParser()
    try:
        root = ElementTree.fromstring(payload, parser=parser)
    except ElementTree.ParseError as exc:
        raise BadRequestError(f"Could not parse this XML: {exc}") from exc

    findings: list[Finding] = []
    _, namespace = _local(root.tag)
    if namespace:
        findings.append(
            certain(
                "xml_namespace",
                namespace,
                (
                    f"The document uses the namespace {namespace}. Prefixes are stripped from "
                    "column names, which are otherwise unusable."
                ),
            )
        )

    ranked = _candidates(root)
    requested = overrides.get("record_element")
    if requested:
        record_name = str(requested)
        findings.append(
            certain("record_element", record_name, "Record element supplied with the file.")
        )
    elif ranked:
        record_name = ranked[0][0]
        findings.append(
            Finding(
                stage="record_element",
                value=record_name,
                certainty=Certainty.LIKELY if len(ranked) == 1 else Certainty.UNCERTAIN,
                confidence=0.9 if len(ranked) == 1 else 0.65,
                reason=(
                    f"<{record_name}> repeats {ranked[0][1]} times, so each one is a row"
                    + (
                        f". {len(ranked) - 1} other element(s) also repeat; change this if one "
                        "of those is the record."
                        if len(ranked) > 1
                        else "."
                    )
                ),
                candidates=[
                    Candidate(name, count / max(ranked[0][1], 1), f"repeats {count} times at depth {depth}")
                    for name, count, depth in ranked[:5]
                ],
            )
        )
    else:
        record_name = _local(root.tag)[0]
        findings.append(
            Finding(
                stage="record_element",
                value=record_name,
                certainty=Certainty.UNCERTAIN,
                confidence=0.4,
                reason=(
                    "No element repeats, so this document holds a single record rather "
                    "than a table."
                ),
            )
        )

    records = [
        element for element in root.iter() if _local(element.tag)[0] == record_name
    ]
    if not records and _local(root.tag)[0] == record_name:
        records = [root]
    if not records:
        raise BadRequestError(f"No <{record_name}> element was found in this document.")

    if limit:
        records = records[:limit]

    rows = [_flatten(element) for element in records]
    frame = normalise_columns(pd.DataFrame(rows))

    attributes = [column for column in frame.columns if "@" in str(column)]
    if attributes:
        findings.append(
            certain(
                "xml_attributes",
                attributes,
                (
                    f"{len(attributes)} column(s) come from attributes rather than elements, "
                    "marked with @. Identifiers usually live there."
                ),
                evidence=attributes[:6],
            )
        )

    return ReadResult(
        frame=frame,
        options={"record_element": record_name},
        findings=findings,
        tables=[name for name, _, _ in ranked[:10]],
    )
