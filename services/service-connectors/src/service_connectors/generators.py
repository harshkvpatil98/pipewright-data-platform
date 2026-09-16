"""Where the catalogue actually comes from.

Three generators, one import. Each turns a table of declarations into working
connectors, and each refuses to produce one it cannot describe honestly:

* **manifests** -- a YAML file per SaaS API, validated on load;
* **dialects** -- a row per SQL database, whose capabilities narrow to `test`
  when the driver is missing;
* **stores** -- object stores, real code where they speak the S3 API and a
  declaration with an install hint where they do not;
* **declared engines** -- the wide-column, key-value and filesystem engines
  this platform cannot drive yet, each naming the interface it *can* read
  instead.

Hand-written connectors keep their place alongside these; the generators are a
way to stop writing the ninetieth variation of the same file, not a replacement
for the ones that are genuinely different.

A generated connector never silently replaces a hand-written one. Where both
exist -- PostgreSQL is in the dialect table *and* has a hand-written adapter
that the extraction service drives -- the hand-written one wins and the
generated entry is skipped, because the hand-written one is the tested one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from service_connectors.adapters.dialect_sql import DialectConnector
from service_connectors.adapters.manifest_rest import ManifestConnector
from service_connectors.adapters.store_files import DeclaredEngineConnector
from service_connectors.adapters.store_files import connector_for as store_connector
from service_connectors.datastores import all_datastores
from service_connectors.dialects import all_dialects
from service_connectors.manifest import load_all
from service_connectors.stores import all_stores


@dataclass
class GenerationReport:
    """What each generator produced, and what it declined to.

    Reported rather than logged: the health view shows it, and "why is there no
    Snowflake connector" should have an answer that is one API call away.
    """

    generated: dict[str, int] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.generated.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated": dict(self.generated),
            "total": self.total,
            "skipped": list(self.skipped),
            "failed": list(self.failed),
        }


def build_all(existing: set[str]) -> tuple[list[Any], GenerationReport]:
    """Every generated connector, minus the ones already hand-written."""
    report = GenerationReport()
    connectors: list[Any] = []

    # -- manifests -------------------------------------------------------
    # `load_all` raises on the first bad manifest, and that exception is
    # allowed to escape: it fails the import, which fails the build, which is
    # the entire point of validating manifests at all.
    manifests = load_all()
    made = 0
    for manifest in manifests:
        if manifest.key in existing:
            report.skipped.append(f"{manifest.key}: a hand-written connector already covers it")
            continue
        connectors.append(ManifestConnector(manifest))
        existing.add(manifest.key)
        made += 1
    report.generated["manifest"] = made

    # -- dialects --------------------------------------------------------
    made = 0
    for dialect in all_dialects():
        if dialect.key in existing:
            report.skipped.append(f"{dialect.key}: a hand-written connector already covers it")
            continue
        connectors.append(DialectConnector(dialect))
        existing.add(dialect.key)
        made += 1
    report.generated["dialect"] = made

    # -- object stores ---------------------------------------------------
    made = 0
    for store in all_stores():
        if store.key in existing:
            report.skipped.append(f"{store.key}: a hand-written connector already covers it")
            continue
        connectors.append(store_connector(store))
        existing.add(store.key)
        made += 1
    report.generated["matrix"] = made

    # -- declared engines -------------------------------------------------
    # In the catalogue, honestly unavailable, and each says which interface
    # this platform *can* read instead. See `datastores.py`.
    made = 0
    for store in all_datastores():
        if store.key in existing:
            report.skipped.append(f"{store.key}: a hand-written connector already covers it")
            continue
        connectors.append(DeclaredEngineConnector(store))
        existing.add(store.key)
        made += 1
    report.generated["declared"] = made

    return connectors, report


REPORT = GenerationReport()
