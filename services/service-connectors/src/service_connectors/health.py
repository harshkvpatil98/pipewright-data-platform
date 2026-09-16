"""Connector operations, at two hundred connectors.

With nineteen, "which connectors do we have" is a list somebody reads. With two
hundred it is a question that needs an answer with shape: how many are usable
here, how many are merely declared, what would it take to make more of them
work, and which of the ones in use have stopped working.

Two things live here:

* :func:`overview` -- the catalogue's own state, computed from the registry. It
  needs no database and no run history, because it answers "what could this
  deployment reach" rather than "what has it reached".
* :func:`usage` -- what is actually configured and how it has been going,
  computed from the extraction service's connections and jobs. It needs a
  database, and degrades to the catalogue view without one rather than failing.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from service_connectors.formats import FORMATS
from service_connectors.protocol import CATEGORIES, Tier
from service_connectors.registry import specs


@dataclass
class TierSummary:
    tier: int
    label: str
    badge: str
    explanation: str
    count: int
    verified: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "label": self.label,
            "badge": self.badge,
            "explanation": self.explanation,
            "count": self.count,
            "verified": self.verified,
        }


@dataclass
class CategorySummary:
    category: str
    total: int
    available: int
    verified: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "total": self.total,
            "available": self.available,
            "verified": self.verified,
        }


@dataclass
class Overview:
    total: int
    available: int
    verified: int
    tiers: list[TierSummary] = field(default_factory=list)
    categories: list[CategorySummary] = field(default_factory=list)
    origins: dict[str, int] = field(default_factory=dict)
    #: What would have to be installed to make more of the catalogue usable,
    #: and how many connectors each package unlocks. The single most useful
    #: number for somebody setting a deployment up.
    missing_packages: list[dict[str, Any]] = field(default_factory=list)
    formats: int = 0
    store_format_combinations: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "available": self.available,
            "verified": self.verified,
            "tiers": [tier.to_dict() for tier in self.tiers],
            "categories": [category.to_dict() for category in self.categories],
            "origins": dict(self.origins),
            "missing_packages": list(self.missing_packages),
            "formats": self.formats,
            "store_format_combinations": self.store_format_combinations,
        }


def overview() -> Overview:
    """The catalogue's state, as the health view shows it."""
    from service_connectors.stores import combinations

    catalogue = specs()
    by_tier = Counter(spec.tier for spec in catalogue)
    missing: Counter[str] = Counter()
    for spec in catalogue:
        if not spec.available and spec.driver_package:
            missing[spec.driver_package] += 1

    categories: list[CategorySummary] = []
    for category in CATEGORIES:
        entries = [spec for spec in catalogue if spec.category == category]
        if not entries:
            continue
        categories.append(
            CategorySummary(
                category=category,
                total=len(entries),
                available=sum(1 for spec in entries if spec.available),
                verified=sum(1 for spec in entries if spec.tier.verified),
            )
        )

    return Overview(
        total=len(catalogue),
        available=sum(1 for spec in catalogue if spec.available),
        verified=sum(1 for spec in catalogue if spec.tier.verified),
        tiers=[
            TierSummary(
                tier=int(tier),
                label=tier.label,
                badge=tier.badge,
                explanation=tier.explanation,
                count=by_tier.get(tier, 0),
                verified=tier.verified,
            )
            for tier in Tier
        ],
        categories=categories,
        origins=dict(Counter(spec.origin for spec in catalogue)),
        missing_packages=[
            {"package": package, "unlocks": count}
            for package, count in missing.most_common()
        ],
        formats=len(FORMATS),
        store_format_combinations=combinations(),
    )


@dataclass
class ConnectorUsage:
    """One connector type, and how the connections using it have been going."""

    connector_type: str
    label: str
    tier: int
    tier_label: str
    available: bool
    connections: int
    last_tested_at: str | None = None
    last_test_status: str | None = None
    failing: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_type": self.connector_type,
            "label": self.label,
            "tier": self.tier,
            "tier_label": self.tier_label,
            "available": self.available,
            "connections": self.connections,
            "last_tested_at": self.last_tested_at,
            "last_test_status": self.last_test_status,
            "failing": self.failing,
        }


def usage(db: Any, project_id: Any = None) -> list[ConnectorUsage]:
    """Which connectors are actually configured, and how they are faring.

    Reads the extraction service's saved connections, because that is where a
    configured connector lives. A connector nobody has configured does not
    appear -- the catalogue view above is the place to see those.
    """
    from sqlalchemy import select

    from service_extraction.models import ExtractionConnection

    query = select(ExtractionConnection)
    if project_id is not None:
        query = query.where(ExtractionConnection.project_id == project_id)
    connections = list(db.scalars(query).all())

    by_type: dict[str, list[Any]] = {}
    for connection in connections:
        by_type.setdefault(connection.connector_type, []).append(connection)

    catalogue = {spec.type: spec for spec in specs()}
    rows: list[ConnectorUsage] = []
    for connector_type, entries in by_type.items():
        spec = catalogue.get(connector_type)
        latest = max(
            (entry for entry in entries if entry.last_tested_at is not None),
            key=lambda entry: entry.last_tested_at,
            default=None,
        )
        rows.append(
            ConnectorUsage(
                connector_type=connector_type,
                label=spec.label if spec else connector_type,
                tier=int(spec.tier) if spec else int(Tier.SPEC_ONLY),
                tier_label=spec.tier.label if spec else Tier.SPEC_ONLY.label,
                available=bool(spec.available) if spec else False,
                connections=len(entries),
                last_tested_at=latest.last_tested_at.isoformat() if latest else None,
                last_test_status=latest.last_test_status if latest else None,
                failing=sum(1 for entry in entries if entry.last_test_status == "failed"),
            )
        )
    rows.sort(key=lambda row: (-row.failing, row.label.lower()))
    return rows
