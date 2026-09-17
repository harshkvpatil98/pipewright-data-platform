"""A Python environment for one checkout, that imports *that* checkout's code.

## The problem this solves

Pipewright installs its twenty-six first-party packages with `pip install -e`.
A git worktree gets none of that: `.venv` is ignored, so a fresh checkout has no
interpreter and every check declaring `requires=("venv",)` records `not_run` --
which is honest, and means a run can never close its completion gate.

The obvious fix is worse than the problem. Symlinking the original checkout's
`.venv` makes the checks *run*, and every one of them tests the original
checkout's source, because that is where the editable installs point. A check
that passes against code nobody is publishing is the exact false pass the whole
verification design exists to prevent.

## What this does instead

Each checkout gets its own real virtualenv, and its `sys.path` is composed so
that **first-party source comes from the checkout and third-party packages come
from the original installation**:

```
<checkout>/.venv/lib/pythonX.Y/site-packages/_pw_dev_sources.pth
    <checkout>/packages/*/src          <- first
    <checkout>/services/*/src
    <checkout>/apps/api-gateway/src
    <checkout>/tools/dev-orchestrator/src
    <root>/.venv/lib/pythonX.Y/site-packages   <- last: third-party only
```

`site.py` appends a `.pth` file's lines to `sys.path` in order, so the
checkout's sources precede the shared directory. Crucially, adding the root's
site-packages as a *path* does not make it a *site directory*: the
`__editable__.*.pth` files inside it are never processed, so the original
checkout's source directories never enter `sys.path` at all. Third-party
distributions, which are ordinary directories, resolve normally.

This was measured rather than assumed. Every first-party module resolves inside
the checkout; a change made only in the checkout is visible only there; and
`assert_module_origins` proves it per run rather than trusting the construction.

## What it deliberately does not do

* **It does not install anything.** No network, no wheel builds, no per-check
  environment. Preparation is filesystem work and finishes in well under a
  second, which is why every checkout can afford its own.
* **It does not make the original installation writable.** The shared directory
  is referenced by path. A worker's sandbox grants writes under its checkout
  only, so a write through that path is refused by the operating system rather
  than by convention.
* **It does not copy secrets.** `.env` files, credential stores and databases
  are not touched. Only `bin/` launcher scripts are reproduced, with their
  interpreter path rewritten.
* **It does not hide a stale environment.** The inputs that define an
  environment are digested into a stamp. A checkout whose stamp does not match
  is rebuilt, so a resumed run cannot reuse an environment built for a different
  tree, interpreter or shared installation.

## The dependency it cannot satisfy

A checkout that declares a **new third-party dependency** has no way to get it
from a shared installation that predates it. `missing_requirements` reports
exactly that, by name, and the caller turns it into a non-passing state -- it is
not silently absent from `sys.path` and discovered as an ImportError inside a
test.
"""

from __future__ import annotations

import importlib.machinery as machinery
import json
import os
import re
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ..util.hashing import digest_json

#: Written into the checkout's site-packages. One file, so the composition is
#: readable with `cat` when something looks wrong.
PTH_NAME = "_pw_dev_sources.pth"

#: Records what the environment was built from, so reuse is a decision rather
#: than an assumption.
STAMP_NAME = ".pw-dev-environment.json"

#: Where first-party source lives, relative to a checkout. These are the same
#: locations `scripts/setup.sh` installs from; globbing the *checkout* means a
#: package the checkout adds is picked up without anyone editing this list.
SOURCE_GLOBS = ("packages/*/src", "services/*/src")
SOURCE_PATHS = ("apps/api-gateway/src", "tools/dev-orchestrator/src")

#: Launchers that belong to the new environment and must not be copied from the
#: old one.
_SKIP_SCRIPTS = frozenset({
    "activate", "activate.csh", "activate.fish", "activate.nu", "activate.ps1",
    "Activate.ps1", "activate_this.py", "python", "python3", "pip", "pip3",
})

_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")

#: Modules CPython imports by itself during interpreter startup, from anywhere
#: on `sys.path`. A first-party source root is on the `sys.path` of the
#: interpreter the controller runs verification with, and that runs unsandboxed
#: -- so one of these in a checkout would execute during every check and could
#: exit zero in silence. `workspace.guard.ALWAYS_FORBIDDEN` stops a task writing
#: one; this refuses to prepare a checkout that has one anyway.
STARTUP_HOOKS = ("sitecustomize", "usercustomize")

#: Every suffix this interpreter imports a module from.
_IMPORTABLE_SUFFIXES = tuple(sorted(set(
    machinery.SOURCE_SUFFIXES + machinery.BYTECODE_SUFFIXES
    + machinery.EXTENSION_SUFFIXES
)))


@dataclass
class EnvironmentReport:
    """What preparing one checkout's environment established, or could not."""

    checkout: Path
    prepared: bool
    reused: bool = False
    interpreter: Path | None = None
    source_roots: tuple[str, ...] = ()
    shared_site_packages: str | None = None
    console_scripts: int = 0
    missing_requirements: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    duration_seconds: float = 0.0
    stamp: str = ""

    @property
    def usable(self) -> bool:
        """Whether a check may be run here and mean anything.

        An unsatisfied applicable requirement counts against it. Leaving it as a
        note was the weaker choice: a run whose tests happen not to import the
        missing package would close its gate while the environment did not match
        what the checkout declared it needed.
        """
        return self.prepared and not self.problems and not self.missing_requirements

    def describe(self) -> str:
        if not self.prepared:
            return (f"{self.checkout.name}: no Python environment — "
                    + "; ".join(self.problems))
        parts = [
            f"{self.checkout.name}: {'reused' if self.reused else 'prepared'} a Python "
            f"environment in {self.duration_seconds:.2f}s",
            f"{len(self.source_roots)} first-party source root(s) from this checkout",
            f"{self.console_scripts} launcher(s)",
        ]
        if self.missing_requirements:
            parts.append(
                f"{len(self.missing_requirements)} declared requirement(s) are not "
                f"installed and cannot be: {', '.join(self.missing_requirements[:6])}"
            )
        return "; ".join(parts)

    def to_dict(self) -> dict:
        return {
            "checkout": str(self.checkout), "prepared": self.prepared,
            "reused": self.reused,
            "interpreter": str(self.interpreter) if self.interpreter else None,
            "source_roots": list(self.source_roots),
            "shared_site_packages": self.shared_site_packages,
            "console_scripts": self.console_scripts,
            "missing_requirements": list(self.missing_requirements),
            "problems": list(self.problems),
            "duration_seconds": round(self.duration_seconds, 3),
            "stamp": self.stamp,
        }


# ------------------------------------------------------------------ discovery
def source_roots(checkout: Path) -> list[Path]:
    """First-party source directories, discovered in the checkout being verified."""
    checkout = Path(checkout)
    found: list[Path] = []
    for pattern in SOURCE_GLOBS:
        found.extend(sorted(p for p in checkout.glob(pattern) if p.is_dir()))
    for relative in SOURCE_PATHS:
        candidate = checkout / relative
        if candidate.is_dir():
            found.append(candidate)
    # Stable order, no duplicates, and the order is what `sys.path` will hold.
    seen: set[str] = set()
    ordered: list[Path] = []
    for path in found:
        key = str(path.resolve())
        if key not in seen:
            seen.add(key)
            ordered.append(path)
    return ordered


def startup_hooks_in(roots: list[Path]) -> list[str]:
    """Startup hooks sitting in the source roots about to reach `sys.path`.

    Both shapes: `sitecustomize.py`, and a package directory named
    `sitecustomize`. Python imports the name, and a package satisfies it exactly
    as a module does.
    """
    found: list[str] = []
    for root in roots:
        for name in STARTUP_HOOKS:
            # Resolution, not a filename list: a package directory, sourceless
            # bytecode and a compiled extension all satisfy the import.
            for suffix in _IMPORTABLE_SUFFIXES:
                candidate = root / f"{name}{suffix}"
                if candidate.exists():
                    found.append(str(candidate))
            package = root / name
            if package.is_dir():
                found.append(str(package))
    return sorted(found)


def site_packages_of(interpreter: Path) -> Path | None:
    """Ask an interpreter where its site-packages is, rather than guessing."""
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv
            [str(interpreter), "-c", "import site;print(site.getsitepackages()[0])"],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip().splitlines()[-1])


def declared_requirements(checkout: Path) -> list[str]:
    """Third-party distribution names the checkout's packages declare.

    Read from `pyproject.toml` rather than inferred from imports: a dependency
    that was added in this checkout is a fact about the checkout, and the shared
    installation predates it.

    Only `project.dependencies` counts. An entry under
    `project.optional-dependencies` is an extra nobody is obliged to install --
    this package's own `jsonschema` extra is exactly that, with a documented
    fallback when it is absent -- and reporting every uninstalled extra as a
    missing requirement would bury the one case that matters: a *required*
    dependency this checkout added that the shared installation cannot provide.
    """
    import tomllib

    first_party: set[str] = set()
    names: dict[str, None] = {}
    files = sorted(checkout.glob("packages/*/pyproject.toml"))
    files += sorted(checkout.glob("services/*/pyproject.toml"))
    for relative in ("apps/api-gateway/pyproject.toml",
                     "tools/dev-orchestrator/pyproject.toml"):
        candidate = checkout / relative
        if candidate.is_file():
            files.append(candidate)

    parsed = []
    for path in files:
        try:
            document = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # Skipping it silently made a checkout with broken metadata look
            # like a checkout with no requirements, which is the one answer that
            # must never be produced by not knowing.
            raise ValueError(f"{path} could not be read: {exc}") from None
        parsed.append(document)
        name = (document.get("project") or {}).get("name")
        if name:
            first_party.add(_normalise(name))

    for document in parsed:
        project = document.get("project") or {}
        for entry in list(project.get("dependencies") or []):
            text = str(entry).strip()
            match = _REQUIREMENT_NAME.match(text)
            if match and _normalise(match.group(1)) in first_party:
                continue
            # An entry that does not begin with a name is kept, not dropped:
            # discarding it here meant a malformed dependency was silently not
            # a dependency. The parser downstream decides, and says so.
            names[text] = None
    return list(names)


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# --------------------------------------------------------------- preparation
def stamp_for(checkout: Path, shared: Path, interpreter_version: str,
              roots: list[Path], *, base: Path | None = None) -> str:
    """Everything a reused environment depends on, in one digest.

    The launcher inventory is included because launchers are *copied*: if the
    shared installation gains, loses or updates one while its path and Python
    version stay the same, a reused checkout would keep a stale copy -- or lack
    a new one -- and nothing else would notice.
    """
    return digest_json({
        "checkout": str(Path(checkout).resolve()),
        "shared_site_packages": str(shared),
        "python": interpreter_version,
        "base_interpreter": _interpreter_identity(base),
        "source_roots": sorted(str(p) for p in roots),
        "launchers": _launcher_manifest(base.parent if base else None),
        "layout": 4,
    })


def _interpreter_identity(base: Path | None) -> dict | None:
    """The interpreter an environment was built from, beyond its path."""
    if base is None:
        return None
    base = Path(base)
    try:
        stat_result = base.stat()
    except OSError:
        return {"path": str(base), "stat": None}
    return {
        "path": str(base.resolve()),
        "size": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
    }


def _launcher_manifest(bin_dir: Path | None) -> list[list]:
    """Name, size and modification time of every launcher that would be copied."""
    if bin_dir is None or not Path(bin_dir).is_dir():
        return []
    manifest = []
    for entry in sorted(Path(bin_dir).iterdir()):
        if entry.name in _SKIP_SCRIPTS or entry.name.startswith("python"):
            continue
        try:
            stat_result = entry.stat()
        except OSError:
            continue
        # Nanoseconds, not seconds: rewriting a launcher with same-sized
        # content inside one second left name, size and second unchanged, and
        # the checkout kept its stale copy.
        manifest.append([entry.name, stat_result.st_size, stat_result.st_mtime_ns,
                         stat_result.st_mode])
    return manifest


def prepare(checkout: Path, *, shared_venv: Path, timeout_seconds: float = 300.0,
            reuse: bool = True) -> EnvironmentReport:
    """Give `checkout` an interpreter that imports `checkout`'s own code.

    Returns a report in every case. Preparation that could not finish is a
    reported condition, never an exception and never a silent partial
    environment: a caller that sees `prepared=False` must not record a pass.
    """
    started = time.monotonic()
    checkout = Path(checkout).resolve()
    shared_venv = Path(shared_venv).resolve()
    problems: list[str] = []

    base = shared_venv / "bin" / "python"
    if not base.exists():
        return EnvironmentReport(
            checkout=checkout, prepared=False,
            problems=(f"no interpreter at {base}; the repository's own environment has "
                      f"not been created, so no checkout can be given one",),
            duration_seconds=time.monotonic() - started,
        )

    shared_site = site_packages_of(base)
    if shared_site is None or not shared_site.is_dir():
        return EnvironmentReport(
            checkout=checkout, prepared=False,
            problems=(f"{base} did not report a usable site-packages directory",),
            duration_seconds=time.monotonic() - started,
        )

    roots = source_roots(checkout)
    hooks = startup_hooks_in(roots)
    if hooks:
        return EnvironmentReport(
            checkout=checkout, prepared=False,
            problems=tuple(
                f"{hook} would be imported automatically by every interpreter started "
                f"here, before any check runs and outside any sandbox. A checkout "
                f"carrying one cannot be verified." for hook in hooks),
            duration_seconds=time.monotonic() - started,
        )
    if not roots:
        return EnvironmentReport(
            checkout=checkout, prepared=False,
            problems=(f"{checkout} contains none of {SOURCE_GLOBS + SOURCE_PATHS}; it "
                      f"does not look like this repository",),
            duration_seconds=time.monotonic() - started,
        )

    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    try:
        probe = subprocess.run(  # noqa: S603 - fixed argv
            [str(base), "-c",
             "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if probe.returncode == 0 and probe.stdout.strip():
            version = probe.stdout.strip().splitlines()[-1]
    except (OSError, subprocess.SubprocessError) as exc:
        return EnvironmentReport(
            checkout=checkout, prepared=False,
            problems=(f"could not run {base}: {exc}",),
            duration_seconds=time.monotonic() - started,
        )

    target = checkout / ".venv"
    stamp = stamp_for(checkout, shared_site, version, roots, base=base)
    interpreter = target / "bin" / "python"

    if reuse and _stamp_matches(target, stamp) and interpreter.exists():
        report = EnvironmentReport(
            checkout=checkout, prepared=True, reused=True, interpreter=interpreter,
            source_roots=tuple(str(p) for p in roots),
            shared_site_packages=str(shared_site),
            console_scripts=_count_scripts(target),
            stamp=stamp, duration_seconds=time.monotonic() - started,
        )
        report.missing_requirements = tuple(
            _missing(checkout, shared_site, interpreter))
        return report

    # A stamp that does not match means the environment describes a different
    # tree. Removing it is the point: reusing it would be the silent staleness
    # this module exists to prevent.
    if target.exists():
        _remove(target, problems)

    try:
        subprocess.run(  # noqa: S603 - fixed argv
            [str(base), "-m", "venv", "--without-pip", str(target)],
            capture_output=True, text=True, timeout=timeout_seconds, check=True,
        )
    except subprocess.TimeoutExpired:
        return EnvironmentReport(
            checkout=checkout, prepared=False,
            problems=(f"creating a virtualenv in {checkout.name} exceeded "
                      f"{timeout_seconds:.0f}s",),
            duration_seconds=time.monotonic() - started,
        )
    except (OSError, subprocess.SubprocessError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        return EnvironmentReport(
            checkout=checkout, prepared=False,
            problems=(f"could not create a virtualenv in {checkout.name}: "
                      f"{str(detail).strip()[:300]}",),
            duration_seconds=time.monotonic() - started,
        )

    site_dir = target / "lib" / f"python{version}" / "site-packages"
    if not site_dir.is_dir():
        found = sorted((target / "lib").glob("python*/site-packages"))
        if not found:
            return EnvironmentReport(
                checkout=checkout, prepared=False,
                problems=(f"the new virtualenv in {checkout.name} has no site-packages",),
                duration_seconds=time.monotonic() - started,
            )
        site_dir = found[0]

    lines = [str(root) for root in roots] + [str(shared_site)]
    (site_dir / PTH_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")

    scripts = _install_launchers(shared_venv, target, problems)
    (target / STAMP_NAME).write_text(
        json.dumps({"stamp": stamp, "checkout": str(checkout),
                    "shared_site_packages": str(shared_site), "python": version,
                    "source_roots": [str(p) for p in roots]}, indent=2),
        encoding="utf-8")

    report = EnvironmentReport(
        checkout=checkout, prepared=True, reused=False, interpreter=interpreter,
        source_roots=tuple(str(p) for p in roots),
        shared_site_packages=str(shared_site), console_scripts=scripts,
        problems=tuple(problems), stamp=stamp,
        duration_seconds=time.monotonic() - started,
    )
    report.missing_requirements = tuple(_missing(checkout, shared_site, interpreter))
    return report


def _stamp_matches(target: Path, stamp: str) -> bool:
    try:
        recorded = json.loads((target / STAMP_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return recorded.get("stamp") == stamp


def _count_scripts(target: Path) -> int:
    bin_dir = target / "bin"
    if not bin_dir.is_dir():
        return 0
    return sum(1 for entry in bin_dir.iterdir() if entry.name not in _SKIP_SCRIPTS)


def _remove(target: Path, problems: list[str]) -> None:
    import shutil

    try:
        shutil.rmtree(target)
    except OSError as exc:
        problems.append(f"could not remove the stale environment at {target}: {exc}")


def _install_launchers(shared_venv: Path, target: Path, problems: list[str]) -> int:
    """Reproduce `bin/` launchers so `source .venv/bin/activate; pytest` works.

    `scripts/test.sh` and `scripts/verify-release.sh` activate the environment
    and then call `pytest` and `ruff` by name, so a virtualenv with only an
    interpreter cannot run the repository's own gate.

    A console script generated by pip embeds the absolute interpreter path --
    twice, when the path contains a space, because pip then writes a `/bin/sh`
    preamble that re-execs. Rewriting every occurrence of the old environment's
    directory covers both shapes. A compiled launcher such as `ruff` has no
    interpreter to rewrite and is symlinked: it is an executable this
    environment borrows, not code whose imports matter.
    """
    source_bin = shared_venv / "bin"
    target_bin = target / "bin"
    if not source_bin.is_dir() or not target_bin.is_dir():
        problems.append("no bin directory to reproduce launchers from")
        return 0

    old, new = str(shared_venv), str(target)
    installed = 0
    for entry in sorted(source_bin.iterdir()):
        if entry.name in _SKIP_SCRIPTS or entry.name.startswith("python"):
            continue
        if not entry.is_file():
            continue
        destination = target_bin / entry.name
        if destination.exists():
            continue
        try:
            text = entry.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            # A compiled executable. Borrow it; nothing in it resolves imports.
            try:
                destination.symlink_to(entry)
                installed += 1
            except OSError as exc:
                problems.append(f"could not link {entry.name}: {exc}")
            continue
        if not text.startswith("#!"):
            continue
        try:
            destination.write_text(text.replace(old, new), encoding="utf-8")
            destination.chmod(destination.stat().st_mode | stat.S_IEXEC
                              | stat.S_IXGRP | stat.S_IXOTH)
            installed += 1
        except OSError as exc:
            problems.append(f"could not write launcher {entry.name}: {exc}")
    return installed


def _missing(checkout: Path, shared_site: Path, interpreter: Path) -> list[str]:
    """Applicable declared requirements the shared installation does not satisfy.

    Asked of the environment that will actually run the checks, through
    `importlib.metadata`, so a *version* that does not match counts as
    unsatisfied -- `pydantic>=999` is not satisfied by the pydantic that is
    installed. Environment markers are evaluated, so a requirement that does not
    apply here is not reported. Metadata that cannot be parsed is reported as a
    problem rather than silently yielding "nothing missing".
    """
    try:
        required = declared_requirements(checkout)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return [f"(could not read dependency declarations: {exc!r})"]
    if not required:
        return []

    probe = (
        "import json,sys\n"
        "from importlib.metadata import version, PackageNotFoundError\n"
        "try:\n"
        "    from packaging.requirements import Requirement\n"
        "    from packaging.utils import canonicalize_name\n"
        "except Exception as exc:\n"
        "    print(json.dumps({'error': repr(exc)})); raise SystemExit(0)\n"
        "missing = []\n"
        "from importlib.metadata import metadata\n"
        "def check(raw, seen):\n"
        "    try:\n"
        "        req = Requirement(raw)\n"
        "    except Exception as exc:\n"
        "        return [raw + ' (not a usable requirement: ' + str(exc)[:80] + ')']\n"
        "    if req.marker is not None and not req.marker.evaluate():\n"
        "        return []\n"
        "    if req.url:\n"
        "        return [raw + ' (direct reference; this checker cannot verify it)']\n"
        "    name = canonicalize_name(req.name)\n"
        "    try:\n"
        "        have = version(name)\n"
        "    except PackageNotFoundError:\n"
        "        return [req.name + ' (not installed)']\n"
        "    if req.specifier and not req.specifier.contains(have, prereleases=True):\n"
        "        return [f'{req.name} {req.specifier} (installed {have})']\n"
        "    out = []\n"
        "    for extra in sorted(req.extras):\n"
        "        key = (name, extra)\n"
        "        if key in seen:\n"
        "            continue\n"
        "        seen.add(key)\n"
        "        try:\n"
        "            declared = metadata(name).get_all('Requires-Dist') or []\n"
        "        except Exception:\n"
        "            out.append(f'{req.name}[{extra}] (metadata unreadable)'); continue\n"
        "        provides = [e.strip().lower() for e in\n"
        "                    (metadata(name).get_all('Provides-Extra') or [])]\n"
        "        if extra.lower() not in provides:\n"
        "            out.append(f'{req.name}[{extra}] (no such extra)'); continue\n"
        "        for line in declared:\n"
        "            try:\n"
        "                sub = Requirement(line)\n"
        "            except Exception:\n"
        "                continue\n"
        "            marker = str(sub.marker or '')\n"
        "            if f\"extra == '{extra}'\" not in marker and \\\n"
        "                    f'extra == \"{extra}\"' not in marker:\n"
        "                continue\n"
        "            bare = line.split(';')[0].strip()\n"
        "            out.extend(f'{req.name}[{extra}] -> ' + m\n"
        "                       for m in check(bare, seen))\n"
        "    return out\n"
        "seen = set()\n"
        "for raw in json.loads(sys.argv[1]):\n"
        "    missing.extend(check(raw, seen))\n"
        "print(json.dumps({'missing': missing}))\n"
    )
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv
            [str(interpreter), "-c", probe, json.dumps(required)],
            capture_output=True, text=True, timeout=180, check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                 "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [f"(could not check requirements: {exc})"]
    if result.returncode != 0:
        return [f"(requirement check failed: {result.stderr.strip()[:200]})"]
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return ["(requirement check produced no usable answer)"]
    if payload.get("error"):
        return [f"(requirement check needs packaging: {payload['error']})"]
    return list(payload.get("missing", []))


# ------------------------------------------------------------- verification
def module_origins(interpreter: Path, modules: tuple[str, ...],
                   *, cwd: Path | None = None) -> dict[str, str | None]:
    """Where an interpreter resolves each module from. `None` means unimportable."""
    probe = (
        "import json, importlib.util as u;"
        f"print(json.dumps({{m: (u.find_spec(m).origin if u.find_spec(m) else None) "
        f"for m in {list(modules)!r}}}))"
    )
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv
            [str(interpreter), "-c", probe], cwd=str(cwd) if cwd else None,
            capture_output=True, text=True, timeout=120, check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                 "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except (OSError, subprocess.SubprocessError):
        return dict.fromkeys(modules, None)
    if result.returncode != 0:
        return dict.fromkeys(modules, None)
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return dict.fromkeys(modules, None)


def assert_module_origins(checkout: Path, modules: tuple[str, ...]) -> list[str]:
    """Complaints about modules this checkout does not own.

    The construction is designed so this passes; it is checked anyway, every
    run, because "the design makes it impossible" is not evidence and a future
    change to the shared installation could silently reintroduce the fault.
    """
    checkout = Path(checkout).resolve()
    interpreter = checkout / ".venv" / "bin" / "python"
    if not interpreter.exists():
        return [f"{checkout} has no interpreter at .venv/bin/python, so nothing can be "
                f"verified here"]
    problems: list[str] = []
    root = str(checkout)
    for module, origin in sorted(module_origins(interpreter, modules,
                                                cwd=checkout).items()):
        if not origin:
            problems.append(f"{module} is not importable in {checkout.name}")
            continue
        try:
            resolved = str(Path(origin).resolve())
        except OSError:
            problems.append(f"{module} resolves to an unreadable path {origin}")
            continue
        if not resolved.startswith(root + os.sep):
            problems.append(
                f"{module} resolves to {origin}, outside {checkout.name}. Checks run "
                f"here would describe a different tree.")
    return problems
