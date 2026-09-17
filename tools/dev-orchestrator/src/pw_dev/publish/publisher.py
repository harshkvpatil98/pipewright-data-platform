"""The only code in this tool that creates a commit or contacts a remote.

Order of operations, and why each step is where it is:

1. the approved fingerprint is compared with the candidate's *current*
   fingerprint. Anything that changed after review -- source, test, doc or
   policy -- invalidates the approval before a commit exists;
2. the staged content is inspected: scope against the specification's declared
   paths, credential-shaped strings, temporary and build artefacts, and
   deletions nobody asked for;
3. one commit is created for exactly the approved tree, with author *and*
   committer set explicitly. The message is composed here; no model writes it;
4. every commit reachable from the publication ref but not from the captured
   base is re-read from Git and checked for identity and attribution -- the
   commit that was just made is checked like any other, from Git's answer
   rather than from what was intended;
5. the remote is inspected before the push: the target must not be a protected
   branch, and if the branch already exists remotely it must be an ancestor of
   what is being published. A target that moved incompatibly blocks. There is no
   force path in this file;
6. after the push, the remote ref is read back and compared to the intended SHA.
   A push exiting zero is not proof; the read-back is.

CI is reported as `not_triggered` for a feature branch, because this
repository's workflow runs on pushes to main/master and on pull requests. A
pushed branch with no PR has not been tested by CI, and saying otherwise would
be the exact kind of claim this system exists to prevent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..config import PublicationPolicy
from ..errors import PublicationError
from ..schemas.validate import validate_artifact
from ..util.hashing import tree_fingerprint
from ..util.redact import scan_for_secrets
from ..workspace import git
from ..workspace.patches import CONTROLLER_SCRATCH
from .attribution import clean_commit_message, scan_commit_metadata, scan_ref_name
from .identity import commit_env, enforce_identity, verify_identity


class PublicationRefusal(PublicationError):
    """Publication was refused, with the checks that failed. Nothing was pushed."""

    def __init__(self, message: str, checks: list[dict]) -> None:
        self.checks = checks
        super().__init__(message)


#: Paths that must never appear in a published commit.
_JUNK_PATTERNS = (
    re.compile(r"(?:^|/)\.pw-dev(?:/|$)"),
    re.compile(r"(?:^|/)\.pw-dev-scratch(?:/|$)"),
    re.compile(r"(?:^|/)\.pw-dev-worktree$"),
    re.compile(r"(?:^|/)\.env(?:\.|$)"),
    re.compile(r"(?:^|/)node_modules(?:/|$)"),
    re.compile(r"(?:^|/)\.venv(?:/|$)"),
    re.compile(r"(?:^|/)__pycache__(?:/|$)"),
    re.compile(r"\.(?:pyc|pyo|orig|rej|swp)$"),
    re.compile(r"(?:^|/)\.DS_Store$"),
    re.compile(r"(?:^|/)\.next(?:/|$)"),
    re.compile(r"(?:^|/)\.coverage$"),
)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


class Publisher:
    """Creates and publishes the approved tree, or refuses and explains."""

    def __init__(self, *, repo_root: Path, policy: PublicationPolicy, run_id: str) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.policy = policy
        self.run_id = run_id

    # ---------------------------------------------------------------- preflight
    def preflight(self, candidate: Path, *, base_commit: str, approved_fingerprint: str,
                  allowed_paths: list[str] | None = None) -> list[Check]:
        """Everything that can be decided before a commit exists."""
        checks: list[Check] = []
        candidate = Path(candidate).resolve()

        current = tree_fingerprint(candidate)
        matched = current == approved_fingerprint
        checks.append(Check(
            "approved tree unchanged", matched,
            "the candidate matches the reviewed tree" if matched else
            f"the candidate is {current[:20]}… but review approved {approved_fingerprint[:20]}…; "
            "the approval does not cover this tree",
        ))
        if not matched:
            return checks

        git.git(candidate, ["add", "-A", "--", ".", *CONTROLLER_SCRATCH], check=False)
        changed = git.out(
            candidate,
            ["diff", "--cached", "--name-status", base_commit, "--", ".", *CONTROLLER_SCRATCH],
            check=False,
        )
        entries = [line.split("\t") for line in changed.splitlines() if line]
        paths = [parts[-1] for parts in entries if parts]

        checks.append(Check(
            "change set is non-empty", bool(paths),
            f"{len(paths)} paths changed against {base_commit[:12]}" if paths else
            "nothing changed against the base; there is nothing to publish",
        ))

        junk = [p for p in paths if any(pattern.search(p) for pattern in _JUNK_PATTERNS)]
        checks.append(Check(
            "no temporary or build artefacts", not junk,
            "none found" if not junk else f"would publish: {', '.join(junk[:10])}",
        ))

        deletions = [parts[-1] for parts in entries if parts and parts[0].startswith("D")]
        checks.append(Check(
            "deletions accounted for", True,
            "no deletions" if not deletions else
            f"{len(deletions)} deletion(s), listed for review: {', '.join(deletions[:10])}",
        ))

        if allowed_paths:
            from ..workspace.guard import PathGuard

            guard = PathGuard(allowed_paths)
            _, violations = guard.partition(paths)
            checks.append(Check(
                "changes are inside the specification's declared scope", not violations,
                "all changed paths are in scope" if not violations else
                "; ".join(f"{v.path}: {v.reason}" for v in violations[:8]),
            ))

        diff = git.out(candidate, ["diff", "--cached", base_commit, "--", ".",
                                   *CONTROLLER_SCRATCH], check=False, timeout=600)
        secrets = scan_for_secrets(diff)
        checks.append(Check(
            "no credential-shaped content in the diff", not secrets,
            "none found" if not secrets else
            "; ".join(f"{label} ({snippet})" for label, snippet in secrets[:6]),
        ))
        return checks

    # ------------------------------------------------------------------ commit
    def commit(self, candidate: Path, *, base_commit: str, subject: str, body: str,
               approved_fingerprint: str, allowed_paths: list[str] | None = None) -> tuple[str, str, list[Check]]:
        """Create one commit for exactly the approved tree.

        Returns `(commit_sha, tree_sha, checks)`. Worker checkpoint history is
        not carried forward: the published branch gets a single commit whose
        tree is the approved tree, so there is nothing to inspect that a person
        would not want to read.
        """
        candidate = Path(candidate).resolve()
        checks = self.preflight(candidate, base_commit=base_commit,
                                approved_fingerprint=approved_fingerprint,
                                allowed_paths=allowed_paths)
        if any(not c.passed for c in checks):
            raise PublicationRefusal(
                "refusing to commit: " + "; ".join(c.name for c in checks if not c.passed),
                [c.to_dict() for c in checks],
            )

        identity = enforce_identity(
            candidate, expected_name=self.policy.author_name,
            expected_email=self.policy.author_email,
        )
        if not identity.ok:
            raise PublicationRefusal(
                "refusing to commit: " + "; ".join(identity.problems),
                [*(c.to_dict() for c in checks),
                 {"name": "git identity", "passed": False, "detail": "; ".join(identity.problems)}],
            )
        checks.append(Check("git identity", True,
                            f"{identity.expected_name} <{identity.expected_email}> (repository-local)"))

        git.git(candidate, ["add", "-A", "--", ".", *CONTROLLER_SCRATCH])
        tree_sha = git.out(candidate, ["write-tree"])
        message = clean_commit_message(subject, body)

        argv = ["commit-tree", tree_sha, "-p", base_commit]
        if identity.signing_required:
            argv.append("-S")
        commit_sha = git.out(
            candidate, [*argv, "-m", message],
            env_overrides=commit_env(self.policy.author_name, self.policy.author_email),
        )
        if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
            raise PublicationError(f"git commit-tree returned {commit_sha!r}")

        # Point the candidate branch at the new commit so the worktree state and
        # the published commit cannot drift apart.
        git.git(candidate, ["reset", "--soft", commit_sha], check=False)

        recorded_tree = git.out(candidate, ["rev-parse", f"{commit_sha}^{{tree}}"])
        checks.append(Check(
            "committed tree equals the approved tree", recorded_tree == tree_sha,
            f"tree {recorded_tree[:12]}",
        ))
        if recorded_tree != tree_sha:
            raise PublicationRefusal("the commit does not carry the approved tree",
                                     [c.to_dict() for c in checks])
        return commit_sha, tree_sha, checks

    # ------------------------------------------------------------- inspection
    def inspect_new_commits(self, candidate: Path, *, base_commit: str, head: str) -> tuple[list[dict], list[str]]:
        """Read every new commit back from Git and check identity and attribution."""
        problems: list[str] = []
        records: list[dict] = []
        for sha in git.commits_between(candidate, base_commit, head):
            metadata = git.commit_metadata(candidate, sha)
            findings = scan_commit_metadata(metadata, sha=sha)
            note = git.notes_for(candidate, sha)
            if note:
                from .attribution import scan_text

                findings += scan_text(note, f"{sha[:12]}.note")
            identity_problems = verify_identity(
                candidate, sha, expected_name=self.policy.author_name,
                expected_email=self.policy.author_email,
            )
            problems.extend(identity_problems)
            problems.extend(str(f) for f in findings)
            records.append({
                "sha": sha,
                "author": f"{metadata['author_name']} <{metadata['author_email']}>",
                "committer": f"{metadata['committer_name']} <{metadata['committer_email']}>",
                "subject": metadata["subject"],
                "attribution_clean": not findings and not identity_problems,
            })
        return records, problems

    # ----------------------------------------------------------------- pushing
    def branch_name(self, phase_id: str | None) -> str:
        if self.policy.allow_existing_branch:
            return self.policy.allow_existing_branch
        slug = re.sub(r"[^a-z0-9]+", "-", (phase_id or "bootstrap").lower()).strip("-")
        return f"{self.policy.branch_prefix}/{slug}-{self.run_id.rsplit('-', 1)[-1]}"

    def push(self, candidate: Path, *, commit_sha: str, branch: str) -> dict:
        """Push, having established the target is safe, then read the ref back."""
        checks: list[Check] = []
        remote = self.policy.remote
        url = git.remote_url(candidate, remote)
        if url is None:
            raise PublicationRefusal(
                f"remote {remote!r} is not configured in this repository",
                [{"name": "remote configured", "passed": False, "detail": f"no remote {remote!r}"}],
            )
        checks.append(Check("remote configured", True, f"{remote} -> {url}"))

        if branch in self.policy.protected_branches:
            raise PublicationRefusal(
                f"refusing to push to the protected branch {branch!r}",
                [{"name": "target is not protected", "passed": False,
                  "detail": f"{branch} is in protected_branches"}],
            )
        checks.append(Check("target is not a protected branch", True,
                            f"{branch} is not in {list(self.policy.protected_branches)}"))

        ref_findings = scan_ref_name(branch)
        if ref_findings:
            raise PublicationRefusal(
                "the branch name carries assistant attribution",
                [{"name": "branch name", "passed": False,
                  "detail": "; ".join(str(f) for f in ref_findings)}],
            )
        checks.append(Check("branch name carries no attribution", True, branch))

        try:
            existing = git.ls_remote(candidate, remote, f"refs/heads/{branch}")
        except git.GitError as exc:
            # An unreachable remote is a refusal with the local work preserved,
            # not an exception escaping into the run loop.
            raise PublicationRefusal(
                f"could not read {remote} before pushing: {exc}. Nothing was pushed and the "
                f"verified local commit is preserved.",
                [*(c.to_dict() for c in checks),
                 {"name": "remote reachable", "passed": False, "detail": str(exc)[:600]}],
            ) from exc
        if existing:
            # The branch is already there. Publishing is only allowed when what
            # is there is an ancestor of what is being published, so nothing is
            # overwritten. There is no force-push path.
            is_ancestor = git.git(
                candidate, ["merge-base", "--is-ancestor", existing, commit_sha], check=False,
            ).returncode == 0
            if not is_ancestor:
                raise PublicationRefusal(
                    f"{remote}/{branch} is at {existing[:12]}, which is not an ancestor of "
                    f"{commit_sha[:12]}. The target moved incompatibly. The verified local "
                    f"result is preserved; integrate the remote change under a new validation "
                    f"cycle rather than overwriting it.",
                    [*(c.to_dict() for c in checks),
                     {"name": "fast-forward only", "passed": False,
                      "detail": f"remote {existing[:12]} is not an ancestor of {commit_sha[:12]}"}],
                )
            checks.append(Check("fast-forward only", True,
                                f"remote {existing[:12]} is an ancestor of {commit_sha[:12]}"))
        else:
            checks.append(Check("target branch is new", True,
                                f"{remote}/{branch} does not exist yet"))

        result = git.git(
            candidate, ["push", remote, f"{commit_sha}:refs/heads/{branch}"],
            check=False, timeout=600,
        )
        if not result.ok:
            raise PublicationRefusal(
                f"push to {remote}/{branch} failed: "
                f"{(result.stderr or result.stdout).strip()[:600]}",
                [*(c.to_dict() for c in checks),
                 {"name": "push", "passed": False,
                  "detail": (result.stderr or result.stdout).strip()[:600]}],
            )
        checks.append(Check("push", True, f"pushed {commit_sha[:12]} to {remote}/{branch}"))

        # The push exiting zero is not the evidence. This is.
        try:
            observed = git.ls_remote(candidate, remote, f"refs/heads/{branch}")
        except git.GitError as exc:
            raise PublicationRefusal(
                f"the push reported success but {remote}/{branch} could not be read back "
                f"to confirm it: {exc}",
                [*(c.to_dict() for c in checks),
                 {"name": "remote ref matches the intended commit", "passed": False,
                  "detail": str(exc)[:600]}],
            ) from exc
        matched = observed == commit_sha
        checks.append(Check(
            "remote ref matches the intended commit", matched,
            f"{remote}/{branch} is at {observed}" if observed else
            f"{remote}/{branch} could not be read back",
        ))
        if not matched:
            raise PublicationRefusal(
                f"after pushing, {remote}/{branch} reads back as {observed}, not {commit_sha}",
                [c.to_dict() for c in checks],
            )
        return {"remote": remote, "remote_url": url, "branch": branch,
                "remote_sha": observed, "checks": [c.to_dict() for c in checks]}

    # ----------------------------------------------------------------- receipt
    def receipt(self, *, published: bool, base_commit: str, commit_sha: str | None,
                tree_fingerprint_value: str | None, approved_fingerprint: str | None,
                branch: str | None, remote: str | None, remote_url: str | None,
                remote_sha: str | None, new_commits: list[dict], checks: list[dict],
                ci_status: str, notes: list[str]) -> dict:
        document = {
            "schema_version": "publication_receipt/v1",
            "run_id": self.run_id,
            "published": published,
            "mode": self.policy.mode,
            "base_commit": base_commit,
            "commit_sha": commit_sha,
            "tree_fingerprint": tree_fingerprint_value,
            "approved_fingerprint": approved_fingerprint,
            "branch": branch,
            "remote": remote,
            "remote_url": remote_url,
            "remote_sha_after_push": remote_sha,
            "new_commits": new_commits,
            "identity": {
                "expected_name": self.policy.author_name,
                "expected_email": self.policy.author_email,
                "verified": all(c.get("attribution_clean", False) for c in new_commits)
                and bool(new_commits),
            },
            "checks": checks,
            "ci_status": ci_status,
            "notes": notes,
        }
        validate_artifact(document, "publication_receipt/v1")
        return document
