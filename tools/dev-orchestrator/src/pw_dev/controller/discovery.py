"""DISCOVER: read the repository, reconcile its own account of itself.

Two documents in this repository disagree about what is done. `docs/roadmap-v2.md`
opens with "Status: proposed, not started" while later sections mark phases
complete, and the progress ledger in `docs/HANDOFF.md` records a different
state again. A system that picks the next phase from the first sentence it reads
picks the wrong one.

So discovery gathers evidence and hands the *disagreements* to the planner
rather than resolving them silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..workspace import git

_LEDGER_ROW = re.compile(
    r"^\|\s*(?P<num>\d{2})\s*\|\s*(?P<name>[^|]+?)\s*\|\s*\*{0,2}(?P<status>[^|*]+?)\*{0,2}\s*\|"
    r"\s*(?P<sessions>[^|]*?)\s*\|\s*(?P<notes>[^|]*?)\s*\|\s*$"
)
_ROADMAP_HEADING = re.compile(r"^##\s+Phase\s+(?P<num>\d{2})\s+[—-]\s+(?P<name>.+?)\s*$")


@dataclass
class PhaseRecord:
    number: str
    name: str
    ledger_status: str | None = None
    roadmap_marker: str | None = None
    sessions: str | None = None
    notes: str | None = None
    depends_on: list[str] = field(default_factory=list)

    @property
    def eligible(self) -> bool:
        return (self.ledger_status or "").strip().lower() in ("not started", "partial")

    def disagreement(self) -> str | None:
        ledger = (self.ledger_status or "").lower()
        marker = (self.roadmap_marker or "").lower()
        if not ledger or not marker:
            return None
        complete_marker = "complete" in marker and "partial" not in marker
        if complete_marker and ledger != "done":
            return (
                f"roadmap marks phase {self.number} complete; the ledger says {self.ledger_status!r}"
            )
        if "partial" in marker and ledger == "done":
            return f"roadmap marks phase {self.number} partial; the ledger says done"
        return None


@dataclass
class Discovery:
    """The baseline a run is planned against."""

    repo_root: Path
    head_sha: str
    branch: str | None
    dirty_paths: list[str]
    untracked_paths: list[str]
    remotes: dict[str, str]
    phases: list[PhaseRecord]
    contradictions: list[str]
    deferred_decisions: list[str]
    documents: dict[str, str]
    recommended_phase: str | None = None
    recommendation_text: str | None = None

    def eligible_phases(self) -> list[PhaseRecord]:
        return [p for p in self.phases if p.eligible]

    def next_phase(self) -> PhaseRecord | None:
        """The phase the handoff recommends, if it names one that is eligible.

        Reported as a *candidate*, not a decision. The handoff's recommendation
        wins over "lowest eligible number" because a phase can be eligible and
        deliberately deferred -- 16 is marked partial with its remaining
        families explicitly out of scope, and taking it because it sorts first
        would be reading the table and ignoring the paragraph under it.
        """
        candidates = self.eligible_phases()
        if not candidates:
            return None
        if self.recommended_phase:
            for record in candidates:
                if record.number == self.recommended_phase:
                    return record
        return candidates[0]

    def candidate_phases(self) -> list[PhaseRecord]:
        """Eligible phases whose dependencies are all done, recommendation first."""
        done = {p.number for p in self.phases if (p.ledger_status or "").lower() == "done"}
        ready = [p for p in self.eligible_phases() if all(d in done for d in p.depends_on)]
        ready.sort(key=lambda p: (p.number != self.recommended_phase, p.number))
        return ready

    def to_dict(self) -> dict:
        return {
            "repo_root": str(self.repo_root),
            "head_sha": self.head_sha,
            "branch": self.branch,
            "dirty_paths": self.dirty_paths,
            "untracked_paths": self.untracked_paths,
            "remotes": self.remotes,
            "phases": [
                {
                    "number": p.number, "name": p.name, "ledger_status": p.ledger_status,
                    "roadmap_marker": p.roadmap_marker, "sessions": p.sessions,
                    "notes": p.notes, "depends_on": p.depends_on,
                }
                for p in self.phases
            ],
            "contradictions": self.contradictions,
            "deferred_decisions": self.deferred_decisions,
            "recommended_phase": self.recommended_phase,
            "recommendation_text": self.recommendation_text,
        }


def discover(repo_root: Path) -> Discovery:
    repo_root = Path(repo_root).resolve()
    state = git.capture_state(repo_root)

    handoff = _read(repo_root / "docs" / "HANDOFF.md")
    roadmap = _read(repo_root / "docs" / "roadmap-v2.md")

    phases: dict[str, PhaseRecord] = {}
    for line in handoff.splitlines():
        match = _LEDGER_ROW.match(line.strip())
        if not match:
            continue
        number = match.group("num")
        notes = match.group("notes").strip()
        phases[number] = PhaseRecord(
            number=number,
            name=match.group("name").strip(),
            ledger_status=match.group("status").strip(),
            sessions=match.group("sessions").strip(),
            notes=notes,
            depends_on=_dependencies_from(notes),
        )

    for line in roadmap.splitlines():
        match = _ROADMAP_HEADING.match(line.strip())
        if not match:
            continue
        number = match.group("num")
        name = match.group("name")
        marker = ""
        if "✅" in name or "COMPLETE" in name.upper():
            marker = "complete"
        if "⚠" in name or "PARTIAL" in name.upper():
            marker = "partial"
        record = phases.setdefault(number, PhaseRecord(number=number, name=name.strip()))
        record.roadmap_marker = marker or None

    contradictions: list[str] = []
    opening = "\n".join(roadmap.splitlines()[:6]).lower()
    if "not started" in opening and any(
        (p.ledger_status or "").lower() == "done" for p in phases.values()
    ):
        done = sorted(p.number for p in phases.values() if (p.ledger_status or "").lower() == "done")
        contradictions.append(
            "docs/roadmap-v2.md opens with 'Status: proposed, not started', but the progress "
            f"ledger in docs/HANDOFF.md records phases {', '.join(done)} as done. The opening "
            "line is stale; the ledger is the current record."
        )
    for record in sorted(phases.values(), key=lambda p: p.number):
        disagreement = record.disagreement()
        if disagreement:
            contradictions.append(disagreement)

    contradictions.extend(_tool_count_disagreements(handoff, roadmap))

    deferred = _deferred_decisions(handoff)
    recommended, recommendation_text = _recommendation(handoff)

    return Discovery(
        repo_root=repo_root,
        head_sha=state.head_sha,
        branch=state.branch,
        dirty_paths=state.dirty_paths,
        untracked_paths=state.untracked_paths,
        remotes=state.remotes,
        phases=[phases[k] for k in sorted(phases)],
        contradictions=contradictions,
        deferred_decisions=deferred,
        documents={"handoff": str(repo_root / "docs" / "HANDOFF.md"),
                   "roadmap": str(repo_root / "docs" / "roadmap-v2.md")},
        recommended_phase=recommended,
        recommendation_text=recommendation_text,
    )


def _dependencies_from(notes: str) -> list[str]:
    """Pull "Needs 08, 18" out of a ledger note.

    The ledger records dependencies in prose, so this reads them rather than
    asking the planner to infer an ordering the repository already states.
    """
    match = re.search(r"(?i)\bneeds\b\s+(?P<body>[\d,\s]+(?:and\s*[\d,\s]+)?)", notes)
    if not match:
        return []
    return sorted({token for token in re.findall(r"\d{2}", match.group("body"))})


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _tool_count_disagreements(handoff: str, roadmap: str) -> list[str]:
    """Catch the documented tool counts contradicting each other.

    Not cosmetic: a planner told "167 tools" and a planner told "173 tools" will
    scope the remaining tool work differently.
    """
    counts: dict[str, set[str]] = {}
    for label, text in (("HANDOFF.md", handoff), ("roadmap-v2.md", roadmap)):
        found = set(re.findall(r"(\d{2,4})\s+tools\b", text))
        if found:
            counts[label] = found
    all_counts = {c for values in counts.values() for c in values}
    if len(all_counts) > 1:
        rendered = "; ".join(f"{label}: {sorted(v)}" for label, v in sorted(counts.items()))
        return [
            "the documented transformation-tool counts disagree with each other "
            f"({rendered}). Treat any single figure as unverified until the registry is counted."
        ]
    return []


def _deferred_decisions(handoff: str) -> list[str]:
    """Decisions the handoff records as deliberately postponed.

    These must not be folded into an unrelated phase because they happen to be
    nearby. Recorded so a plan can name them as dependencies or non-goals.
    """
    found: list[str] = []
    if re.search(r"(?i)cutting over to IR-only is a deliberate separate decision", handoff):
        found.append(
            "IR-only executor cutover: both executors run and are proven to agree; the "
            "cutover is a deliberate separate decision (docs/HANDOFF.md, Phase 08 notes)"
        )
    if re.search(r"(?i)not yet wired into runs", handoff):
        found.append(
            "pushdown is built but not wired into extraction runs; that wiring is a "
            "separate deliberate decision (docs/HANDOFF.md, phase 12 ledger row)"
        )
    return found


def _recommendation(handoff: str) -> tuple[str | None, str | None]:
    """Read the handoff's own "Recommended next action" section.

    The repository states which phase it thinks comes next, in prose, under a
    heading. Parsing it is better than re-deriving an opinion from the table:
    the prose is where "16 is partial on purpose" and "18 unlocks 19 and 22"
    are recorded.
    """
    match = re.search(
        r"(?im)^###\s+Recommended next action\s*$(?P<body>.*?)(?=^###\s|^##\s|\Z)",
        handoff, re.DOTALL,
    )
    if not match:
        return None, None
    # Collapse whitespace first: the sentence naming the phase is wrapped across
    # lines in the source, so a pattern with literal spaces silently misses it.
    body = " ".join(match.group("body").split())
    phase = (
        re.search(r"(?i)\b(\d{2})\s*\([^)]+\)\s+is\s+the\s+natural\s+next", body)
        or re.search(r"(?i)\b(\d{2})\b\s+is\s+the\s+natural\s+next", body)
        or re.search(r"(?i)\bphase\s+(\d{2})\b[^.]{0,80}\bnext\b", body)
    )
    return (phase.group(1) if phase else None), body[:600]
