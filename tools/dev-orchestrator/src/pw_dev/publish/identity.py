"""Git identity: set it locally, and stop anything from overriding it.

Two separate mechanisms matter, because `git commit` takes the first answer it
finds and the environment wins over configuration:

1. the repository-local `user.name` / `user.email` are set and verified;
2. `GIT_AUTHOR_*` and `GIT_COMMITTER_*` are stripped from every child
   environment (`util.proc.ENV_DENYLIST`) and then passed explicitly on the
   commit invocation, so an inherited value cannot re-author the commit and a
   misconfigured shell cannot quietly become the committer.

Signing requirements are read, never changed. If the repository asks for signed
commits and no signing credential is present, that is reported and publication
stops -- it is not solved with `--no-gpg-sign`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..workspace import git


@dataclass
class IdentityReport:
    expected_name: str
    expected_email: str
    local_name: str | None
    local_email: str | None
    env_overrides: dict[str, str] = field(default_factory=dict)
    signing_required: bool = False
    signing_format: str | None = None
    signing_key: str | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict:
        return {
            "expected_name": self.expected_name,
            "expected_email": self.expected_email,
            "verified": self.ok,
        }


def inspect_identity(repo: Path, *, expected_name: str, expected_email: str) -> IdentityReport:
    report = IdentityReport(
        expected_name=expected_name,
        expected_email=expected_email,
        local_name=git.out(repo, ["config", "--local", "--get", "user.name"], check=False) or None,
        local_email=git.out(repo, ["config", "--local", "--get", "user.email"], check=False) or None,
    )
    report.env_overrides = {
        name: "<set>"
        for name in (
            "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
            "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE",
        )
        if os.environ.get(name)
    }
    required, fmt = git.signing_configured(repo)
    report.signing_required = required
    report.signing_format = fmt
    if required:
        key = git.out(repo, ["config", "--get", "user.signingkey"], check=False)
        report.signing_key = key or None
        if not key and fmt != "ssh":
            report.problems.append(
                "commit.gpgsign is true but user.signingkey is unset; signing is required "
                "by this repository and will not be disabled to work around it"
            )
    if report.local_name != expected_name or report.local_email != expected_email:
        report.problems.append(
            f"repository-local identity is "
            f"{report.local_name!r} <{report.local_email!r}>, expected "
            f"{expected_name!r} <{expected_email}>"
        )
    return report


def enforce_identity(repo: Path, *, expected_name: str, expected_email: str) -> IdentityReport:
    """Set the repository-local identity, then re-inspect to confirm it took."""
    git.git(repo, ["config", "--local", "user.name", expected_name])
    git.git(repo, ["config", "--local", "user.email", expected_email])
    report = inspect_identity(repo, expected_name=expected_name, expected_email=expected_email)
    # Environment overrides are not a problem on their own -- they are neutralised
    # on every commit -- but they are worth surfacing, because a shell that sets
    # them is a shell where a manual `git commit` would be misattributed.
    return report


def commit_env(expected_name: str, expected_email: str) -> dict[str, str]:
    """Explicit author and committer for the commit invocation."""
    return {
        "GIT_AUTHOR_NAME": expected_name,
        "GIT_AUTHOR_EMAIL": expected_email,
        "GIT_COMMITTER_NAME": expected_name,
        "GIT_COMMITTER_EMAIL": expected_email,
    }


def verify_identity(repo: Path, sha: str, *, expected_name: str, expected_email: str) -> list[str]:
    """Check one commit's author *and* committer. Both, not just the author."""
    metadata = git.commit_metadata(repo, sha)
    problems: list[str] = []
    for role in ("author", "committer"):
        name = metadata.get(f"{role}_name")
        email = metadata.get(f"{role}_email")
        if name != expected_name or email != expected_email:
            problems.append(
                f"{sha[:12]} {role} is {name!r} <{email}>, expected "
                f"{expected_name!r} <{expected_email}>"
            )
    return problems
