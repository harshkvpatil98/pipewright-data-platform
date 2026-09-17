"""Every Git call this tool makes.

Git is invoked with `-c` overrides rather than by touching the operator's
configuration, and with `GIT_*` identity variables stripped from the child
environment (see `util.proc.ENV_DENYLIST`) so an inherited `GIT_AUTHOR_NAME`
cannot quietly re-author a commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..errors import PwDevError
from ..util import proc


class GitError(PwDevError):
    def __init__(self, argv: list[str], result: proc.ProcResult) -> None:
        self.argv = argv
        self.result = result
        super().__init__(
            f"git {' '.join(argv)} failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()[:600]}"
        )


@dataclass(frozen=True)
class WorkingTreeState:
    """What the repository looked like when the run captured its baseline."""

    head_sha: str
    branch: str | None
    dirty_paths: list[str]
    untracked_paths: list[str]
    remotes: dict[str, str]

    @property
    def clean(self) -> bool:
        return not self.dirty_paths and not self.untracked_paths


def git(
    repo: Path, argv: list[str], *, timeout: float = 600.0, check: bool = True,
    env_overrides: dict[str, str] | None = None, input_text: str | None = None,
) -> proc.ProcResult:
    # The identity variables are passed as trusted overrides: the child
    # environment is still built from an allowlist, so an inherited GIT_AUTHOR_*
    # never survives, and the only values that reach Git are the ones the
    # publisher asserted.
    identity = {k: v for k, v in (env_overrides or {}).items()
                if k in proc.ENV_DENYLIST}
    plain = {k: v for k, v in (env_overrides or {}).items()
             if k not in proc.ENV_DENYLIST}
    env = proc.build_env(
        overrides={
            "GIT_TERMINAL_PROMPT": "0",  # never block an unattended run on a credential prompt
            "GIT_ADVICE": "0",
            **plain,
        },
        trusted_overrides=identity,
    )
    # SSH_AUTH_SOCK is forwarded when present so an ssh remote can authenticate
    # without this tool ever handling a key.
    import os

    if os.environ.get("SSH_AUTH_SOCK"):
        env["SSH_AUTH_SOCK"] = os.environ["SSH_AUTH_SOCK"]
    result = proc.run(["git", *argv], cwd=repo, env=env, timeout=timeout,
                      stdin_data=input_text, max_output_bytes=32 * 1024 * 1024)
    if check and not result.ok:
        raise GitError(argv, result)
    return result


def out(repo: Path, argv: list[str], **kwargs) -> str:
    return git(repo, argv, **kwargs).stdout.strip()


def head_sha(repo: Path) -> str:
    return out(repo, ["rev-parse", "HEAD"])


def current_branch(repo: Path) -> str | None:
    name = out(repo, ["rev-parse", "--abbrev-ref", "HEAD"], check=False)
    return None if name in ("", "HEAD") else name


def capture_state(repo: Path) -> WorkingTreeState:
    """Baseline capture.

    Uncommitted work is recorded, never touched. Nothing here stashes, resets or
    cleans: someone else's in-progress edit is not this tool's to discard.
    """
    # Not `out()`: porcelain status lines begin with a significant space for a
    # modified-but-unstaged file (" M path"), and stripping it shifts every
    # path by one character.
    status = git(repo, ["status", "--porcelain=v1", "-z"], check=False).stdout
    dirty: list[str] = []
    untracked: list[str] = []
    for entry in status.split("\0"):
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        (untracked if code == "??" else dirty).append(path)
    remotes: dict[str, str] = {}
    for line in out(repo, ["remote", "-v"], check=False).splitlines():
        parts = line.split()
        if len(parts) >= 2:
            remotes.setdefault(parts[0], parts[1])
    return WorkingTreeState(
        head_sha=head_sha(repo), branch=current_branch(repo),
        dirty_paths=sorted(dirty), untracked_paths=sorted(untracked), remotes=remotes,
    )


def add_worktree(repo: Path, path: Path, commit: str, branch: str) -> None:
    git(repo, ["worktree", "add", "--detach", "-f", str(path), commit])
    git(path, ["checkout", "-B", branch, commit])


def remove_worktree(repo: Path, path: Path) -> None:
    git(repo, ["worktree", "remove", "--force", str(path)], check=False)
    git(repo, ["worktree", "prune"], check=False)


def changed_paths(repo: Path, base: str) -> list[str]:
    """Paths changed against `base`, including files Git is not tracking yet.

    A worker that creates a new file has changed the candidate; a check that
    only reads `git diff` would not see it. The controller's own scratch and the
    debris a check leaves behind are excluded -- `compileall` writing
    `__pycache__` while verifying a tree is not a change to that tree.
    """
    from .patches import CONTROLLER_SCRATCH

    spec = ["--", ".", *CONTROLLER_SCRATCH]
    tracked = out(repo, ["diff", "--name-only", base, *spec], check=False)
    staged = out(repo, ["diff", "--name-only", "--cached", base, *spec], check=False)
    untracked = out(
        repo, ["ls-files", "--others", "--exclude-standard", *spec], check=False
    )
    paths = {p for p in (*tracked.splitlines(), *staged.splitlines(), *untracked.splitlines()) if p}
    return sorted(paths)


def commit_metadata(repo: Path, sha: str) -> dict[str, str]:
    fields = out(repo, [
        "show", "-s", "--format=%an%x1f%ae%x1f%cn%x1f%ce%x1f%s%x1f%b%x1f%GS", sha,
    ])
    parts = fields.split("\x1f")
    while len(parts) < 7:
        parts.append("")
    return {
        "author_name": parts[0], "author_email": parts[1],
        "committer_name": parts[2], "committer_email": parts[3],
        "subject": parts[4], "body": parts[5], "signer": parts[6],
    }


def commits_between(repo: Path, base: str, head: str) -> list[str]:
    body = out(repo, ["rev-list", f"{base}..{head}"], check=False)
    return [line for line in body.splitlines() if line]


def notes_for(repo: Path, sha: str) -> str:
    return out(repo, ["notes", "show", sha], check=False)


def remote_url(repo: Path, remote: str) -> str | None:
    value = out(repo, ["remote", "get-url", remote], check=False)
    return value or None


def ls_remote(repo: Path, remote: str, ref: str) -> str | None:
    """The remote's current SHA for a ref, or None when the ref does not exist."""
    result = git(repo, ["ls-remote", remote, ref], check=False, timeout=180)
    if not result.ok:
        raise GitError(["ls-remote", remote, ref], result)
    for line in result.stdout.splitlines():
        sha, _, name = line.partition("\t")
        if name.strip() in (ref, f"refs/heads/{ref}"):
            return sha.strip()
    return None


def signing_configured(repo: Path) -> tuple[bool, str | None]:
    """Whether commits are expected to be signed, and with what.

    Signing requirements are preserved: if the repository asks for signed
    commits and no signing credential is available, that is reported, never
    silently disabled with `--no-gpg-sign`.
    """
    want = out(repo, ["config", "--get", "commit.gpgsign"], check=False).lower() == "true"
    fmt = out(repo, ["config", "--get", "gpg.format"], check=False) or "openpgp"
    return want, (fmt if want else None)
