"""The transformation tool library.

One `tool` step type covers every tool in the catalogue. That is deliberate:
adding a tool must not mean touching the step vocabulary, the validator, the
lineage table and the UI catalogue in four separate places -- which is exactly
how a library of hundreds becomes impossible to keep consistent.

Import this package for its side effect: the category modules register
themselves on import, and :data:`TOOLS` is the whole library.
"""

from __future__ import annotations

import re
from typing import Any

from shared_python.errors import BadRequestError
from shared_python.types import PWType

from service_transformations.ir.nodes import Node
from service_transformations.tools.spec import (
    Accepts,
    Example,
    Param,
    ParamKind,
    ToolSpec,
)

#: Words that carry no signal in a tool search. Without this, "extract year
#: from date" finds nothing, because "from" is in no tool's vocabulary.
_STOPWORDS = frozenset({
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on",
    "or", "the", "to", "with",
})

#: Every registered tool, by name. Ordered by registration, which is category
#: order, so the catalogue reads the way the UI groups it.
TOOLS: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    if spec.name in TOOLS:
        raise ValueError(f"Two tools are named {spec.name!r}.")
    TOOLS[spec.name] = spec
    return spec


def get(name: str) -> ToolSpec:
    spec = TOOLS.get(name)
    if spec is None:
        raise BadRequestError(
            f"There is no tool called {name!r}. "
            "See GET /transformations/tools for the catalogue."
        )
    return spec


def categories() -> list[str]:
    seen: list[str] = []
    for spec in TOOLS.values():
        if spec.category not in seen:
            seen.append(spec.category)
    return seen


def applicable_to(type_: PWType) -> list[ToolSpec]:
    """The column-scoped tools worth offering on a column of this type."""
    return [spec for spec in TOOLS.values() if spec.column_scoped and spec.accepts.matches(type_)]


def build(node: Node, config: dict[str, Any]) -> Node:
    """Compile one `tool` step config into IR."""
    name = config.get("tool")
    if not isinstance(name, str) or not name:
        raise BadRequestError("A tool step must name a tool.")
    spec = get(name)
    params = spec.resolve(config)
    params["column"] = config.get("column")
    params["into"] = config.get("into")
    return spec.build(node, params)


def search(query: str, limit: int = 25) -> list[ToolSpec]:
    """Rank tools by name, title and synonym against a query.

    Every word in the query has to match something, and the score is the sum --
    so "zip code" finds the tool whose synonym is "zip" and whose title mentions
    codes, while "zip banana" finds nothing. Requiring every word is what keeps
    a second word useful: with an any-word rule, adding detail to a query makes
    the results worse, which is the opposite of what typing more should do.

    Synonyms carry most of the weight. Nobody searches for "initcap"; they
    search for "title case", and a catalogue of hundreds is only as good as the
    words people actually reach for.
    """
    words = [
        word for word in re.split(r"[^a-z0-9]+", query.strip().lower()) if word and word not in _STOPWORDS
    ]
    if not words:
        return list(TOOLS.values())[:limit]

    scored: list[tuple[int, ToolSpec]] = []
    for spec in TOOLS.values():
        haystacks = (
            (spec.title.lower(), 100),
            (spec.name.lower().replace(".", " ").replace("_", " "), 90),
            *((synonym.lower(), 80) for synonym in spec.synonyms),
            (spec.category.lower(), 30),
            (spec.summary.lower(), 20),
        )
        total = 0
        for word in words:
            best = 0
            for text, weight in haystacks:
                if text == word:
                    best = max(best, weight + 50)
                elif re.search(rf"\b{re.escape(word)}", text):
                    # A word boundary, not just a substring: "phone" should
                    # find "Standardise a phone number" ahead of a tool whose
                    # summary happens to contain "phonetic".
                    best = max(best, weight + 25)
                elif word in text:
                    best = max(best, weight)
            if best == 0:
                total = 0
                break
            total += best
        if total:
            scored.append((total, spec))

    scored.sort(key=lambda pair: (-pair[0], pair[1].name))
    return [spec for _, spec in scored[:limit]]


def _load() -> None:
    # Imported for their registration side effects. Listed rather than
    # discovered so the order -- and therefore the catalogue order -- is
    # something somebody chose.
    from service_transformations.tools.catalogue import (  # noqa: F401
        cleansing,
        columns,
        conversions,
        datetimes,
        encoding,
        nulls,
        numeric,
        rows,
        text,
        validation,
    )


_load()

__all__ = [
    "Accepts",
    "Example",
    "Param",
    "ParamKind",
    "TOOLS",
    "ToolSpec",
    "applicable_to",
    "build",
    "categories",
    "get",
    "register",
    "search",
]
