"""Finding the dataset you half-remember.

A platform stops being usable at roughly the point where nobody can find
anything in it. Search here is deliberately *not* just a name match: people
remember a column, or a tag, or roughly what a thing was for, far more often
than they remember what somebody called it.

Ranking is by where the match landed. A dataset called "orders" beats one that
merely has an `orders_id` column, and a certified dataset beats an uncertified
one with the same score -- because the certified one is the answer somebody
already checked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# What a match in each place is worth. Relative, not absolute: the only thing
# that matters is the order they produce.
WEIGHT_NAME_EXACT = 100
WEIGHT_NAME_PREFIX = 60
WEIGHT_NAME_CONTAINS = 40
WEIGHT_TAG = 30
WEIGHT_COLUMN = 20
WEIGHT_DESCRIPTION = 10
WEIGHT_GLOSSARY = 25
CERTIFIED_BONUS = 15

MAX_RESULTS = 50
MAX_MATCHED_COLUMNS = 6


@dataclass
class SearchableDataset:
    """A dataset flattened into everything somebody might search by."""

    id: str
    name: str
    description: str | None = None
    columns: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    certified: bool = False
    owner: str | None = None
    row_count: int | None = None
    is_derived: bool = False
    column_notes: dict[str, str] = field(default_factory=dict)


@dataclass
class SearchHit:
    dataset_id: str
    name: str
    score: int
    # Kept apart from `score` because what a dataset is *called* has to outrank
    # what happens to be inside it. Added together, a weak name match plus a few
    # incidental column hits beats a strong name match, and searching "order"
    # returns "order_lines" above "orders".
    name_score: int
    reasons: list[str]
    matched_columns: list[str]
    certified: bool
    owner: str | None
    tags: list[str]
    description: str | None
    row_count: int | None

    @property
    def rank(self) -> tuple[int, int, str]:
        """Sort key: name first, then everything else, then alphabetical."""
        return (-self.name_score, -self.score, self.name.lower())

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "name": self.name,
            "score": self.score,
            "name_score": self.name_score,
            "reasons": self.reasons,
            "matched_columns": self.matched_columns,
            "certified": self.certified,
            "owner": self.owner,
            "tags": self.tags,
            "description": self.description,
            "row_count": self.row_count,
        }


def tokenize(query: str) -> list[str]:
    """Words worth searching for.

    Single characters are dropped: they match nearly everything and rank
    nothing, so they only add noise.
    """
    parts = re.split(r"[^a-z0-9_]+", query.lower())
    return [part for part in parts if len(part) > 1]


def score_dataset(dataset: SearchableDataset, tokens: list[str]) -> SearchHit | None:
    """How well one dataset answers a search, and why."""
    if not tokens:
        return None

    name = dataset.name.lower()
    description = (dataset.description or "").lower()
    tags = [tag.lower() for tag in dataset.tags]
    columns = [column.lower() for column in dataset.columns]

    score = 0
    name_score = 0
    reasons: list[str] = []
    matched_columns: list[str] = []

    for token in tokens:
        if name == token:
            name_score += WEIGHT_NAME_EXACT
            reasons.append(f"named '{dataset.name}'")
        elif name.startswith(token):
            # Scaled by how much of the name the token covers, so "order"
            # finds "orders" before "order_line_adjustments".
            coverage = len(token) / max(len(name), 1)
            name_score += int(WEIGHT_NAME_PREFIX * (0.5 + 0.5 * coverage))
            reasons.append(f"name starts with '{token}'")
        elif token in name:
            name_score += WEIGHT_NAME_CONTAINS
            reasons.append(f"name contains '{token}'")

        if any(token in tag for tag in tags):
            score += WEIGHT_TAG
            reasons.append(f"tagged '{token}'")

        hits = [
            original
            for original, lowered in zip(dataset.columns, columns, strict=True)
            if token in lowered
        ]
        if hits:
            score += WEIGHT_COLUMN
            matched_columns.extend(hits)
            reasons.append(f"has column(s) matching '{token}'")

        if token in description:
            score += WEIGHT_DESCRIPTION
            reasons.append("described with that word")

        if any(token in note.lower() for note in dataset.column_notes.values()):
            score += WEIGHT_DESCRIPTION
            reasons.append("a column note mentions it")

    if score == 0 and name_score == 0:
        return None

    if dataset.certified:
        # Between two equal answers, prefer the one somebody has checked.
        score += CERTIFIED_BONUS
        name_score += CERTIFIED_BONUS
        reasons.append("certified")

    return SearchHit(
        dataset_id=dataset.id,
        name=dataset.name,
        score=score + name_score,
        name_score=name_score,
        reasons=list(dict.fromkeys(reasons)),
        matched_columns=list(dict.fromkeys(matched_columns))[:MAX_MATCHED_COLUMNS],
        certified=dataset.certified,
        owner=dataset.owner,
        tags=dataset.tags,
        description=dataset.description,
        row_count=dataset.row_count,
    )


def search(
    datasets: list[SearchableDataset],
    query: str,
    *,
    limit: int = MAX_RESULTS,
    certified_only: bool = False,
    tag: str | None = None,
) -> list[SearchHit]:
    """Rank datasets against a search.

    An empty query lists everything rather than nothing -- a catalog people can
    only use by already knowing what to type is not a catalog.
    """
    candidates = datasets
    if certified_only:
        candidates = [dataset for dataset in candidates if dataset.certified]
    if tag:
        wanted = tag.lower()
        candidates = [
            dataset
            for dataset in candidates
            if any(wanted == existing.lower() for existing in dataset.tags)
        ]

    tokens = tokenize(query)
    if not tokens:
        browsing = [
            SearchHit(
                dataset_id=dataset.id,
                name=dataset.name,
                score=CERTIFIED_BONUS if dataset.certified else 0,
                name_score=CERTIFIED_BONUS if dataset.certified else 0,
                reasons=["certified"] if dataset.certified else [],
                matched_columns=[],
                certified=dataset.certified,
                owner=dataset.owner,
                tags=dataset.tags,
                description=dataset.description,
                row_count=dataset.row_count,
            )
            for dataset in candidates
        ]
        browsing.sort(key=lambda hit: hit.rank)
        return browsing[:limit]

    hits = [
        hit for hit in (score_dataset(dataset, tokens) for dataset in candidates) if hit is not None
    ]
    hits.sort(key=lambda hit: hit.rank)
    return hits[:limit]


def slugify(term: str) -> str:
    """A stable key for a glossary term."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")
    return cleaned or "term"
