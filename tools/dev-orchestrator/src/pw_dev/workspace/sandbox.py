"""The actual write boundary for worker processes.

A git worktree stops two workers editing the same file. It is not a security
boundary: worktrees share `.git`, and a process inside one can write anywhere
the user can. So the boundary is enforced by the operating system.

On macOS that is `sandbox-exec`, which was verified on this host: a process
launched under the profile below can read the filesystem but can only write
inside the roots it was given, and a write to `$HOME` fails with EPERM rather
than being noticed afterwards.

Where no enforceable mechanism exists, `detect_sandbox_support` says so and the
controller refuses to run unattended. Supervised execution is still offered,
with the limitation stated -- not a post-run diff check described as if it
prevented anything.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SandboxSupport:
    """What this host can actually enforce."""

    available: bool
    mechanism: str
    detail: str
    verified: bool = False

    def describe(self) -> str:
        state = "enforced" if self.available else "not available"
        checked = " (verified by probe)" if self.verified else ""
        return f"{self.mechanism}: {state}{checked} -- {self.detail}"


_PROFILE = """(version 1)

;; Reading is allowed: a worker has to be able to read the repository, its
;; toolchain and the standard library. Writing is denied by default and
;; re-granted only for the roots this task owns.
(allow default)
(deny file-write*)

(allow file-write*
{write_roots})

;; Standard streams and the null device, which everything needs.
(allow file-write-data
    (literal "/dev/null")
    (literal "/dev/stdout")
    (literal "/dev/stderr")
    (literal "/dev/dtracehelper"))
(allow file-write* (regex #"^/dev/tty"))
(allow file-ioctl (literal "/dev/dtracehelper"))
{denied}{regranted}"""


def detect_sandbox_support(*, probe: bool = True) -> SandboxSupport:
    """Report -- and optionally prove -- the host's write-confinement mechanism."""
    if sys.platform == "darwin":
        binary = shutil.which("sandbox-exec")
        if binary is None:
            return SandboxSupport(
                False, "sandbox-exec",
                "not present on PATH; macOS normally ships it at /usr/bin/sandbox-exec",
            )
        if not probe:
            return SandboxSupport(True, "sandbox-exec", f"found at {binary}")
        ok, detail = _probe_macos(binary)
        return SandboxSupport(ok, "sandbox-exec", detail, verified=ok)

    if sys.platform.startswith("linux"):
        # bubblewrap is the equivalent here. It is reported honestly rather than
        # implemented blind: this build was developed and verified on macOS, and
        # claiming a Linux boundary that was never exercised would be the
        # precise failure this module exists to avoid.
        binary = shutil.which("bwrap")
        if binary is None:
            return SandboxSupport(
                False, "bubblewrap",
                "bwrap not found; install bubblewrap, or run supervised",
            )
        return SandboxSupport(
            False, "bubblewrap",
            f"bwrap found at {binary} but this build has no verified bubblewrap profile; "
            "treated as unavailable rather than assumed to work",
        )

    return SandboxSupport(
        False, "none", f"no verified write-confinement mechanism for platform {sys.platform!r}"
    )


def _probe_macos(binary: str) -> tuple[str, str] | tuple[bool, str]:
    """Prove the profile denies an out-of-root write before relying on it."""
    with tempfile.TemporaryDirectory(prefix="pw-dev-sbprobe-") as raw:
        base = Path(raw)
        allowed = base / "allowed"
        allowed.mkdir()
        outside = base / "outside"
        outside.mkdir()
        profile = base / "profile.sb"
        protected = allowed / "protected.txt"
        protected.write_text("do not change me", encoding="utf-8")
        profile.write_text(build_profile([allowed], [protected]), encoding="utf-8")

        def _run(script: str) -> subprocess.CompletedProcess:
            return subprocess.run(  # noqa: S603 - argv array, fixed interpreter
                [binary, "-f", str(profile), "/bin/sh", "-c", script],
                capture_output=True, text=True, timeout=60, check=False,
            )

        try:
            inside = _run(f"echo ok > {allowed / 'probe.txt'}")
            escape = _run(f"echo bad > {outside / 'probe.txt'}")
            carved = _run(f"echo bad > {protected}")
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"probe could not run: {exc}"

    if inside.returncode != 0:
        return False, f"a write inside the allowed root was denied: {inside.stderr.strip()[:200]}"
    if escape.returncode == 0:
        return False, "a write outside the allowed roots succeeded; the profile does not confine"
    if carved.returncode == 0:
        return False, ("a file carved out of a granted root was still writable; deny rules do "
                       "not override the allows on this host")
    return True, ("verified: writes are confined to the granted roots, escape attempts fail, "
                  "and carve-outs inside a granted root are denied")


def build_profile(write_roots: list[Path], deny_paths: list[Path] | None = None,
                  regrant_paths: list[Path] | None = None) -> str:
    """Render a Seatbelt profile granting writes only under `write_roots`.

    `deny_paths` are carved back out *after* the grants. Seatbelt applies the
    last matching rule, so a deny placed below an allow wins -- which is how a
    directory can be writable except for the few files inside it that must not
    change.
    """
    if not write_roots:
        raise ValueError("a sandbox with no writable root cannot run a worker")
    clauses = "\n".join(
        f'    (subpath "{_escape(str(Path(root).resolve()))}")' for root in write_roots
    )
    denied = ""
    if deny_paths:
        # Resolved, like the grants above. On macOS `/var` is a symlink to
        # `/private/var`, so an unresolved deny path never matches a resolved
        # allow and the carve-out silently does nothing.
        rules = "\n".join(
            f'    (subpath "{_escape(str(Path(path).resolve()))}")'
            if not Path(path).suffix
            else f'    (literal "{_escape(str(Path(path).resolve()))}")'
            for path in deny_paths
        )
        denied = (
            "\n;; Carved back out of the grants above. Seatbelt applies the last\n"
            ";; matching rule, so these deny rules beat the subpath allows.\n"
            f"(deny file-write*\n{rules})\n"
        )
    regranted = ""
    if regrant_paths:
        # Last matching rule wins, so these come after the denials: a directory
        # can be closed and one cache inside it opened again. Used where a tool
        # insists on writing beside the code it reads -- Vitest keeps its results
        # cache in `node_modules/.vite` -- without reopening the code itself.
        rules = "\n".join(
            f'    (subpath "{_escape(str(Path(path).resolve()))}")'
            for path in regrant_paths
        )
        regranted = (
            "\n;; Re-granted after the denials above, which they override.\n"
            f"(allow file-write*\n{rules})\n"
        )
    return _PROFILE.format(write_roots=clauses, denied=denied, regranted=regranted)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def claude_bash_workspace() -> Path:
    """Where Claude Code's Bash tool insists on keeping the shell's state.

    It creates `<tmp>/claude-<uid>/<slugified-cwd>` for the shell's working
    directory and a `<tmp>/claude-<hex>-cwd` file beside it -- and it takes
    `<tmp>` from the platform temporary directory, **not** from `TMPDIR`.
    Pointing the child's `TMPDIR` at a confined scratch does not move them,
    which is what made this look like an environment problem rather than a
    missing grant.

    Without it every Bash call failed before running anything:

        EPERM: operation not permitted, mkdir '/private/tmp/claude-501/...'

    and the unsandboxed fallback asked for an approval no headless worker can
    be given. So `Bash` sat in `WORKER_TOOLS`, granted and unusable, and
    workers edited code they could not run or test. Four repair rounds reasoned
    correctly about a failing test's symptom and never found its cause, because
    finding it needed one command.

    Granting the shared temporary directory is a real widening and a small one.
    It is world-writable already, so nothing here is newly reachable to anything
    else on the machine, and the repository, the operator's home and everything
    else outside the worktree stay denied -- which `test_isolation.py` asserts
    rather than assumes. Callers pass this alongside the worktree; the profile
    resolves it, so the `/tmp` -> `/private/tmp` symlink needs no special care.
    """
    return Path("/tmp")


def claude_config_denials(config_dir: Path) -> list[Path]:
    """Files inside the Claude config directory a worker must not change.

    A worker needs the operator's real config directory: Claude Code's
    subscription login resolves through it, and a fresh `CLAUDE_CONFIG_DIR`
    reports "Not logged in" even when the operator is signed in. Copying the
    account record does not help -- this was tested, not assumed.

    So the directory is granted, and the files that could change what happens in
    the operator's *next* interactive session are taken back: settings (which
    can define hooks that run automatically), plugins, agents, commands, and the
    top-level account file.
    """
    config_dir = Path(config_dir)
    return [
        config_dir / "settings.json",
        config_dir / "settings.local.json",
        config_dir / "plugins",
        config_dir / "agents",
        config_dir / "commands",
        config_dir / "hooks",
        config_dir / "skills",
        config_dir.parent / ".claude.json",
    ]


def sandbox_wrapper(write_roots: list[Path], profile_path: Path,
                    deny_paths: list[Path] | None = None,
                    regrant_paths: list[Path] | None = None):
    """Return a callable that wraps an argv in the enforced sandbox.

    Returns `None` when the host cannot enforce anything, so a caller cannot
    accidentally treat "no wrapper" as "confined".
    """
    support = detect_sandbox_support(probe=False)
    if not support.available or sys.platform != "darwin":
        return None
    profile_path = Path(profile_path)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        build_profile(write_roots, deny_paths, regrant_paths), encoding="utf-8")
    binary = shutil.which("sandbox-exec") or "/usr/bin/sandbox-exec"

    def wrap(argv: list[str]) -> list[str]:
        return [binary, "-f", str(profile_path), *argv]

    return wrap


def already_sandboxed() -> bool:
    """Whether this process is itself running inside a Seatbelt sandbox.

    Nesting does not work: a profile applied inside an existing sandbox fails
    to initialise and `sandbox-exec` exits 71 without running the command. That
    matters because verification is now confined, so the orchestrator's own
    tests -- which prove worker isolation by *using* `sandbox-exec` -- run one
    level inside it when the suite runs as a check.

    Detected by trying it, once, rather than by reading an environment variable
    a caller could set. A host with no `sandbox-exec` at all answers `False`:
    there is no sandbox to be inside.
    """
    global _NESTED
    if _NESTED is not None:
        return _NESTED
    binary = shutil.which("sandbox-exec")
    if binary is None or sys.platform != "darwin":
        _NESTED = False
        return _NESTED
    with tempfile.NamedTemporaryFile("w", suffix=".sb", delete=False) as handle:
        handle.write("(version 1)\n(allow default)\n")
        profile = handle.name
    try:
        probe = subprocess.run(  # noqa: S603 - fixed argv
            [binary, "-f", profile, "/usr/bin/true"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        _NESTED = probe.returncode != 0
    except (OSError, subprocess.SubprocessError):
        _NESTED = True
    finally:
        Path(profile).unlink(missing_ok=True)
    return _NESTED


_NESTED: bool | None = None


def resolve_mode(configured: str, support: SandboxSupport) -> str:
    """Turn `auto` into a concrete mode, and refuse a mode the host cannot honour."""
    if configured == "off":
        return "off"
    if configured == "enforced":
        if not support.available:
            raise RuntimeError(
                f"isolation.mode is 'enforced' but this host cannot enforce it "
                f"({support.describe()})"
            )
        return "enforced"
    if configured == "supervised":
        return "supervised"
    return "enforced" if support.available else "supervised"
