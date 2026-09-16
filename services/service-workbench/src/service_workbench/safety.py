"""What a workbench session is allowed to run.

Read-only by default, and the default is not a suggestion: a session has to be
opened in write mode explicitly, the project has to be one where that is
allowed, and the person has to have the role for it. That is the same posture
Phase 15 takes for the grid, applied to the one surface where somebody can type
anything at all.

The classification lives in `sql_text`; this module turns it into a decision and
a sentence explaining it. Keeping the sentence next to the rule is deliberate --
"permission denied" with no reason is how people end up asking for write access
they do not need.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shared_python.errors import BadRequestError, ForbiddenError

from service_workbench.sql_text import Script, Statement, StatementKind


@dataclass(frozen=True)
class SessionPolicy:
    """The rules in force for one execution."""

    #: False means every statement must be a read. This is the default.
    allow_writes: bool = False
    #: Statements that change *structure* need this on top of `allow_writes`.
    allow_ddl: bool = False
    #: Production projects can be locked down further than the role model does.
    environment: str = "development"
    #: Rows returned per statement. A workbench is for looking, not exporting.
    row_limit: int = 1_000
    #: Wall-clock budget for the whole script.
    timeout_seconds: int = 30

    def describe(self) -> str:
        if not self.allow_writes:
            return "read-only"
        return "writes allowed" + (" including structure changes" if self.allow_ddl else "")


@dataclass
class Verdict:
    """Whether a script may run, and what the caller should be told."""

    allowed: bool
    reason: str = ""
    #: Warnings that do not block, shown before the run.
    warnings: list[str] = field(default_factory=list)
    #: True when the caller should be made to confirm before it runs.
    needs_confirmation: bool = False


def check(script: Script, policy: SessionPolicy) -> Verdict:
    """Decide whether this script may run under this policy."""
    unknown = [s for s in script.statements if s.kind is StatementKind.UNKNOWN]
    if unknown:
        first = unknown[0]
        return Verdict(
            allowed=False,
            reason=(
                f"Statement {first.index} does not start with anything this "
                "recognises, so it cannot be checked for safety. If it is valid "
                f"SQL for your database, say so on the issue tracker: {first.summary}"
            ),
        )

    writing = [s for s in script.statements if s.kind.writes]
    if writing and not policy.allow_writes:
        return Verdict(
            allowed=False,
            reason=(
                f"This session is read-only, and statement {writing[0].index} "
                f"would change data ({writing[0].kind.value}). Turn on write mode "
                "to run it -- and it will be logged."
            ),
        )

    structural = [s for s in script.statements if s.kind is StatementKind.DDL]
    if structural and not policy.allow_ddl:
        return Verdict(
            allowed=False,
            reason=(
                f"Statement {structural[0].index} changes the structure of the "
                "database. That needs structure changes to be enabled for this "
                "session, separately from ordinary writes."
            ),
        )

    warnings: list[str] = []
    verdict = Verdict(allowed=True, warnings=warnings)

    session = [s for s in script.statements if s.kind is StatementKind.SESSION]
    if session:
        warnings.append(
            f"Statement {session[0].index} changes session state. The workbench "
            "runs each script on its own connection, so it does not carry over."
        )

    if writing:
        verdict.needs_confirmation = True
        if policy.environment.lower() == "production":
            warnings.append(
                "This project is marked production. Writes here reach the live "
                "database as soon as you run them."
            )
        unbounded = [s for s in writing if _looks_unbounded(s)]
        if unbounded:
            warnings.append(
                f"Statement {unbounded[0].index} has no WHERE clause, so it "
                "applies to every row in the table."
            )
    return verdict


def enforce(script: Script, policy: SessionPolicy) -> Verdict:
    """As `check`, but raise rather than return a refusal."""
    verdict = check(script, policy)
    if not verdict.allowed:
        # A refused write is a permissions answer; a script this cannot read is
        # a problem with the script. They deserve different status codes.
        writing = any(s.kind.writes for s in script.statements)
        raise (ForbiddenError if writing else BadRequestError)(verdict.reason)
    return verdict


def _looks_unbounded(statement: Statement) -> bool:
    """A DELETE or UPDATE with no WHERE. Advisory, and deliberately simple."""
    from service_extraction.sql_safety import strip_sql_noise

    words = strip_sql_noise(statement.sql).lower().split()
    if not words or words[0] not in ("delete", "update"):
        return False
    return "where" not in words


def policy_for(
    *,
    role: str | None,
    environment: str,
    requested_writes: bool,
    requested_ddl: bool,
) -> SessionPolicy:
    """Narrow a request to what the person may actually have.

    Asking for write mode does not grant it: an operator can run things and an
    editor can change definitions, but neither implies permission to rewrite a
    source database by hand. That is an admin action, matching the fact that it
    bypasses every review the rest of the platform applies.
    """
    is_admin = (role or "").strip().lower() == "admin"
    return SessionPolicy(
        allow_writes=bool(requested_writes and is_admin),
        allow_ddl=bool(requested_ddl and is_admin),
        environment=environment,
    )
