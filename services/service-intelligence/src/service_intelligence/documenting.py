"""Writing the description nobody was ever going to write.

A catalog full of datasets with no descriptions is a catalog nobody searches.
The reason those descriptions do not exist is not that people disagree about
them -- it is that writing forty of them is a day's work with no visible reward.

So this generates a first draft from what is already known: the profile says how
many rows and what shape they are, lineage says where the columns came from, and
the quality rules say what has been asserted about them. Every sentence is a
fact that was already recorded; nothing is invented.

The output is explicitly a draft. It is offered for a person to accept or edit,
because a generated description presented as authoritative is how a catalog
fills up with confidently wrong text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DatasetFacts:
    """Everything already known about a dataset, from elsewhere."""

    name: str
    row_count: int | None = None
    column_count: int | None = None
    columns: list[str] = field(default_factory=list)
    completeness: float | None = None
    duplicate_percentage: float | None = None
    is_derived: bool = False
    source_name: str | None = None
    produced_by: str | None = None
    upstream_names: list[str] = field(default_factory=list)
    high_null_columns: list[str] = field(default_factory=list)
    identifier_columns: list[str] = field(default_factory=list)
    rule_count: int = 0
    certified: bool = False


@dataclass
class ColumnFacts:
    name: str
    inferred_type: str | None = None
    null_percentage: float | None = None
    unique_count: int | None = None
    row_count: int | None = None
    sample_values: list[Any] = field(default_factory=list)
    possible_identifier: bool = False
    origin: str | None = None
    pii_kind: str | None = None


@dataclass
class Draft:
    subject: str
    text: str
    facts_used: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"subject": self.subject, "text": self.text, "facts_used": self.facts_used}


def describe_dataset(facts: DatasetFacts) -> Draft:
    """A paragraph about a dataset, assembled from what is already recorded."""
    sentences: list[str] = []
    used: list[str] = []

    if facts.is_derived and facts.produced_by:
        origin = f"produced by the '{facts.produced_by}' pipeline"
        if facts.upstream_names:
            origin += f" from {_join(facts.upstream_names)}"
        sentences.append(f"{facts.name} is {origin}.")
        used.append("lineage")
    elif facts.source_name:
        sentences.append(f"{facts.name} is loaded from {facts.source_name}.")
        used.append("source")
    else:
        sentences.append(f"{facts.name} was uploaded directly.")

    if facts.row_count is not None and facts.column_count is not None:
        sentences.append(
            f"It holds {facts.row_count:,} rows across {facts.column_count} columns."
        )
        used.append("profile")

    if facts.identifier_columns:
        sentences.append(
            f"{_join([f'`{column}`' for column in facts.identifier_columns[:3]])} "
            f"{'looks' if len(facts.identifier_columns) == 1 else 'look'} like "
            f"{'an identifier' if len(facts.identifier_columns) == 1 else 'identifiers'}."
        )
        used.append("profile")

    quality = _quality_sentence(facts)
    if quality:
        sentences.append(quality)
        used.append("profile")

    if facts.rule_count:
        sentences.append(
            f"{facts.rule_count} quality rule{'s' if facts.rule_count != 1 else ''} "
            f"{'are' if facts.rule_count != 1 else 'is'} checked against it."
        )
        used.append("quality rules")

    if facts.certified:
        sentences.append("It has been certified by someone as fit to rely on.")
        used.append("catalog")

    return Draft(subject=facts.name, text=" ".join(sentences), facts_used=sorted(set(used)))


def _quality_sentence(facts: DatasetFacts) -> str | None:
    parts: list[str] = []
    if facts.completeness is not None and facts.completeness < 99.5:
        parts.append(f"{facts.completeness:.1f}% of cells are filled in")
    if facts.duplicate_percentage:
        parts.append(f"{facts.duplicate_percentage:.1f}% of rows are duplicates")
    if facts.high_null_columns:
        parts.append(
            f"{_join([f'`{column}`' for column in facts.high_null_columns[:3]])} "
            f"{'is' if len(facts.high_null_columns) == 1 else 'are'} mostly empty"
        )
    if not parts:
        return None
    return _sentence_case(_join(parts) + ".")


def describe_column(facts: ColumnFacts) -> Draft:
    """A line about one column."""
    sentences: list[str] = []
    used: list[str] = []

    if facts.origin:
        sentences.append(f"Comes from {facts.origin}.")
        used.append("lineage")

    if facts.inferred_type:
        sentences.append(f"Holds {_type_phrase(facts.inferred_type)}.")
        used.append("schema")

    if facts.possible_identifier:
        sentences.append("Looks like an identifier: every row has a different value.")
        used.append("profile")
    elif facts.unique_count is not None and facts.row_count:
        share = facts.unique_count / facts.row_count
        if share <= 0.05:
            sentences.append(
                f"Only {facts.unique_count} distinct value"
                f"{'s' if facts.unique_count != 1 else ''}, so it reads as a category."
            )
            used.append("profile")

    if facts.null_percentage:
        if facts.null_percentage >= 50:
            sentences.append(f"Empty in {facts.null_percentage:.0f}% of rows.")
        elif facts.null_percentage >= 1:
            sentences.append(f"Missing in {facts.null_percentage:.0f}% of rows.")
        used.append("profile")

    if facts.pii_kind:
        # Worth stating plainly: it changes what may be done with the column.
        sentences.append(f"Looks like personal data ({facts.pii_kind.replace('_', ' ')}).")
        used.append("pii scan")

    if facts.sample_values:
        shown = ", ".join(repr(value) for value in facts.sample_values[:3])
        sentences.append(f"For example: {shown}.")
        used.append("profile")

    if not sentences:
        sentences.append("Nothing is recorded about this column yet.")

    return Draft(subject=facts.name, text=" ".join(sentences), facts_used=sorted(set(used)))


def _type_phrase(inferred: str) -> str:
    return {
        "int": "whole numbers",
        "float": "decimal numbers",
        "string": "text",
        "bool": "true or false",
        "boolean": "true or false",
        "datetime": "dates and times",
        "empty": "no values at all",
        "mixed": "a mix of types, which is usually a problem upstream",
    }.get(inferred, inferred)


def _join(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _sentence_case(text: str) -> str:
    return text[0].upper() + text[1:] if text else text
