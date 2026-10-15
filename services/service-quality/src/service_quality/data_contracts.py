"""Data contracts: a promise about a dataset that new data must keep (Phase 19, C1).

A contract says which columns a dataset has and what is in them, how many
rows it has, and how often it gets new data. It is checked where data lands:
every recipe run, import and stream save calls `check_new_data` after
working out the new data and before storing it, and the version seam in
`service_datasets.service.apply_dataset_materialization_success` records
the outcome in the same transaction as the version (`record_landing`).

With "stop" (the default) data that breaks a promise is not saved: the run
fails with the reasons and the current data stays. With "warn" it is saved
and the problem recorded. Either way the owner and the people following the
contract are told once, when it breaks, when it is kept again and when it
changes; the worker sends those after commit (`tick`).

Values are judged by the checks' own evaluators (`service_quality.rules`),
so a contract and a check never disagree about what "always filled" means.
How often new data must arrive is the dataset's freshness promise
(`service_observability`), which the worker already checks: the contract
reads and writes that one promise rather than keeping a second one.

Reasons never quote a value from the data, only counts, because a contract
is visible to people a column policy may hide values from.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, ConflictError, NotFoundError
from shared_python.logging import get_logger
from shared_python.words import count_of, listing

from service_quality.engine import evaluate_rule
from service_quality.models import (
    DataContract,
    DataContractEvent,
    DataContractFollower,
    DataContractProblem,
    DataContractVersion,
)
from service_quality.schemas_contracts import (
    ContractCheckResponse,
    ContractConsumer,
    ContractPerson,
    ContractHistoryResponse,
    ContractProblemRead,
    ContractSaveResponse,
    ContractTerms,
    ContractVersionRead,
    DataContractDetail,
    DataContractListResponse,
    DataContractRead,
    DataContractWrite,
    DatasetContractResponse,
)

logger = get_logger(__name__)

EVENT_TYPE = "data_contract"
RECENT_PROBLEMS = 20
#: Who hears about a contract with no owner and no followers, as for incidents.
ACTING_ROLES = ("operator", "editor", "admin")

KIND_WORDS: dict[str, str] = {
    "text": "Text",
    "whole_number": "Whole number",
    "decimal_number": "Decimal number",
    "date": "Date",
    "date_time": "Date & time",
    "true_false": "True / false",
    "any": "Any",
}

#: What a source is called in a sentence, by its type.
SOURCE_WORDS: dict[str, str] = {
    "recipe": "the recipe",
    "import": "the import",
    "stream": "the stream",
}


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------
# Kinds of column
# --------------------------------------------------------------------------


def observed_kind(series: pd.Series) -> str | None:
    """The kind a column's values are, or None when it has no values to say.

    Whole numbers with an empty value among them arrive as decimals (that is
    how pandas holds them), so a decimal column whose values are all whole
    is a whole-number column.
    """
    from shared_python.types import infer_pw_type

    return kind_of_type(str(infer_pw_type(series)), series)


def kind_of_type(canonical: str | None, series: pd.Series | None = None) -> str | None:
    """A canonical type's kind; `series` lets whole decimals count as whole."""
    from shared_python.types.lattice import Kind, parse

    if not canonical:
        return None
    try:
        parsed = parse(canonical)
    except Exception:  # noqa: BLE001 - an unreadable type is not a kind
        return "other"
    if parsed.kind is Kind.UNKNOWN:
        return None
    if parsed.is_integer:
        return "whole_number"
    if parsed.is_float or parsed.kind is Kind.DECIMAL:
        if series is not None:
            values = pd.to_numeric(series.dropna(), errors="coerce").dropna()
            if len(values) and bool(((values % 1) == 0).all()):
                return "whole_number"
        return "decimal_number"
    if parsed.kind in (Kind.STRING, Kind.UUID):
        return "text"
    if parsed.kind is Kind.DATE:
        return "date"
    if parsed.kind is Kind.TIMESTAMP:
        return "date_time"
    if parsed.kind is Kind.BOOLEAN:
        return "true_false"
    return "other"


def fits(promised: str, actual: str | None) -> bool:
    """Do values of kind `actual` keep a promise of kind `promised`?

    A column with no values keeps every kind: nothing in it says otherwise,
    and "always filled" is the promise that it has values.
    """
    if promised == "any" or actual is None:
        return True
    if promised == "decimal_number":
        return actual in ("whole_number", "decimal_number")
    if promised == "date":
        return actual in ("date", "date_time")
    return promised == actual


def _kind_word(kind: str | None) -> str:
    if kind is None:
        return "empty"
    return KIND_WORDS.get(kind, "another kind").lower() if kind != "other" else "another kind"


# --------------------------------------------------------------------------
# Judging data against the promises
# --------------------------------------------------------------------------


def _reason(term: str, sentence: str) -> dict[str, str]:
    return {"term": term, "sentence": sentence}


def _value_check(frame: pd.DataFrame, term: str, rule_type: str, config: dict[str, Any]) -> dict[str, str] | None:
    try:
        result = evaluate_rule(frame, rule_type=rule_type, config=config)
    except BadRequestError as exc:
        # A promise that cannot be judged is not kept: failing closed is the
        # only answer that does not let bad data through on a technicality.
        return _reason(term, f"This could not be checked: {exc.detail}")
    if result.status == "failed":
        return _reason(term, result.message)
    return None


def evaluate(terms: dict[str, Any], frame: pd.DataFrame, *, previous_row_count: int | None) -> list[dict[str, str]]:
    """Every promise `frame` breaks, in the order the contract makes them.

    `previous_row_count` is the current data's row count, for the largest
    fall allowed; None when there is no current data to compare with.
    """
    reasons: list[dict[str, str]] = []
    present = [str(column) for column in frame.columns]
    promised = [column for column in terms.get("columns") or [] if isinstance(column, dict)]

    for column in promised:
        name = str(column.get("name") or "")
        if name not in frame.columns:
            reasons.append(_reason(f"{name}.present", f"The column '{name}' is missing."))
            continue
        kind = str(column.get("kind") or "any")
        actual = observed_kind(frame[name])
        kind_kept = fits(kind, actual)
        if not kind_kept:
            reasons.append(
                _reason(
                    f"{name}.kind",
                    f"'{name}' should be {KIND_WORDS.get(kind, kind).lower()} but is {_kind_word(actual)}.",
                )
            )
        if column.get("always_filled"):
            found = _value_check(frame, f"{name}.always_filled", "not_null", {"column": name})
            if found:
                reasons.append(found)
        if not kind_kept:
            # Judging repeats, lists or a range on values of the wrong kind
            # would only repeat the problem already named.
            continue
        if column.get("no_repeats"):
            found = _value_check(frame, f"{name}.no_repeats", "unique", {"column": name})
            if found:
                reasons.append(found)
        allowed = column.get("allowed_values")
        if isinstance(allowed, list) and allowed:
            found = _value_check(
                frame, f"{name}.allowed_values", "allowed_values", {"column": name, "allowed_values": allowed}
            )
            if found:
                reasons.append(found)
        lowest, highest = column.get("lowest"), column.get("highest")
        if lowest is not None or highest is not None:
            found = _value_check(frame, f"{name}.range", "range", {"column": name, "min": lowest, "max": highest})
            if found:
                reasons.append(found)

    if terms.get("other_columns") == "not_allowed":
        names = {str(column.get("name")) for column in promised}
        extra = [column for column in present if column not in names]
        if extra:
            reasons.append(
                _reason(
                    "columns.other",
                    f"It has {count_of(len(extra), 'column')} the contract does not promise: {listing(extra)}.",
                )
            )

    rows = int(len(frame))
    at_least, at_most = terms.get("rows_at_least"), terms.get("rows_at_most")
    if at_least is not None and rows < int(at_least):
        reasons.append(
            _reason("rows.at_least", f"It has {count_of(rows, 'row')}; the contract promises at least {int(at_least):,}.")
        )
    if at_most is not None and rows > int(at_most):
        reasons.append(
            _reason("rows.at_most", f"It has {count_of(rows, 'row')}; the contract promises at most {int(at_most):,}.")
        )
    largest_drop = terms.get("largest_drop_percent")
    if largest_drop is not None and previous_row_count:
        fall = (previous_row_count - rows) / previous_row_count * 100
        if fall > float(largest_drop):
            reasons.append(
                _reason(
                    "rows.drop",
                    f"It has {_percent(fall)} fewer rows than the current data ({rows:,} against "
                    f"{previous_row_count:,}); the contract allows at most {_percent(float(largest_drop))} fewer.",
                )
            )
    return reasons


def _percent(value: float) -> str:
    rounded = round(value, 1)
    return f"{int(rounded)}%" if rounded == int(rounded) else f"{rounded}%"


# --------------------------------------------------------------------------
# Promises drafted from the data, and what changed between two sets
# --------------------------------------------------------------------------


def draft_terms(dataset: Dataset) -> ContractTerms:
    """Promises the current data already keeps, for a person to edit.

    Every column with its kind, "always filled" where nothing is empty now,
    and at least one row. Nothing stricter: a draft that today's data only
    happens to keep (no repeats, a range) would stop tomorrow's for no reason
    anyone chose.
    """
    schema = (dataset.schema_json or {}).get("columns") or []
    profile = {
        str(column.get("name")): column
        for column in (dataset.profile_json or {}).get("columns") or []
        if isinstance(column, dict)
    }
    columns = []
    for column in schema:
        if not isinstance(column, dict) or not column.get("name"):
            continue
        name = str(column["name"])
        kind = kind_of_type(column.get("canonical_type") or column.get("inferred_type"))
        nulls = profile.get(name, {}).get("null_count")
        columns.append(
            {
                "name": name,
                "kind": kind if kind in KIND_WORDS else "any",
                "always_filled": nulls == 0 and (dataset.row_count or 0) > 0,
            }
        )
    return ContractTerms.model_validate(
        {"columns": columns, "rows_at_least": 1 if (dataset.row_count or 0) > 0 else None}
    )


def _column_words(column: dict[str, Any]) -> str:
    parts = [KIND_WORDS.get(str(column.get("kind") or "any"), "Any").lower()]
    if column.get("always_filled"):
        parts.append("always filled")
    if column.get("no_repeats"):
        parts.append("no repeats")
    if column.get("allowed_values"):
        parts.append(f"{count_of(len(column['allowed_values']), 'allowed value')}")
    if column.get("lowest") is not None or column.get("highest") is not None:
        parts.append("a range")
    return ", ".join(parts)


def describe_changes(before: dict[str, Any] | None, after: dict[str, Any]) -> list[str]:
    """What a change to a contract did, a sentence each, for its history.

    `before` and `after` are whole contract states: terms, enforcement,
    owner name and description.
    """
    if before is None:
        return ["Wrote the contract."]
    changes: list[str] = []
    old_terms, new_terms = before.get("terms") or {}, after.get("terms") or {}
    old_columns = {str(c["name"]): c for c in old_terms.get("columns") or []}
    new_columns = {str(c["name"]): c for c in new_terms.get("columns") or []}
    for name in new_columns:
        if name not in old_columns:
            changes.append(f"Now promises '{name}' ({_column_words(new_columns[name])}).")
        elif old_columns[name] != new_columns[name]:
            changes.append(f"Changed what it promises about '{name}' (now {_column_words(new_columns[name])}).")
    for name in old_columns:
        if name not in new_columns:
            changes.append(f"No longer promises '{name}'.")
    if old_terms.get("other_columns") != new_terms.get("other_columns"):
        changes.append(
            "Now allows only the promised columns."
            if new_terms.get("other_columns") == "not_allowed"
            else "Now allows new columns to appear."
        )
    for key, words in (
        ("rows_at_least", "at least"),
        ("rows_at_most", "at most"),
    ):
        if old_terms.get(key) != new_terms.get(key):
            value = new_terms.get(key)
            changes.append(f"Now promises {words} {int(value):,} rows." if value is not None else f"No longer promises {words} a number of rows.")
    if old_terms.get("largest_drop_percent") != new_terms.get("largest_drop_percent"):
        value = new_terms.get("largest_drop_percent")
        changes.append(
            f"Now allows at most {_percent(float(value))} fewer rows than the last data."
            if value is not None
            else "No longer limits how far the row count may fall."
        )
    if old_terms.get("new_data_every_hours") != new_terms.get("new_data_every_hours"):
        value = new_terms.get("new_data_every_hours")
        changes.append(
            f"Now promises new data at least every {_hours(float(value))}."
            if value is not None
            else "No longer promises how often new data arrives."
        )
    if before.get("enforcement") != after.get("enforcement"):
        changes.append(
            "Now stops data that breaks it." if after.get("enforcement") == "stop" else "Now lets data that breaks it through, with a warning."
        )
    if before.get("owner") != after.get("owner"):
        changes.append(f"The owner is now {after.get('owner') or 'nobody'}.")
    if (before.get("description") or "") != (after.get("description") or ""):
        changes.append("Changed the description.")
    return changes or ["Saved with no changes to its promises."]


def _hours(value: float) -> str:
    if value == int(value):
        return count_of(int(value), "hour")
    return f"{value:g} hours"


# --------------------------------------------------------------------------
# Where data lands
# --------------------------------------------------------------------------


@dataclass
class Verdict:
    """What a dataset's contract made of new data, carried to the version seam."""

    contract_id: uuid.UUID
    contract_version: int
    enforcement: str
    dataset_name: str
    reasons: list[dict[str, str]]
    rows_checked: int
    source_type: str | None
    source_id: uuid.UUID | None = None
    source_name: str | None = None
    run_id: uuid.UUID | None = None
    actor_user_id: uuid.UUID | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def kept(self) -> bool:
        return not self.reasons

    def sentences(self) -> list[str]:
        return [reason["sentence"] for reason in self.reasons]


class ContractBroken(ConflictError):
    """New data broke an enforced contract, so it was not saved."""

    def __init__(self, detail: str, verdict: Verdict) -> None:
        super().__init__(detail)
        self.verdict = verdict


def contract_for(db: Session, dataset_id: uuid.UUID) -> DataContract | None:
    return db.scalar(select(DataContract).where(DataContract.dataset_id == dataset_id))


def _source_words(source_type: str | None, source_name: str | None) -> str:
    """"the recipe 'Clean orders'", for the middle of a sentence."""
    if source_type in SOURCE_WORDS and source_name:
        return f"{SOURCE_WORDS[source_type]} '{source_name}'"
    return {
        "rollback": "rolling back",
        "erasure": "erasing a person's data",
        "check": "a check by hand",
    }.get(source_type or "", "new data")


def check_new_data(
    db: Session,
    *,
    dataset: Dataset | None,
    frame: pd.DataFrame,
    source_type: str,
    source_id: uuid.UUID | None = None,
    source_name: str | None = None,
    run_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    may_stop: bool = True,
    record_stop: bool = True,
) -> Verdict | None:
    """Judge new data for `dataset` against its contract, before it is stored.

    Returns None when the dataset has no contract (a new dataset never has
    one). When the data breaks an enforced contract, records the problem
    (flushed, so the caller's failure path commits it with the failed run)
    and raises `ContractBroken`; otherwise returns the verdict, which the
    caller hands to the version seam so the outcome is recorded with the
    version. `may_stop` is False where stopping is not ours to do (erasing a
    person's data is a legal duty); `record_stop` is False where a person is
    refused in front of them (a rollback) rather than a run failing unseen.
    """
    if dataset is None:
        return None
    contract = contract_for(db, dataset.id)
    if contract is None:
        return None
    previous = int(dataset.row_count) if dataset.status == "ready" and dataset.row_count is not None else None
    verdict = Verdict(
        contract_id=contract.id,
        contract_version=contract.version,
        enforcement=contract.enforcement,
        dataset_name=dataset.name,
        reasons=evaluate(contract.terms_json or {}, frame, previous_row_count=previous),
        rows_checked=int(len(frame)),
        source_type=source_type,
        source_id=source_id,
        source_name=source_name,
        run_id=run_id,
        actor_user_id=actor_user_id,
    )
    if verdict.kept or contract.enforcement != "stop" or not may_stop:
        return verdict

    if record_stop:
        contract.last_checked_at = _now()
        _record_problem(db, contract, dataset, verdict, outcome="stopped")
        db.flush()
    because = "; ".join(verdict.sentences())
    if source_type == "rollback":
        detail = (
            f"This version breaks the contract on '{dataset.name}': {because} "
            "Change the contract, or set it to warn, to roll back to it."
        )
    else:
        detail = (
            f"The new data breaks the contract on '{dataset.name}', so it was not saved and the current "
            f"data is unchanged: {because}"
        )
    raise ContractBroken(detail, verdict)


def record_landing(db: Session, *, dataset: Dataset, verdict: Verdict | None) -> None:
    """Record what the contract made of data that has just become the head.

    Called by the version seam in the version's own transaction, so data
    that is rolled back records nothing. Data let through with problems
    opens (or repeats) a problem; data that keeps the contract resolves
    the problems it answers: its own source's, and any data let through
    before it, which it has now replaced.
    """
    if verdict is None:
        return
    contract = db.get(DataContract, verdict.contract_id)
    if contract is None:
        return
    moment = _now()
    contract.last_checked_at = moment
    if not verdict.kept:
        _record_problem(db, contract, dataset, verdict, outcome="let_through")
        return
    _resolve_answered(db, contract, dataset, verdict, moment)


def _fingerprint(kind: str, source_type: str | None, source_id: uuid.UUID | None, reasons: list[dict[str, str]]) -> str:
    terms = "|".join(sorted(reason["term"] for reason in reasons))
    raw = f"{kind}:{source_type or ''}:{source_id or ''}:{terms}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _same_source(problem: DataContractProblem, source_type: str | None, source_id: uuid.UUID | None) -> bool:
    return problem.source_type == source_type and problem.source_id == source_id


def _record_problem(
    db: Session, contract: DataContract, dataset: Dataset, verdict: Verdict, *, outcome: str
) -> DataContractProblem:
    moment = _now()
    fingerprint = _fingerprint("new_data", verdict.source_type, verdict.source_id, verdict.reasons)
    open_problems = db.scalars(
        select(DataContractProblem).where(
            DataContractProblem.contract_id == contract.id,
            DataContractProblem.kind == "new_data",
            DataContractProblem.resolved_at.is_(None),
        )
    ).all()
    for problem in open_problems:
        if _same_source(problem, verdict.source_type, verdict.source_id) and problem.fingerprint == fingerprint:
            # The same source breaking the same promises again: one problem,
            # seen once more, rather than a new one and a new message.
            problem.times_seen = int(problem.times_seen or 1) + 1
            problem.last_seen_at = moment
            problem.reasons_json = verdict.reasons
            problem.outcome = outcome
            problem.contract_version = contract.version
            problem.pipeline_run_id = verdict.run_id or problem.pipeline_run_id
            problem.actor_user_id = verdict.actor_user_id or problem.actor_user_id
            return problem
        if _same_source(problem, verdict.source_type, verdict.source_id) or (
            outcome == "let_through" and problem.outcome == "let_through"
        ):
            # Superseded: the same source now breaks something else, or other
            # data that was let through has been replaced by this.
            problem.resolved_at = moment

    problem = DataContractProblem(
        project_id=contract.project_id,
        contract_id=contract.id,
        dataset_id=dataset.id,
        contract_version=contract.version,
        kind="new_data",
        outcome=outcome,
        source_type=verdict.source_type,
        source_id=verdict.source_id,
        source_name=(verdict.source_name or None) and verdict.source_name[:200],
        reasons_json=verdict.reasons,
        fingerprint=fingerprint,
        times_seen=1,
        last_seen_at=moment,
        pipeline_run_id=verdict.run_id,
        actor_user_id=verdict.actor_user_id,
    )
    db.add(problem)
    because = " ".join(verdict.sentences())
    source = _source_words(verdict.source_type, verdict.source_name)
    if outcome == "stopped":
        title = f"The contract on {dataset.name} stopped new data"
        message = f"New data from {source} breaks the contract on {dataset.name}, so it was not saved. {because}"
    else:
        title = f"The contract on {dataset.name} is broken"
        message = (
            f"New data from {source} breaks the contract on {dataset.name}. It was saved, because the "
            f"contract is set to warn. {because}"
        )
    _event(db, contract, dataset, kind="broken", title=title, message=message)
    return problem


def _resolve_answered(
    db: Session, contract: DataContract, dataset: Dataset, verdict: Verdict, moment: datetime
) -> None:
    open_problems = db.scalars(
        select(DataContractProblem).where(
            DataContractProblem.contract_id == contract.id,
            DataContractProblem.kind == "new_data",
            DataContractProblem.resolved_at.is_(None),
        )
    ).all()
    answered = [
        problem
        for problem in open_problems
        if _same_source(problem, verdict.source_type, verdict.source_id)
        or problem.outcome == "let_through"
        or problem.source_type == "check"
    ]
    if not answered:
        return
    for problem in answered:
        problem.resolved_at = moment
    still_open = len(open_problems) - len(answered)
    source = _source_words(verdict.source_type, verdict.source_name)
    message = f"New data from {source} keeps the contract on {dataset.name}."
    if still_open:
        message += f" {count_of(still_open, 'problem')} from other sources {'is' if still_open == 1 else 'are'} still open."
    _event(db, contract, dataset, kind="kept", title=f"{dataset.name} keeps its contract again", message=message)


def _event(
    db: Session,
    contract: DataContract,
    dataset: Dataset,
    *,
    kind: str,
    title: str,
    message: str,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    db.add(
        DataContractEvent(
            project_id=contract.project_id,
            contract_id=contract.id,
            dataset_id=dataset.id,
            kind=kind,
            actor_user_id=actor_user_id,
            title=title[:240],
            message=message,
        )
    )


# --------------------------------------------------------------------------
# Reading and writing contracts
# --------------------------------------------------------------------------


def _dataset(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID) -> Dataset:
    from service_datasets.service import get_dataset_model_for_project

    return get_dataset_model_for_project(db, project_id, dataset_id)


def _usernames(db: Session, ids: list[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    from service_auth.models import User

    wanted = sorted({value for value in ids if value is not None}, key=str)
    if not wanted:
        return {}
    return {row[0]: row[1] for row in db.execute(select(User.id, User.username).where(User.id.in_(wanted))).all()}


def _policy(db: Session, dataset_id: uuid.UUID):
    from service_observability.models import FreshnessPolicy

    return db.scalar(select(FreshnessPolicy).where(FreshnessPolicy.dataset_id == dataset_id))


def _terms_with_freshness(db: Session, contract: DataContract) -> dict[str, Any]:
    """The stored terms with how often new data must arrive, read from the
    dataset's one freshness promise so the two can never disagree."""
    terms = dict(contract.terms_json or {})
    policy = _policy(db, contract.dataset_id)
    terms["new_data_every_hours"] = (
        round(policy.max_age_minutes / 60, 4) if policy is not None and policy.enabled else None
    )
    return terms


def _problem_read(problem: DataContractProblem) -> ContractProblemRead:
    return ContractProblemRead(
        id=problem.id,
        kind=problem.kind,
        outcome=problem.outcome,
        source_type=problem.source_type,
        source_id=problem.source_id,
        source_name=problem.source_name,
        reasons=[str(reason.get("sentence", "")) for reason in problem.reasons_json or []],
        times_seen=int(problem.times_seen or 1),
        first_seen_at=problem.created_at,
        last_seen_at=problem.last_seen_at,
        resolved_at=problem.resolved_at,
        pipeline_run_id=problem.pipeline_run_id,
        contract_version=problem.contract_version,
    )


def _open_counts(db: Session, contract_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not contract_ids:
        return {}
    rows = db.execute(
        select(DataContractProblem.contract_id, func.count(DataContractProblem.id))
        .where(DataContractProblem.contract_id.in_(contract_ids), DataContractProblem.resolved_at.is_(None))
        .group_by(DataContractProblem.contract_id)
    ).all()
    return {row[0]: int(row[1]) for row in rows}


def _follower_counts(db: Session, contract_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not contract_ids:
        return {}
    rows = db.execute(
        select(DataContractFollower.contract_id, func.count(DataContractFollower.id))
        .where(DataContractFollower.contract_id.in_(contract_ids))
        .group_by(DataContractFollower.contract_id)
    ).all()
    return {row[0]: int(row[1]) for row in rows}


def _following(db: Session, contract_ids: list[uuid.UUID], user_id: uuid.UUID) -> set[uuid.UUID]:
    if not contract_ids:
        return set()
    return set(
        db.scalars(
            select(DataContractFollower.contract_id).where(
                DataContractFollower.contract_id.in_(contract_ids), DataContractFollower.user_id == user_id
            )
        ).all()
    )


def _read(
    db: Session,
    contract: DataContract,
    *,
    dataset_name: str,
    open_problems: int,
    followers: int,
    following: bool,
    names: dict[uuid.UUID, str],
) -> DataContractRead:
    if open_problems:
        state = "broken"
    elif contract.last_checked_at is not None:
        state = "kept"
    else:
        state = "not_checked"
    return DataContractRead(
        id=contract.id,
        project_id=contract.project_id,
        dataset_id=contract.dataset_id,
        dataset_name=dataset_name,
        owner_user_id=contract.owner_user_id,
        owner_username=names.get(contract.owner_user_id) if contract.owner_user_id else None,
        description=contract.description,
        enforcement=contract.enforcement,
        terms=ContractTerms.model_validate(_terms_with_freshness(db, contract)),
        version=contract.version,
        status=state,
        open_problems=open_problems,
        followers=followers,
        following=following,
        last_checked_at=contract.last_checked_at,
        created_at=contract.created_at,
        updated_at=contract.updated_at,
    )


def list_contracts(db: Session, project_id: uuid.UUID, current_user: UserRead) -> DataContractListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    rows = db.execute(
        select(DataContract, Dataset.name)
        .join(Dataset, Dataset.id == DataContract.dataset_id)
        .where(DataContract.project_id == project_id)
        .order_by(func.lower(Dataset.name))
    ).all()
    ids = [row[0].id for row in rows]
    opened = _open_counts(db, ids)
    followers = _follower_counts(db, ids)
    mine = _following(db, ids, current_user.id)
    names = _usernames(db, [row[0].owner_user_id for row in rows])
    return DataContractListResponse(
        items=[
            _read(
                db,
                contract,
                dataset_name=name,
                open_problems=opened.get(contract.id, 0),
                followers=followers.get(contract.id, 0),
                following=contract.id in mine,
                names=names,
            )
            for contract, name in rows
        ]
    )


def _detail(db: Session, contract: DataContract, dataset: Dataset, current_user: UserRead) -> DataContractDetail:
    names = _usernames(db, [contract.owner_user_id])
    base = _read(
        db,
        contract,
        dataset_name=dataset.name,
        open_problems=_open_counts(db, [contract.id]).get(contract.id, 0),
        followers=_follower_counts(db, [contract.id]).get(contract.id, 0),
        following=contract.id in _following(db, [contract.id], current_user.id),
        names=names,
    )
    problems = db.scalars(
        select(DataContractProblem)
        .where(DataContractProblem.contract_id == contract.id)
        .order_by(DataContractProblem.resolved_at.is_not(None), DataContractProblem.last_seen_at.desc())
        .limit(RECENT_PROBLEMS)
    ).all()
    return DataContractDetail(
        **base.model_dump(),
        problems=[_problem_read(problem) for problem in problems],
        consumers=consumers_of(db, dataset.project_id, dataset.id),
    )


def _people(db: Session, project_id: uuid.UUID) -> list[ContractPerson]:
    """The project's owner and members, who may own one of its contracts."""
    from service_access.models import ProjectMembership
    from service_auth.models import User
    from service_projects.models import Project

    project = db.get(Project, project_id)
    ids = set(db.scalars(select(ProjectMembership.user_id).where(ProjectMembership.project_id == project_id)).all())
    if project is not None and project.owner_user_id:
        ids.add(project.owner_user_id)
    if not ids:
        return []
    rows = db.execute(select(User.id, User.username).where(User.id.in_(ids)).order_by(func.lower(User.username))).all()
    return [ContractPerson(id=row[0], username=row[1]) for row in rows]


def _response(db: Session, dataset: Dataset, contract: DataContract | None, current_user: UserRead) -> dict[str, Any]:
    from service_projects.contracts import project_role

    return {
        "contract": _detail(db, contract, dataset, current_user) if contract is not None else None,
        "draft": draft_terms(dataset),
        "people": _people(db, dataset.project_id),
        "your_role": project_role(db, dataset.project_id, current_user.id),
    }


def get_dataset_contract(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead
) -> DatasetContractResponse:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _dataset(db, project_id, dataset_id)
    return DatasetContractResponse(**_response(db, dataset, contract_for(db, dataset.id), current_user))


def _validated(db: Session, project_id: uuid.UUID, payload: DataContractWrite) -> dict[str, Any]:
    """The terms to store, after the checks pydantic cannot make."""
    terms = payload.terms
    seen: set[str] = set()
    for column in terms.columns:
        name = column.name.strip()
        if not name:
            raise BadRequestError("Each promised column needs a name.")
        if name in seen:
            raise BadRequestError(f"'{name}' is promised twice; promise each column once.")
        seen.add(name)
        if column.lowest is not None and column.highest is not None and column.lowest > column.highest:
            raise BadRequestError(f"For '{name}', the lowest value is above the highest.")
        for bound in (column.lowest, column.highest):
            if bound is not None and not math.isfinite(bound):
                raise BadRequestError(f"For '{name}', the lowest and highest values must be ordinary numbers.")
        if (column.lowest is not None or column.highest is not None) and column.kind not in (
            "whole_number",
            "decimal_number",
            "any",
        ):
            raise BadRequestError(f"'{name}' is {KIND_WORDS[column.kind].lower()}, so it cannot have a lowest or highest number.")
        if column.allowed_values is not None:
            cleaned = [value for value in column.allowed_values if value.strip()]
            if not cleaned:
                raise BadRequestError(f"For '{name}', list at least one allowed value, or clear the list.")
            if any(len(value) > 200 for value in cleaned):
                raise BadRequestError(f"For '{name}', each allowed value must be 200 characters or fewer.")
    if terms.rows_at_least is not None and terms.rows_at_most is not None and terms.rows_at_least > terms.rows_at_most:
        raise BadRequestError("The fewest rows promised is more than the most.")
    if payload.owner_user_id is not None:
        from service_access.models import ProjectMembership
        from service_projects.models import Project

        project = db.get(Project, project_id)
        member = db.scalar(
            select(ProjectMembership.id).where(
                ProjectMembership.project_id == project_id, ProjectMembership.user_id == payload.owner_user_id
            )
        )
        if member is None and (project is None or project.owner_user_id != payload.owner_user_id):
            raise BadRequestError("The owner must be someone in this project.")
    stored = terms.model_dump(exclude={"new_data_every_hours"})
    stored["columns"] = [
        {
            **column,
            "name": column["name"].strip(),
            "allowed_values": [value for value in column["allowed_values"] if value.strip()]
            if column.get("allowed_values") is not None
            else None,
        }
        for column in stored["columns"]
    ]
    return stored


def _set_freshness(db: Session, contract: DataContract, hours: float | None, owner_user_id: uuid.UUID | None) -> None:
    """Write how often new data must arrive as the dataset's freshness promise."""
    from service_observability.models import FreshnessPolicy

    policy = _policy(db, contract.dataset_id)
    if hours is None:
        if policy is not None:
            db.delete(policy)
        return
    minutes = max(1, int(round(hours * 60)))
    if policy is None:
        db.add(
            FreshnessPolicy(
                project_id=contract.project_id,
                dataset_id=contract.dataset_id,
                max_age_minutes=minutes,
                severity="high",
                enabled=True,
                owner_user_id=owner_user_id,
            )
        )
    else:
        if policy.max_age_minutes != minutes:
            # A new limit is judged afresh by the next sweep.
            policy.last_checked_at = None
        policy.max_age_minutes = minutes
        policy.enabled = True


def _state(contract: DataContract, terms: dict[str, Any], owner_name: str | None) -> dict[str, Any]:
    return {
        "terms": terms,
        "enforcement": contract.enforcement,
        "owner": owner_name,
        "description": contract.description,
    }


def save_contract(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: DataContractWrite,
    current_user: UserRead,
    storage_backend: Any,
) -> ContractSaveResponse:
    """Write or change a dataset's contract, as a new version, and say at
    once whether the current data keeps it."""
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _dataset(db, project_id, dataset_id)
    stored = _validated(db, project_id, payload)
    contract = contract_for(db, dataset.id)
    before: dict[str, Any] | None = None
    if contract is None:
        contract = DataContract(
            project_id=project_id,
            dataset_id=dataset.id,
            version=1,
            created_by_user_id=current_user.id,
            owner_user_id=payload.owner_user_id or current_user.id,
        )
        db.add(contract)
    else:
        before_names = _usernames(db, [contract.owner_user_id])
        before = _state(
            contract,
            _terms_with_freshness(db, contract),
            before_names.get(contract.owner_user_id) if contract.owner_user_id else None,
        )
        contract.version = int(contract.version or 1) + 1
        # A contract always has someone answerable for it: leaving the owner
        # out keeps the one it has.
        contract.owner_user_id = payload.owner_user_id or contract.owner_user_id or current_user.id
    contract.description = (payload.description or "").strip() or None
    contract.enforcement = payload.enforcement
    contract.terms_json = stored
    db.flush()
    _set_freshness(db, contract, payload.terms.new_data_every_hours, contract.owner_user_id)

    names = _usernames(db, [contract.owner_user_id])
    after_terms = {**stored, "new_data_every_hours": payload.terms.new_data_every_hours}
    after = _state(contract, after_terms, names.get(contract.owner_user_id) if contract.owner_user_id else None)
    changes = describe_changes(before, after)
    db.add(
        DataContractVersion(
            contract_id=contract.id,
            version=contract.version,
            description=contract.description,
            enforcement=contract.enforcement,
            owner_user_id=contract.owner_user_id,
            terms_json=after_terms,
            changes_json=changes,
            created_by_user_id=current_user.id,
        )
    )
    if before is not None:
        _event(
            db,
            contract,
            dataset,
            kind="changed",
            title=f"The contract on {dataset.name} changed",
            message=f"{current_user.username} changed the contract on {dataset.name} (version {contract.version}). "
            + " ".join(changes),
            actor_user_id=current_user.id,
        )

    # Without storage (a bundle being imported) the data is checked when new
    # data next arrives, or by hand.
    current = _check_head(db, contract, dataset, storage_backend, current_user) if storage_backend is not None else None
    db.commit()
    db.refresh(contract)
    return ContractSaveResponse(**_response(db, dataset, contract, current_user), current=current)


def _check_head(
    db: Session, contract: DataContract, dataset: Dataset, storage_backend: Any, current_user: UserRead
) -> ContractCheckResponse | None:
    """Judge the current data against the contract and record the outcome
    as a check by hand: a problem if it breaks it, and kept if not."""
    if not dataset.file_path or dataset.status != "ready":
        return None
    frame = _head_frame(db, dataset, storage_backend)
    verdict = Verdict(
        contract_id=contract.id,
        contract_version=contract.version,
        enforcement=contract.enforcement,
        dataset_name=dataset.name,
        # The current data is what the comparison is made against, so a
        # fall in rows cannot be judged here: only new data can fall.
        reasons=evaluate(contract.terms_json or {}, frame, previous_row_count=None),
        rows_checked=int(len(frame)),
        source_type="check",
        actor_user_id=current_user.id,
    )
    contract.last_checked_at = _now()
    if verdict.kept:
        _resolve_answered(db, contract, dataset, verdict, contract.last_checked_at)
    else:
        _record_problem(db, contract, dataset, verdict, outcome="let_through")
    return ContractCheckResponse(kept=verdict.kept, reasons=verdict.sentences(), rows_checked=verdict.rows_checked)


def _head_frame(db: Session, dataset: Dataset, storage_backend: Any) -> pd.DataFrame:
    from service_quality.service import _load_dataset_frame

    _, frame = _load_dataset_frame(db, dataset.project_id, dataset.id, storage_backend)
    return frame


def check_contract_now(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead, storage_backend: Any
) -> ContractCheckResponse:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _dataset(db, project_id, dataset_id)
    contract = contract_for(db, dataset.id)
    if contract is None:
        raise NotFoundError("This dataset has no contract yet.")
    result = _check_head(db, contract, dataset, storage_backend, current_user)
    if result is None:
        raise BadRequestError("This dataset has no saved data to check yet.")
    db.commit()
    return result


def would_keep(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    current_user: UserRead,
    storage_backend: Any,
    *,
    version_number: int | None,
) -> ContractCheckResponse:
    """Whether the current data, or one version, keeps the contract. Records
    nothing: it is how the version history warns before a rollback."""
    from service_datasets.service import read_version_frame

    ensure_owned_project(db, project_id, current_user.id)
    dataset = _dataset(db, project_id, dataset_id)
    contract = contract_for(db, dataset.id)
    if contract is None:
        raise NotFoundError("This dataset has no contract yet.")
    if version_number is None:
        if not dataset.file_path or dataset.status != "ready":
            raise BadRequestError("This dataset has no saved data to check yet.")
        frame = _head_frame(db, dataset, storage_backend)
        previous = None
    else:
        frame = read_version_frame(db, dataset, version_number, storage_backend)
        previous = int(dataset.row_count) if dataset.row_count is not None else None
    reasons = evaluate(contract.terms_json or {}, frame, previous_row_count=previous)
    return ContractCheckResponse(
        kept=not reasons,
        reasons=[reason["sentence"] for reason in reasons],
        rows_checked=int(len(frame)),
        version_number=version_number,
    )


def delete_contract(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead) -> None:
    """Remove a dataset's contract. Its freshness promise stays: that is the
    dataset's own, shown under Checks, and may have been there first."""
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _dataset(db, project_id, dataset_id)
    contract = contract_for(db, dataset.id)
    if contract is None:
        raise NotFoundError("This dataset has no contract to remove.")
    db.delete(contract)
    db.commit()


def follow_contract(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead, *, follow: bool
) -> DataContractRead:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _dataset(db, project_id, dataset_id)
    contract = contract_for(db, dataset.id)
    if contract is None:
        raise NotFoundError("This dataset has no contract to follow.")
    existing = db.scalar(
        select(DataContractFollower).where(
            DataContractFollower.contract_id == contract.id, DataContractFollower.user_id == current_user.id
        )
    )
    if follow and existing is None:
        db.add(DataContractFollower(contract_id=contract.id, user_id=current_user.id))
    elif not follow and existing is not None:
        db.delete(existing)
    db.commit()
    return _read(
        db,
        contract,
        dataset_name=dataset.name,
        open_problems=_open_counts(db, [contract.id]).get(contract.id, 0),
        followers=_follower_counts(db, [contract.id]).get(contract.id, 0),
        following=follow,
        names=_usernames(db, [contract.owner_user_id]),
    )


def contract_history(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead
) -> ContractHistoryResponse:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _dataset(db, project_id, dataset_id)
    contract = contract_for(db, dataset.id)
    if contract is None:
        raise NotFoundError("This dataset has no contract yet.")
    versions = db.scalars(
        select(DataContractVersion)
        .where(DataContractVersion.contract_id == contract.id)
        .order_by(DataContractVersion.version.desc())
    ).all()
    names = _usernames(db, [v.owner_user_id for v in versions] + [v.created_by_user_id for v in versions])
    return ContractHistoryResponse(
        items=[
            ContractVersionRead(
                version=version.version,
                description=version.description,
                enforcement=version.enforcement,
                owner_username=names.get(version.owner_user_id) if version.owner_user_id else None,
                terms=ContractTerms.model_validate(version.terms_json or {}),
                changes=list(version.changes_json or []),
                created_by_username=names.get(version.created_by_user_id) if version.created_by_user_id else None,
                created_at=version.created_at,
            )
            for version in versions
        ]
    )


# --------------------------------------------------------------------------
# Who relies on a dataset
# --------------------------------------------------------------------------


def consumers_of(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID) -> list[ContractConsumer]:
    """What reads a dataset, worked out when asked and never stored.

    Recipes that start from it or join or add it, checks on it, charts of it
    and the dashboards that show them, metrics defined on it, scheduled
    deliveries of it, and workflow tasks that name it.
    """
    from service_lineage.graph import secondary_input_ids
    from service_reporting.models import Dashboard, DashboardTile, Metric, SavedChart
    from service_schedules.models import ScheduledOperation
    from service_transformations.models import TransformationPipeline
    from service_workflows.models import Workflow, WorkflowNode

    from service_quality.models import DataQualityRule

    key = str(dataset_id)
    found: list[ContractConsumer] = []

    for recipe in db.scalars(
        select(TransformationPipeline).where(TransformationPipeline.project_id == project_id)
    ).all():
        if recipe.base_dataset_id == dataset_id or any(
            other == key for other, _how in secondary_input_ids(recipe.steps_json)
        ):
            found.append(ContractConsumer(kind="recipe", id=recipe.id, name=recipe.name))

    for rule in db.scalars(
        select(DataQualityRule).where(DataQualityRule.project_id == project_id, DataQualityRule.dataset_id == dataset_id)
    ).all():
        found.append(ContractConsumer(kind="check", id=rule.id, name=rule.name))

    charts = db.scalars(
        select(SavedChart).where(SavedChart.project_id == project_id, SavedChart.dataset_id == dataset_id)
    ).all()
    found.extend(ContractConsumer(kind="chart", id=chart.id, name=chart.name) for chart in charts)
    if charts:
        # A subquery, not DISTINCT over the rows: PostgreSQL cannot compare the
        # JSON columns a dashboard row carries.
        showing = select(DashboardTile.dashboard_id).where(DashboardTile.chart_id.in_([chart.id for chart in charts]))
        dashboards = db.execute(
            select(Dashboard.id, Dashboard.name).where(Dashboard.id.in_(showing))
        ).all()
        found.extend(ContractConsumer(kind="dashboard", id=row.id, name=row.name) for row in dashboards)

    for metric in db.scalars(
        select(Metric).where(Metric.project_id == project_id, Metric.dataset_id == dataset_id)
    ).all():
        found.append(ContractConsumer(kind="metric", id=metric.id, name=metric.name))

    for schedule in db.scalars(
        select(ScheduledOperation).where(ScheduledOperation.project_id == project_id)
    ).all():
        if str((schedule.target_config_json or {}).get("dataset_id") or "") == key:
            found.append(ContractConsumer(kind="delivery", id=schedule.id, name=schedule.name))

    workflow_ids = {
        node.workflow_id
        for node in db.scalars(select(WorkflowNode).where(WorkflowNode.project_id == project_id)).all()
        if str((node.config_json or {}).get("dataset_id") or "") == key
    }
    if workflow_ids:
        for workflow in db.scalars(select(Workflow).where(Workflow.id.in_(workflow_ids))).all():
            found.append(ContractConsumer(kind="workflow", id=workflow.id, name=workflow.name))

    order = ["recipe", "check", "chart", "dashboard", "metric", "delivery", "workflow"]
    return sorted(found, key=lambda item: (order.index(item.kind), item.name.lower()))


# --------------------------------------------------------------------------
# The worker: overdue data, and telling people
# --------------------------------------------------------------------------


def sync_overdue(db: Session, *, now: datetime | None = None) -> int:
    """Open or close each contract's overdue problem from its dataset's
    freshness promise, which the worker's freshness sweep has just judged.
    Returns how many problems it opened or closed."""
    from service_observability.freshness import humanise_minutes
    from service_observability.models import FreshnessPolicy

    moment = now or _now()
    changed = 0
    rows = db.execute(
        select(DataContract, Dataset, FreshnessPolicy)
        .join(Dataset, Dataset.id == DataContract.dataset_id)
        .outerjoin(FreshnessPolicy, FreshnessPolicy.dataset_id == DataContract.dataset_id)
    ).all()
    open_by_contract = {
        problem.contract_id: problem
        for problem in db.scalars(
            select(DataContractProblem).where(
                DataContractProblem.kind == "overdue", DataContractProblem.resolved_at.is_(None)
            )
        ).all()
    }
    for contract, dataset, policy in rows:
        open_overdue = open_by_contract.get(contract.id)
        stale = policy is not None and policy.enabled and policy.last_status == "stale"
        if stale and open_overdue is None:
            age = policy.last_age_minutes
            if age is None:
                sentence = f"No new data has arrived; the contract promises new data at least every {humanise_minutes(policy.max_age_minutes)}."
            else:
                sentence = (
                    f"No new data for {humanise_minutes(age)}; the contract promises new data at least every "
                    f"{humanise_minutes(policy.max_age_minutes)}."
                )
            reasons = [_reason("new_data.every", sentence)]
            db.add(
                DataContractProblem(
                    project_id=contract.project_id,
                    contract_id=contract.id,
                    dataset_id=dataset.id,
                    contract_version=contract.version,
                    kind="overdue",
                    outcome="overdue",
                    reasons_json=reasons,
                    fingerprint=_fingerprint("overdue", None, None, reasons),
                    times_seen=1,
                    last_seen_at=moment,
                )
            )
            _event(
                db,
                contract,
                dataset,
                kind="overdue",
                title=f"New data for {dataset.name} is overdue",
                message=f"{sentence} Anything reading {dataset.name} is still using older data.",
            )
            changed += 1
        elif open_overdue is not None and not stale:
            open_overdue.resolved_at = moment
            if policy is not None and policy.enabled and policy.last_status == "fresh":
                _event(
                    db,
                    contract,
                    dataset,
                    kind="kept",
                    title=f"{dataset.name} has new data again",
                    message=f"New data has arrived for {dataset.name}, so it keeps its contract's promise about how often.",
                )
            changed += 1
    if changed:
        db.commit()
    return changed


def send_due(db: Session, *, limit: int = 100, now: datetime | None = None) -> int:
    """Send the contract events written since the last time, once each.

    Each event is claimed with a conditional update before it is sent, so two
    workers never send the same one. It goes to the contract's owner and
    followers (to the project's acting people when it has neither), and to
    any alert channel that takes "A contract was broken or changed".
    """
    from service_access.models import ProjectMembership
    from service_notifications.external_dispatch import dispatch_external_notifications
    from service_notifications.service import create_user_notification
    from service_projects.models import Project

    moment = now or _now()
    pending = db.scalars(
        select(DataContractEvent)
        .where(DataContractEvent.sent_at.is_(None))
        .order_by(DataContractEvent.created_at)
        .limit(limit)
    ).all()
    sent = 0
    for event in pending:
        claimed = db.execute(
            update(DataContractEvent)
            .where(DataContractEvent.id == event.id, DataContractEvent.sent_at.is_(None))
            .values(sent_at=moment)
        )
        db.commit()
        if claimed.rowcount != 1:
            continue
        try:
            contract = db.get(DataContract, event.contract_id)
            people: set[uuid.UUID] = set()
            if contract is not None:
                if contract.owner_user_id:
                    people.add(contract.owner_user_id)
                people.update(
                    db.scalars(
                        select(DataContractFollower.user_id).where(DataContractFollower.contract_id == contract.id)
                    ).all()
                )
            if event.kind == "changed":
                # The person who made a change knows; the rest are told.
                people.discard(event.actor_user_id)
            elif not people:
                project = db.get(Project, event.project_id)
                if project is not None and project.owner_user_id:
                    people.add(project.owner_user_id)
                people.update(
                    db.scalars(
                        select(ProjectMembership.user_id).where(
                            ProjectMembership.project_id == event.project_id,
                            ProjectMembership.role.in_(ACTING_ROLES),
                        )
                    ).all()
                )
            level = {"broken": "warning", "overdue": "warning", "kept": "success"}.get(event.kind, "info")
            for user_id in sorted(people, key=str):
                create_user_notification(
                    db,
                    user_id=user_id,
                    project_id=event.project_id,
                    type=EVENT_TYPE,
                    level=level,
                    title=event.title,
                    message=event.message,
                    related_dataset_id=event.dataset_id,
                )
            dispatch_external_notifications(
                db,
                project_id=event.project_id,
                event_type=EVENT_TYPE,
                title=event.title,
                message=event.message,
                level=level,
            )
            db.commit()
            sent += 1
        except Exception:  # noqa: BLE001 - one event must not stop the rest
            db.rollback()
            logger.exception("data_contract_send_failed event_id=%s", event.id)
    return sent


def tick(db: Session) -> None:
    """The worker's turn: overdue data first, so its message goes out now."""
    sync_overdue(db)
    send_due(db)
