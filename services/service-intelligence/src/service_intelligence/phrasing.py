"""Turning a typed sentence into pipeline steps.

**This is a phrase parser, not a language model.** It recognises a specific set
of ways people write these requests and maps them onto the transformation steps
the engine already has. It does not understand English, and pretending otherwise
would be the worst possible property for a feature that edits somebody's data.

Two consequences follow from that, and both are deliberate:

* **Anything it does not recognise is reported, never dropped.** A parser that
  silently ignores half a sentence produces a pipeline that does half of what
  was asked, and the person only finds out from the numbers.
* **Column names are checked against the dataset.** "total revenue by region"
  is only a valid request if `revenue` and `region` exist; otherwise the answer
  is which columns *do* exist, not a step that fails at run time.

The result is a proposal. Nothing is applied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

# The aggregations a sentence can name, and what the engine calls them.
AGGREGATION_WORDS: dict[str, str] = {
    "total": "sum",
    "sum": "sum",
    "add up": "sum",
    "average": "avg",
    "avg": "avg",
    "mean": "avg",
    "count": "count",
    "number of": "count",
    "how many": "count",
    "maximum": "max",
    "max": "max",
    "highest": "max",
    "largest": "max",
    "minimum": "min",
    "min": "min",
    "lowest": "min",
    "smallest": "min",
    "median": "median",
    "distinct": "count_distinct",
    "unique": "count_distinct",
}

COMPARISON_WORDS: dict[str, str] = {
    "is not": "not_equals",
    "is": "equals",
    "equals": "equals",
    "=": "equals",
    "greater than": "greater_than",
    "more than": "greater_than",
    "over": "greater_than",
    "above": "greater_than",
    ">": "greater_than",
    "less than": "less_than",
    "under": "less_than",
    "below": "less_than",
    "<": "less_than",
    "contains": "contains",
    "includes": "contains",
}

# Words that carry no instruction and only get in the way of matching.
_FILLER = frozenset(
    {"the", "a", "an", "of", "for", "please", "then", "and", "with", "in", "column", "columns", "field"}
)


@dataclass
class ParsedIntent:
    """One thing the sentence asked for."""

    action: str
    step: dict[str, Any]
    phrase: str
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "step": self.step,
            "phrase": self.phrase,
            "explanation": self.explanation,
        }


@dataclass
class ParseResult:
    steps: list[dict[str, Any]] = field(default_factory=list)
    understood: list[ParsedIntent] = field(default_factory=list)
    not_understood: list[str] = field(default_factory=list)
    unknown_columns: list[str] = field(default_factory=list)
    summary: str = ""

    @property
    def complete(self) -> bool:
        return bool(self.understood) and not self.not_understood and not self.unknown_columns

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": self.steps,
            "understood": [item.to_dict() for item in self.understood],
            "not_understood": self.not_understood,
            "unknown_columns": self.unknown_columns,
            "complete": self.complete,
            "summary": self.summary,
        }


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _match_column(word: str, columns: Sequence[str]) -> str | None:
    """Find the column a phrase refers to, allowing for how people write them."""
    target = re.sub(r"[^a-z0-9]", "", word.lower())
    if not target:
        return None
    for column in columns:
        if re.sub(r"[^a-z0-9]", "", column.lower()) == target:
            return column
    # A single-word request for a multi-word column: "revenue" for "net_revenue".
    matches = [
        column
        for column in columns
        if target in re.sub(r"[^a-z0-9]", "", column.lower())
    ]
    return matches[0] if len(matches) == 1 else None


# Words that begin a new request. "and" only separates when one of these
# follows it -- splitting on every "and" would break "where a is x and y".
_VERBS = (
    "remove", "drop", "delete", "rename", "sort", "order", "keep", "filter",
    "exclude", "total", "sum", "average", "avg", "mean", "count", "median",
    "deduplicate", "dedupe", "show", "group",
)

_CLAUSE_BOUNDARY = re.compile(
    r"\s*(?:,|;|\bthen\b|\band\s+then\b|\band\b(?=\s+(?:" + "|".join(_VERBS) + r")\b))\s*"
)


def _split_clauses(sentence: str) -> list[str]:
    """Break a sentence into the separate requests it contains.

    Getting this wrong is not cosmetic: a clause that is swallowed by its
    neighbour is a request silently dropped, and the person finds out from the
    numbers rather than from the screen.
    """
    parts = _CLAUSE_BOUNDARY.split(sentence)
    return [part.strip() for part in parts if part.strip()]


def parse(sentence: str, columns: Sequence[str]) -> ParseResult:
    """Read a request and propose the steps that answer it."""
    result = ParseResult()
    cleaned = _clean(sentence)
    if not cleaned:
        result.summary = "Nothing to read."
        return result

    for clause in _split_clauses(cleaned):
        intent = (
            _parse_aggregate(clause, columns, result)
            or _parse_filter(clause, columns, result)
            or _parse_drop(clause, columns, result)
            or _parse_rename(clause, columns, result)
            or _parse_deduplicate(clause)
            or _parse_sort(clause, columns, result)
        )
        if intent is None:
            result.not_understood.append(clause)
        else:
            result.understood.append(intent)
            result.steps.append(intent.step)

    result.summary = _summarise(result, columns)
    return result


def _remember_unknown(result: ParseResult, word: str) -> None:
    if word and word not in result.unknown_columns:
        result.unknown_columns.append(word)


def _parse_aggregate(
    clause: str, columns: Sequence[str], result: ParseResult
) -> ParsedIntent | None:
    """'total amount by region', 'average price grouped by category'."""
    grouping = re.search(r"\b(?:by|per|grouped by|group by)\b\s+(.+)$", clause)
    if not grouping:
        return None

    word = next(
        (
            key
            for key in sorted(AGGREGATION_WORDS, key=len, reverse=True)
            if re.search(rf"\b{re.escape(key)}\b", clause)
        ),
        None,
    )
    if word is None:
        return None

    aggregation = AGGREGATION_WORDS[word]
    head = clause[: grouping.start()]
    head = re.sub(rf"\b{re.escape(word)}\b", " ", head)
    measure_word = _last_meaningful_word(head)
    dimension_word = _first_meaningful_word(grouping.group(1))

    measure = _match_column(measure_word, columns) if measure_word else None
    dimension = _match_column(dimension_word, columns) if dimension_word else None

    if dimension is None:
        _remember_unknown(result, dimension_word or "")
        return None
    if measure is None:
        if aggregation != "count":
            _remember_unknown(result, measure_word or "")
            return None
        measure = dimension  # "how many by region" counts the grouping itself.

    return ParsedIntent(
        action="aggregate",
        step={
            "step_type": "aggregate",
            "config": {
                "group_by": [dimension],
                "aggregations": [
                    {
                        "column": measure,
                        "function": aggregation,
                        "alias": f"{aggregation}_{measure}",
                    }
                ],
            },
        },
        phrase=clause,
        explanation=f"Group by '{dimension}' and take the {aggregation} of '{measure}'.",
    )


def _parse_filter(
    clause: str, columns: Sequence[str], result: ParseResult
) -> ParsedIntent | None:
    """'where channel is web', 'keep rows with amount over 100'.

    Several conditions joined by "and" become several conditions on one step,
    not one condition whose value swallowed the rest of the sentence.
    """
    if not re.search(r"\b(where|only|keep|filter|exclude|remove rows)\b", clause):
        return None

    negated = bool(re.search(r"\b(exclude|remove rows)\b", clause))
    body = re.sub(r"^.*?\b(?:where|with)\b\s*", "", clause) if re.search(r"\b(where|with)\b", clause) else clause

    conditions: list[dict[str, Any]] = []
    explanations: list[str] = []

    for part in re.split(r"\s+and\s+", body):
        parsed = _parse_condition(part.strip(), columns, result, negated=negated)
        if parsed is None:
            continue
        condition, explanation = parsed
        conditions.append(condition)
        explanations.append(explanation)

    if not conditions:
        return None

    return ParsedIntent(
        action="filter",
        step={"step_type": "filter_rows", "config": {"conditions": conditions}},
        phrase=clause,
        explanation="Keep rows where " + " and ".join(explanations) + ".",
    )


def _parse_condition(
    part: str, columns: Sequence[str], result: ParseResult, *, negated: bool
) -> tuple[dict[str, Any], str] | None:
    for phrase in sorted(COMPARISON_WORDS, key=len, reverse=True):
        match = re.search(rf"(\w+)\s+{re.escape(phrase)}\s+(.+)$", part)
        if not match:
            continue

        column = _match_column(match.group(1), columns)
        if column is None:
            _remember_unknown(result, match.group(1))
            return None

        raw_value = match.group(2).strip().strip("'\"")
        value: Any = raw_value
        if re.fullmatch(r"-?\d+", raw_value):
            value = int(raw_value)
        elif re.fullmatch(r"-?\d*\.\d+", raw_value):
            value = float(raw_value)

        operator = COMPARISON_WORDS[phrase]
        if negated and operator == "equals":
            operator = "not_equals"

        return (
            {"column": column, "operator": operator, "value": value},
            f"'{column}' {operator.replace('_', ' ')} {value!r}",
        )
    return None


def _parse_drop(clause: str, columns: Sequence[str], result: ParseResult) -> ParsedIntent | None:
    """'drop the notes column', 'remove internal_id'."""
    match = re.search(r"\b(?:drop|remove|delete)\b\s+(.+)$", clause)
    if not match or "duplicate" in clause or "rows" in clause:
        return None

    words = [word for word in re.split(r"[^a-z0-9_]+", match.group(1)) if word and word not in _FILLER]
    wanted = [(_match_column(word, columns), word) for word in words]
    resolved = [column for column, _word in wanted if column]
    if not resolved:
        for _column, word in wanted:
            _remember_unknown(result, word)
        return None

    return ParsedIntent(
        action="drop_columns",
        step={"step_type": "drop_columns", "config": {"columns": resolved}},
        phrase=clause,
        explanation=f"Remove {', '.join(repr(column) for column in resolved)}.",
    )


def _parse_rename(clause: str, columns: Sequence[str], result: ParseResult) -> ParsedIntent | None:
    """'rename amount to revenue'."""
    match = re.search(r"\brename\b\s+(\w+)\s+(?:to|as)\s+(\w+)", clause)
    if not match:
        return None

    column = _match_column(match.group(1), columns)
    if column is None:
        _remember_unknown(result, match.group(1))
        return None

    return ParsedIntent(
        action="rename_columns",
        step={
            "step_type": "rename_columns",
            "config": {"mappings": {column: match.group(2)}},
        },
        phrase=clause,
        explanation=f"Rename '{column}' to '{match.group(2)}'.",
    )


def _parse_deduplicate(clause: str) -> ParsedIntent | None:
    """'remove duplicates', 'deduplicate'."""
    if not re.search(r"\b(deduplicate|dedupe|duplicates?)\b", clause):
        return None
    return ParsedIntent(
        action="remove_duplicates",
        step={"step_type": "remove_duplicates", "config": {}},
        phrase=clause,
        explanation="Remove rows that are identical across every column.",
    )


def _parse_sort(clause: str, columns: Sequence[str], result: ParseResult) -> ParsedIntent | None:
    """'sort by amount descending', 'order by name'."""
    match = re.search(r"\b(?:sort|order)\s+by\b\s+(.+)$", clause)
    if not match:
        return None

    tail = match.group(1)
    descending = bool(re.search(r"\b(desc|descending|highest first|largest first)\b", tail))
    word = _first_meaningful_word(tail)
    column = _match_column(word, columns) if word else None
    if column is None:
        _remember_unknown(result, word or "")
        return None

    return ParsedIntent(
        action="sort_rows",
        step={
            "step_type": "sort_rows",
            "config": {"columns": [column], "ascending": not descending},
        },
        phrase=clause,
        explanation=f"Sort by '{column}', {'highest' if descending else 'lowest'} first.",
    )


def _first_meaningful_word(text: str) -> str | None:
    for word in re.split(r"[^a-z0-9_]+", text):
        if word and word not in _FILLER:
            return word
    return None


def _last_meaningful_word(text: str) -> str | None:
    words = [word for word in re.split(r"[^a-z0-9_]+", text) if word and word not in _FILLER]
    return words[-1] if words else None


def _summarise(result: ParseResult, columns: Sequence[str]) -> str:
    if result.unknown_columns:
        unknown = ", ".join(f"'{word}'" for word in result.unknown_columns)
        available = ", ".join(columns[:8]) + ("…" if len(columns) > 8 else "")
        return (
            f"No column called {unknown}. This dataset has: {available}."
        )
    if not result.understood:
        return (
            "None of that matched something this can build. It recognises phrases like "
            "'total amount by region', 'where channel is web', 'remove duplicates', "
            "'drop notes', and 'sort by amount descending'."
        )
    if result.not_understood:
        missed = "; ".join(f"'{phrase}'" for phrase in result.not_understood)
        return (
            f"Built {len(result.steps)} step(s). Could not read: {missed} — "
            "that part was left out rather than guessed at."
        )
    return f"Built {len(result.steps)} step(s) from that."
