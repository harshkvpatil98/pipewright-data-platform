"""Configuration and the adopted run policy.

A run *freezes* its configuration at start: the frozen copy is stored as an
artifact and every later decision reads that, not the file on disk. Editing the
controller's configuration mid-run must not widen the permissions or relax the
completion gates of a run already in flight.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from .errors import ConfigError

CONFIG_FILENAME = "pw-dev.toml"
STATE_DIRNAME = ".pw-dev"


@dataclass(frozen=True)
class ProviderConfig:
    """One provider CLI as this controller drives it."""

    executable: str
    model: str | None
    # `None` means "whatever the CLI resolves by default"; the resolved value is
    # recorded in the run's provider snapshot so it is never merely implied.
    reasoning_effort: str | None = None
    extra_args: tuple[str, ...] = ()
    startup_timeout_seconds: int = 120


@dataclass(frozen=True)
class Limits:
    """Conservative by default. Every one of these pauses a run, never completes it."""

    max_parallel_workers: int = 3
    per_task_seconds: int = 1800
    total_run_seconds: int = 14400
    provider_retries: int = 2
    repair_rounds_per_task: int = 3
    max_output_bytes: int = 8 * 1024 * 1024
    plan_seconds: int = 2400
    review_seconds: int = 2400
    verification_seconds: int = 3600
    max_context_file_bytes: int = 120_000
    max_context_files: int = 40


@dataclass(frozen=True)
class IsolationConfig:
    """How worker processes are confined.

    `mode` is one of:

    * `enforced`  -- the host can restrict writes (macOS `sandbox-exec`), so an
      unattended run is allowed;
    * `supervised` -- no enforceable boundary; writes are detected after the
      fact, and an unattended run is refused;
    * `off` -- explicitly disabled, for a throwaway container that is already
      the boundary.

    A git worktree is *not* one of these. Worktrees stop two workers from
    editing the same file; they share `.git` and enforce nothing.
    """

    mode: str = "auto"
    unattended: bool = False
    allow_supervised_unattended: bool = False


@dataclass(frozen=True)
class PublicationPolicy:
    """Captured once per run. Pushing is not merging, and neither is deploying."""

    mode: str = "none"                      # none | local_commit | feature_branch
    remote: str = "origin"
    branch_prefix: str = "pw-dev"
    allow_existing_branch: str | None = None
    protected_branches: tuple[str, ...] = ("main", "master")
    author_name: str = "harshkvpatil98"
    author_email: str = "harshkvpatil@gmail.com"
    create_pull_request: bool = False
    wait_for_ci: bool = False


@dataclass(frozen=True)
class Config:
    """The whole adopted configuration for a run."""

    repo_root: Path
    state_dir: Path
    planner: ProviderConfig
    implementer: ProviderConfig
    reviewer: ProviderConfig
    limits: Limits = field(default_factory=Limits)
    isolation: IsolationConfig = field(default_factory=IsolationConfig)
    publication: PublicationPolicy = field(default_factory=PublicationPolicy)
    verification_profile: str = "pipewright"

    # ----------------------------------------------------------------- loading
    @staticmethod
    def default_paths(repo_root: Path) -> tuple[Path, Path]:
        return repo_root / "tools" / "dev-orchestrator" / CONFIG_FILENAME, repo_root / STATE_DIRNAME

    @classmethod
    def load(cls, repo_root: Path, *, overrides: dict[str, Any] | None = None) -> "Config":
        repo_root = Path(repo_root).resolve()
        config_path, state_dir = cls.default_paths(repo_root)
        raw: dict[str, Any] = {}
        if config_path.is_file():
            try:
                raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError as exc:
                raise ConfigError(f"{config_path} is not valid TOML: {exc}") from exc

        providers = raw.get("providers", {})
        config = cls(
            repo_root=repo_root,
            state_dir=Path(raw.get("state_dir", state_dir)),
            planner=_provider(providers.get("planner"), "codex", None),
            implementer=_provider(providers.get("implementer"), "claude", None),
            reviewer=_provider(providers.get("reviewer"), "codex", None),
            limits=_dataclass_from(Limits, raw.get("limits", {})),
            isolation=_dataclass_from(IsolationConfig, raw.get("isolation", {})),
            publication=_dataclass_from(PublicationPolicy, raw.get("publication", {})),
            verification_profile=raw.get("verification_profile", "pipewright"),
        )
        if overrides:
            config = config.with_overrides(overrides)
        config.validate()
        return config

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "Config":
        """Rebuild the configuration a run was started with.

        A resumed run reads this, not the file on disk. Editing `pw-dev.toml`
        while a run is paused must not widen that run's permissions or relax the
        gates it will be judged against.
        """
        def provider(raw: dict[str, Any]) -> ProviderConfig:
            return ProviderConfig(
                executable=raw["executable"], model=raw.get("model"),
                reasoning_effort=raw.get("reasoning_effort"),
                extra_args=tuple(raw.get("extra_args") or ()),
                startup_timeout_seconds=int(raw.get("startup_timeout_seconds", 120)),
            )

        publication = dict(snapshot["publication"])
        publication["protected_branches"] = tuple(publication.get("protected_branches") or ())
        return cls(
            repo_root=Path(snapshot["repo_root"]),
            state_dir=Path(snapshot["state_dir"]),
            planner=provider(snapshot["planner"]),
            implementer=provider(snapshot["implementer"]),
            reviewer=provider(snapshot["reviewer"]),
            limits=Limits(**snapshot["limits"]),
            isolation=IsolationConfig(**snapshot["isolation"]),
            publication=PublicationPolicy(**publication),
            verification_profile=snapshot.get("verification_profile", "pipewright"),
        )

    def with_overrides(self, overrides: dict[str, Any]) -> "Config":
        """Apply CLI overrides. Only the fields a command is allowed to set."""
        config = self
        publication = overrides.get("publication")
        if publication:
            config = replace(config, publication=replace(config.publication, **publication))
        limits = overrides.get("limits")
        if limits:
            config = replace(config, limits=replace(config.limits, **limits))
        isolation = overrides.get("isolation")
        if isolation:
            config = replace(config, isolation=replace(config.isolation, **isolation))
        for role in ("planner", "implementer", "reviewer"):
            patch = overrides.get(role)
            if patch:
                config = replace(config, **{role: replace(getattr(config, role), **patch)})
        return config

    def validate(self) -> None:
        if self.limits.max_parallel_workers < 1:
            raise ConfigError("limits.max_parallel_workers must be at least 1")
        if self.limits.max_parallel_workers > 8:
            raise ConfigError(
                "limits.max_parallel_workers above 8 is refused: concurrent workers "
                "contend for the same build caches and databases, and the gain stops "
                "before the contention does"
            )
        if self.publication.mode not in ("none", "local_commit", "feature_branch"):
            raise ConfigError(f"unknown publication mode {self.publication.mode!r}")
        if self.isolation.mode not in ("auto", "enforced", "supervised", "off"):
            raise ConfigError(f"unknown isolation mode {self.isolation.mode!r}")
        if self.publication.allow_existing_branch in self.publication.protected_branches:
            raise ConfigError(
                f"publication.allow_existing_branch may not be a protected branch "
                f"({self.publication.allow_existing_branch!r})"
            )
        if not self.publication.author_email or "@" not in self.publication.author_email:
            raise ConfigError("publication.author_email must be a real address")

    # ---------------------------------------------------------------- snapshot
    def snapshot(self) -> dict[str, Any]:
        """The frozen form stored with a run and digested into evidence."""
        document = asdict(self)
        document["repo_root"] = str(self.repo_root)
        document["state_dir"] = str(self.state_dir)
        for key in ("planner", "implementer", "reviewer"):
            document[key]["extra_args"] = list(getattr(self, key).extra_args)
        document["publication"]["protected_branches"] = list(self.publication.protected_branches)
        return document

    def runs_dir(self) -> Path:
        return self.state_dir / "runs"

    def db_path(self) -> Path:
        return self.state_dir / "state.sqlite3"


def _provider(raw: dict[str, Any] | None, default_exe: str, default_model: str | None) -> ProviderConfig:
    raw = dict(raw or {})
    extra = tuple(raw.pop("extra_args", ()) or ())
    return ProviderConfig(
        executable=raw.pop("executable", default_exe),
        model=raw.pop("model", default_model),
        reasoning_effort=raw.pop("reasoning_effort", None),
        extra_args=extra,
        startup_timeout_seconds=int(raw.pop("startup_timeout_seconds", 120)),
    )


def _dataclass_from(cls, raw: dict[str, Any]):
    known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"unknown {cls.__name__} keys: {sorted(unknown)}")
    coerced = dict(raw)
    for key, value in list(coerced.items()):
        if isinstance(value, list):
            coerced[key] = tuple(value)
    return cls(**coerced)


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up to the nearest Git repository root."""
    current = Path(start or os.getcwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    raise ConfigError(f"{current} is not inside a Git repository")
