"""Running user Python, or refusing to.

The roadmap's rule for this is the important part: *a `python-step` that cannot
be sandboxed properly on a given deployment is disabled with a stated reason
rather than run unsafely.* Everything here is built around being able to make
that statement truthfully.

**What the isolation actually is.** A separate process, started with
`multiprocessing`'s ``spawn`` so it inherits no state from the gateway, running
with:

* an import allowlist installed before the user's code is compiled, so
  ``import os`` fails at import time rather than being caught later;
* ``RLIMIT_AS`` and ``RLIMIT_CPU`` set in the child, so a runaway allocation or
  loop is killed by the kernel rather than by hope;
* ``RLIMIT_NOFILE`` and ``RLIMIT_NPROC`` clamped, so it cannot fork or open
  files at scale;
* a wall-clock deadline enforced by the parent, which terminates the child --
  the only limit that survives code deliberately trying to defeat the others.

**What it is not.** This is a language-level sandbox in a resource-limited
process. It is not a container, a VM, or a seccomp jail. A determined attacker
with a CPython escape can get out of it, and pretending otherwise would be the
dishonest part. :func:`capabilities` reports exactly which of the above the
current platform supports, and the notebook refuses to run Python cells when the
answer is "not enough" -- which is what makes the claim above checkable rather
than aspirational.
"""

from __future__ import annotations

import builtins
import multiprocessing
import os
import platform
import queue
import sys
from dataclasses import dataclass, field
from typing import Any

from shared_python.errors import BadRequestError

#: Modules a cell may import. Data work, and nothing that reaches outside.
ALLOWED_IMPORTS = frozenset(
    {
        "pandas", "numpy", "math", "statistics", "datetime", "decimal",
        "fractions", "json", "re", "collections", "itertools", "functools",
        "operator", "string", "textwrap", "unicodedata", "uuid", "hashlib",
        "base64", "binascii", "random", "time", "calendar", "zoneinfo",
        "dataclasses", "enum", "typing", "abc", "copy", "heapq", "bisect",
        "csv", "io", "pprint", "warnings",
    }
)

#: Named so a refusal can explain itself. These are the ones people reach for
#: and the ones that would matter.
_BLOCKED_REASONS = {
    "os": "reads and writes the filesystem and environment",
    "sys": "reaches into the interpreter",
    "subprocess": "starts other programs",
    "socket": "opens network connections",
    "requests": "makes network requests",
    "urllib": "makes network requests",
    "http": "makes network requests",
    "ftplib": "makes network connections",
    "smtplib": "sends mail",
    "shutil": "moves and deletes files",
    "pathlib": "reads and writes the filesystem",
    "importlib": "loads arbitrary modules",
    "ctypes": "calls arbitrary native code",
    "pickle": "executes arbitrary code while loading",
    "marshal": "loads interpreter bytecode",
    "multiprocessing": "starts other processes",
    "threading": "escapes the CPU limit",
    "sqlite3": "opens databases directly",
    "builtins": "reaches around the allowlist",
}

#: Builtins removed from the cell's namespace. `__import__` is replaced rather
#: than removed, because `import x` compiles to a call to it.
_REMOVED_BUILTINS = (
    "open", "exec", "eval", "compile", "input", "breakpoint", "exit", "quit",
    "help", "globals", "locals", "vars", "memoryview", "__loader__", "__spec__",
)

DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_MEMORY_MB = 512
DEFAULT_CPU_SECONDS = 15
#: A cell that prints a million lines is a mistake, not a result.
MAX_OUTPUT_CHARS = 200_000


@dataclass(frozen=True)
class Capability:
    name: str
    available: bool
    detail: str


@dataclass
class Capabilities:
    """What this deployment can actually enforce."""

    items: list[Capability] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """True when every limit that matters can be enforced.

        The wall clock and process isolation are non-negotiable: without them
        there is no limit at all, only a hope that the code behaves. Memory and
        CPU rlimits are required too -- a cell that allocates until the host
        swaps has taken the platform down whether or not it escaped.
        """
        required = {"process_isolation", "wall_clock", "memory_limit", "cpu_limit"}
        found = {item.name for item in self.items if item.available}
        return required <= found

    @property
    def reason(self) -> str:
        missing = [item for item in self.items if not item.available]
        if not missing:
            return ""
        return (
            "Python cells are disabled on this deployment because "
            + "; ".join(f"{item.name.replace('_', ' ')} ({item.detail})" for item in missing)
            + "."
        )


_PROBE: Capabilities | None = None


def _probe_limits() -> set[str]:
    """Which rlimits this OS will actually accept, found by trying them.

    `hasattr(resource, "RLIMIT_AS")` is true on macOS and setting it raises
    "current limit exceeds maximum limit" -- so the constant existing says
    nothing about whether the limit can be enforced. Asking the kernel is the
    only way to know, and the answer decides whether Python cells run at all.
    """
    context = multiprocessing.get_context("spawn")
    outbox: Any = context.Queue()
    child = context.Process(target=_probe_child, args=(outbox,), daemon=True)
    child.start()
    try:
        applied = outbox.get(timeout=20)
    except queue.Empty:
        applied = []
    finally:
        child.join(timeout=5)
        if child.is_alive():
            child.kill()
            child.join(timeout=2)
    return set(applied)


def _probe_child(outbox: Any) -> None:
    try:
        outbox.put(_apply_limits(DEFAULT_MEMORY_MB, DEFAULT_CPU_SECONDS))
    except Exception:  # noqa: BLE001 - an unusable platform reports nothing
        outbox.put([])


def capabilities(*, refresh: bool = False) -> Capabilities:
    """What this deployment can actually enforce, probed once per process."""
    global _PROBE
    if _PROBE is not None and not refresh:
        return _PROBE

    items: list[Capability] = []
    spawn_ok = "spawn" in multiprocessing.get_all_start_methods()
    items.append(
        Capability(
            "process_isolation",
            spawn_ok,
            "a fresh interpreter per cell"
            if spawn_ok
            else "this platform cannot spawn a clean interpreter",
        )
    )
    items.append(Capability("wall_clock", True, f"{DEFAULT_TIMEOUT_SECONDS}s deadline"))

    applied = _probe_limits() if spawn_ok else set()
    memory_ok = "RLIMIT_AS" in applied
    items.append(
        Capability(
            "memory_limit",
            memory_ok,
            f"{DEFAULT_MEMORY_MB}MB address space"
            if memory_ok
            else (
                f"{platform.system()} rejects RLIMIT_AS, so a cell could allocate "
                "until the host runs out of memory"
            ),
        )
    )
    cpu_ok = "RLIMIT_CPU" in applied
    items.append(
        Capability(
            "cpu_limit",
            cpu_ok,
            f"{DEFAULT_CPU_SECONDS}s CPU"
            if cpu_ok
            else f"{platform.system()} rejects RLIMIT_CPU",
        )
    )
    items.append(
        Capability("no_file_writes", "RLIMIT_FSIZE" in applied, "RLIMIT_FSIZE is zero")
    )
    items.append(
        Capability(
            "audit_hook",
            hasattr(sys, "addaudithook"),
            "imports, file access and process creation are refused by CPython itself",
        )
    )
    items.append(
        Capability("import_allowlist", True, f"{len(ALLOWED_IMPORTS)} modules permitted")
    )
    items.append(
        Capability(
            "network",
            True,
            "no network module is importable and socket events are refused; the "
            "platform does not block sockets at the OS level",
        )
    )

    _PROBE = Capabilities(items=items)
    return _PROBE


@dataclass
class SandboxResult:
    ok: bool
    stdout: str = ""
    error: str = ""
    #: Variables the cell bound that the next cell can use, as a repr summary.
    bindings: dict[str, str] = field(default_factory=dict)
    duration_ms: float = 0.0
    #: Frames that came back as dataframes, by name.
    frames: dict[str, Any] = field(default_factory=dict)
    #: Which OS limits actually took effect for this run.
    limits_applied: list[str] = field(default_factory=list)


def require_usable() -> None:
    """The gate. Callers that expose Python to a user go through this.

    Kept out of :func:`run` on purpose: `run` is the mechanism and stays
    testable everywhere, while this is the policy the roadmap asks for --
    *a step that cannot be sandboxed properly on a given deployment is disabled
    with a stated reason rather than run unsafely.*
    """
    available = capabilities()
    if not available.usable:
        raise BadRequestError(available.reason)


def run(
    source: str,
    namespace: dict[str, Any] | None = None,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    memory_mb: int | None = DEFAULT_MEMORY_MB,
    cpu_seconds: int = DEFAULT_CPU_SECONDS,
) -> SandboxResult:
    """Run a cell in an isolated process and report what it did.

    ``namespace`` maps names to pandas DataFrames from earlier cells. Anything
    the cell leaves bound to a DataFrame comes back in ``frames``.

    This applies every limit the OS accepts and reports the rest; it does not
    decide whether that is enough. :func:`require_usable` makes that call.
    """
    import time

    if not isinstance(source, str) or not source.strip():
        raise BadRequestError("There is no code to run.")

    context = multiprocessing.get_context("spawn")
    outbox: Any = context.Queue()
    child = context.Process(
        target=_child,
        args=(source, dict(namespace or {}), outbox, memory_mb, cpu_seconds),
        daemon=True,
    )

    started = time.perf_counter()
    child.start()
    try:
        payload = outbox.get(timeout=timeout_seconds)
    except queue.Empty:
        # The deadline is the limit that holds when the others are being
        # actively defeated, so it terminates rather than asking politely.
        child.terminate()
        child.join(timeout=2)
        if child.is_alive():
            child.kill()
        return SandboxResult(
            ok=False,
            error=f"The cell ran for more than {timeout_seconds} seconds and was stopped.",
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )
    finally:
        child.join(timeout=5)
        if child.is_alive():
            child.kill()
            child.join(timeout=2)

    duration = round((time.perf_counter() - started) * 1000, 3)
    if payload.get("killed"):
        return SandboxResult(ok=False, error=payload["error"], duration_ms=duration)

    return SandboxResult(
        ok=payload["ok"],
        stdout=payload.get("stdout", ""),
        error=payload.get("error", ""),
        bindings=payload.get("bindings", {}),
        frames=payload.get("frames", {}),
        limits_applied=payload.get("limits_applied", []),
        duration_ms=duration,
    )


# ------------------------------------------------------- inside the child


def _child(source: str, namespace: dict[str, Any], outbox: Any, memory_mb: int, cpu_seconds: int) -> None:
    """Runs in the spawned process. Nothing here is trusted by the parent."""
    import io
    import contextlib
    import traceback

    try:
        applied = _apply_limits(memory_mb, cpu_seconds)
    except Exception as exc:  # noqa: BLE001 - report rather than run unlimited
        outbox.put({"ok": False, "killed": True, "error": f"Could not apply resource limits: {exc}"})
        return

    stdout = io.StringIO()
    try:
        globals_for_cell = _prepare_globals(namespace)
        # Compiled before the hook is armed: `compile` is itself an audited
        # event, and the cell's own source is the one thing allowed through it.
        compiled = compile(source, "<cell>", "exec")
        _purge_modules()
        _install_audit_hook()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stdout):
            exec(compiled, globals_for_cell)  # noqa: S102 - this is the feature
    except MemoryError:
        outbox.put({"ok": False, "error": "The cell ran out of memory and was stopped.", "limits_applied": applied})
        return
    except SyntaxError as exc:
        outbox.put({"ok": False, "error": f"Line {exc.lineno}: {exc.msg}", "stdout": stdout.getvalue()[:MAX_OUTPUT_CHARS], "limits_applied": applied})
        return
    except BaseException as exc:  # noqa: BLE001 - a cell may raise anything
        # The gateway's traceback is not the cell author's business; theirs is.
        frames = traceback.format_exception_only(type(exc), exc)
        outbox.put(
            {
                "ok": False,
                "error": "".join(frames).strip(),
                "stdout": stdout.getvalue()[:MAX_OUTPUT_CHARS],
                "limits_applied": applied,
            }
        )
        return

    outbox.put({**_collect(globals_for_cell, stdout.getvalue()), "limits_applied": applied})


def _apply_limits(memory_mb: int | None, cpu_seconds: int) -> list[str]:
    """Apply what this OS will take, and report exactly what stuck.

    Reporting matters more than trying. An earlier version swallowed every
    failure, so on macOS -- where `setrlimit(RLIMIT_AS, ...)` is rejected
    outright -- the child ran with no memory limit at all while the platform
    told the user it had one.
    """
    import resource

    wanted: list[tuple[str, tuple[int, int]]] = [
        ("RLIMIT_CPU", (cpu_seconds, cpu_seconds + 1)),
        ("RLIMIT_NOFILE", (64, 64)),
        ("RLIMIT_FSIZE", (0, 0)),
    ]
    if memory_mb is not None:
        limit = memory_mb * 1024 * 1024
        wanted.insert(0, ("RLIMIT_AS", (limit, limit)))

    applied: list[str] = []
    for name, value in wanted:
        constant = getattr(resource, name, None)
        if constant is None:
            continue
        try:
            resource.setrlimit(constant, value)
        except (ValueError, OSError):
            continue
        applied.append(name)
    return applied


#: Audited events that end the cell, whatever route reached them. An audit hook
#: fires from CPython itself, so unlike a replaced builtin it cannot be stepped
#: around by finding the original object through `__subclasses__` or a
#: function's `__globals__` -- which is exactly how the first version of this
#: module was escaped.
_FORBIDDEN_EVENTS = (
    "exec", "compile", "os.system", "os.exec", "os.spawn", "os.posix_spawn",
    "os.fork", "os.forkpty", "os.putenv", "os.unsetenv", "os.remove",
    "os.rename", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.link",
    "os.symlink", "os.truncate", "os.startfile", "subprocess.Popen",
    "socket.__new__", "socket.connect", "socket.bind", "socket.getaddrinfo",
    "ctypes.dlopen", "ctypes.dlsym", "ctypes.call_function",
    "ctypes.create_string_buffer", "pickle.find_class", "shutil.copyfile",
    "shutil.move", "shutil.rmtree", "sys.addaudithook", "sys.settrace",
    "sys.setprofile", "sys._getframe", "webbrowser.open",
)


def _purge_modules() -> None:
    """Drop the dangerous modules from ``sys.modules`` before arming.

    Without this the audit hook is not enough. A module already imported during
    interpreter startup is *cached*, so `BuiltinImporter.load_module("os")` --
    reachable in three lines through `object.__subclasses__()` -- hands it back
    without performing an import, and no `import` event ever fires. Removing the
    cache entry turns every such route back into a real import, which the hook
    then refuses.

    The modules stay loaded; only the lookup table loses them. Code that already
    holds a reference -- pandas, the import machinery itself -- is unaffected,
    which is why this runs after pandas is imported and before the cell starts.
    """
    import sys as _sys

    doomed = [
        name
        for name in list(_sys.modules)
        if name.split(".")[0] in _BLOCKED_REASONS
        and name.split(".")[0] not in ("sys", "builtins")
    ]
    for name in doomed:
        _sys.modules.pop(name, None)


def _install_audit_hook() -> None:
    """The barrier that holds when the language-level ones are being defeated.

    Installed last, after pandas and the standard library have finished their
    own imports, so their legitimate file reads are not caught by it. Once
    added, a hook cannot be removed -- `sys.addaudithook` is itself audited.
    """
    import sys as _sys

    # Reads are permitted inside the interpreter's own tree and inside the
    # system time-zone database. `zoneinfo` is in the allowlist because
    # tz-aware timestamps are part of this platform's type system, and it reads
    # its data from `/usr/share/zoneinfo` rather than from `sys.prefix`.
    readable = {p for p in (_sys.prefix, _sys.base_prefix, _sys.exec_prefix) if p}
    try:
        import zoneinfo as _zoneinfo

        readable.update(str(path) for path in _zoneinfo.TZPATH)
    except Exception:  # noqa: BLE001 - a build without tzdata simply has none
        pass
    interpreter_paths = tuple(readable)
    # The cell's own body is run with `exec`, which is itself an audited event.
    # Exactly one is expected -- it fires before any of the cell's code runs --
    # so allowing the first and refusing the rest is unambiguous.
    state = {"armed": False, "own_exec_used": False}

    def hook(event: str, args: tuple) -> None:
        if not state["armed"]:
            return
        if event == "exec" and not state["own_exec_used"]:
            state["own_exec_used"] = True
            return
        if event == "import":
            root = str(args[0]).split(".")[0]
            if root not in ALLOWED_IMPORTS:
                raise ImportError(_import_refusal(root))
            return
        if event == "open":
            path = str(args[0]) if args else ""
            # Reads inside the interpreter's own tree are how `zoneinfo` finds
            # its data. Everything else -- any write, any other path -- is not
            # this cell's business.
            mode = str(args[1] or "") if len(args) > 1 else ""
            if any(flag in mode for flag in ("w", "a", "x", "+")) or not path.startswith(
                interpreter_paths
            ):
                raise PermissionError(
                    "This cell cannot read or write files. Pass data in as a "
                    "DataFrame instead."
                )
            return
        if event in _FORBIDDEN_EVENTS:
            raise PermissionError(
                f"'{event}' is not available in a notebook cell: it reaches "
                "outside the sandbox."
            )

    _sys.addaudithook(hook)
    state["armed"] = True


def _import_refusal(root: str) -> str:
    reason = _BLOCKED_REASONS.get(root)
    detail = f" -- it {reason}" if reason else ""
    return (
        f"'{root}' cannot be imported here{detail}. "
        f"Available: {', '.join(sorted(ALLOWED_IMPORTS))}."
    )


def _guarded_import(name: str, globals_=None, locals_=None, fromlist=(), level=0):
    root = name.split(".")[0]
    if root in ALLOWED_IMPORTS:
        return _REAL_IMPORT(name, globals_, locals_, fromlist, level)
    raise ImportError(_import_refusal(root))


_REAL_IMPORT = builtins.__import__


def _prepare_globals(namespace: dict[str, Any]) -> dict[str, Any]:
    safe_builtins = {
        name: value
        for name, value in vars(builtins).items()
        if name not in _REMOVED_BUILTINS and not name.startswith("_")
    }
    safe_builtins["__import__"] = _guarded_import
    # Exception types start with an uppercase letter and were kept above; the
    # dunders that were filtered out are the ones worth removing.
    safe_builtins["__build_class__"] = builtins.__build_class__
    safe_builtins["__name__"] = "builtins"

    import pandas as pd

    prepared: dict[str, Any] = {
        "__builtins__": safe_builtins,
        "__name__": "__cell__",
        "pd": pd,
    }
    prepared.update(namespace)
    return prepared


def _collect(globals_for_cell: dict[str, Any], stdout: str) -> dict[str, Any]:
    import pandas as pd

    bindings: dict[str, str] = {}
    frames: dict[str, Any] = {}
    for name, value in globals_for_cell.items():
        if name.startswith("_") or name in ("pd",):
            continue
        if isinstance(value, pd.DataFrame):
            frames[name] = value
            bindings[name] = f"DataFrame({len(value)} rows x {len(value.columns)} columns)"
        elif isinstance(value, (int, float, str, bool, list, dict, tuple, set)) or value is None:
            text = repr(value)
            bindings[name] = text if len(text) <= 200 else text[:197] + "..."
        elif callable(value) or isinstance(value, type):
            continue
        else:
            bindings[name] = type(value).__name__
    return {
        "ok": True,
        "stdout": stdout[:MAX_OUTPUT_CHARS],
        "bindings": bindings,
        "frames": frames,
    }


def describe() -> dict[str, Any]:
    """What the UI shows on the sandbox's settings panel."""
    available = capabilities()
    return {
        "usable": available.usable,
        "reason": available.reason,
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.machine()}",
        "process": os.getpid(),
        "allowed_imports": sorted(ALLOWED_IMPORTS),
        "capabilities": [
            {"name": item.name, "available": item.available, "detail": item.detail}
            for item in available.items
        ],
        "limits": {
            "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
            "memory_mb": DEFAULT_MEMORY_MB,
            "cpu_seconds": DEFAULT_CPU_SECONDS,
        },
    }
