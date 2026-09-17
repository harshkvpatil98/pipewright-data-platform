"""Fixtures: a disposable repository, a local bare remote, and a store.

The helpers these build on live in `pw_dev.testing` rather than here. The
repository's pytest bundle runs from the repository root with
`--import-mode=importlib`, under which `from conftest import ...` fails at
collection -- and one collection error interrupts the whole bundle, not just
these files.

Every test runs against a throwaway repository under `tmp_path`. Nothing touches
the real checkout, the operator's Git configuration, or a network remote: the
publication tests push to a bare repository on disk, which is a real push with a
real ref to read back.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pw_dev.config import Config, IsolationConfig, Limits, ProviderConfig, PublicationPolicy
from pw_dev.state.db import RunStore
from pw_dev.testing import run_git


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """A small repository that looks enough like Pipewright to plan against."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-q", "-b", "main")
    run_git(repo, "config", "user.name", "fixture")
    run_git(repo, "config", "user.email", "fixture@example.invalid")
    run_git(repo, "config", "commit.gpgsign", "false")

    (repo / "docs").mkdir()
    (repo / "docs" / "HANDOFF.md").write_text(
        "# HANDOFF\n\n"
        "## 8. Progress ledger\n\n"
        "| # | Phase | Status | Sessions | Notes |\n"
        "|---|---|---|---|---|\n"
        "| 08 | Types | **done** | 2/2 | Cutover deferred |\n"
        "| 16 | Tools | **partial** | 3/6 | 167 tools |\n"
        "| 18 | Time travel | not started | 0/3 | Needs 08 |\n\n"
        "### Recommended next action\n\n"
        "Tracks A, B and C are complete: 18 (time travel) is the\n"
        "natural next one and unlocks 19 and 22.\n\n"
        "Cutting over to IR-only is a deliberate separate decision, not an oversight.\n",
        encoding="utf-8",
    )
    (repo / "docs" / "roadmap-v2.md").write_text(
        "# Roadmap v2\n\n"
        "> **Status:** proposed, not started.\n\n"
        "## Phase 08 — Types ✅ COMPLETE\n\ntext\n\n"
        "## Phase 16 — Tools ⚠ PARTIAL\n\n173 tools exist.\n\n"
        "## Phase 18 — Time travel\n\nImmutable snapshots.\n",
        encoding="utf-8",
    )
    (repo / "src").mkdir()
    (repo / "src" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "src" / "other.py").write_text("OTHER = 2\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "__init__.py").write_text("", encoding="utf-8")
    # stdlib unittest, so the fixture profile's gate runs on any Python without
    # needing pytest installed in the throwaway repository.
    (repo / "tests" / "test_app.py").write_text(
        "import unittest\n\nfrom src.app import VALUE\n\n\n"
        "class ValueTest(unittest.TestCase):\n"
        "    def test_value(self):\n"
        "        self.assertEqual(VALUE, 1)\n",
        encoding="utf-8",
    )
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "initial")
    return repo


@pytest.fixture
def bare_remote(tmp_path: Path, fixture_repo: Path) -> Path:
    """A real Git remote on disk, so a push can be pushed and read back."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)],  # noqa: S603
                   check=True, capture_output=True)
    run_git(fixture_repo, "remote", "add", "origin", str(remote))
    run_git(fixture_repo, "push", "-q", "origin", "main")
    return remote


@pytest.fixture
def config(fixture_repo: Path, tmp_path: Path) -> Config:
    return Config(
        repo_root=fixture_repo,
        state_dir=tmp_path / "state",
        planner=ProviderConfig(executable="codex", model="test-planner"),
        implementer=ProviderConfig(executable="claude", model="test-implementer"),
        reviewer=ProviderConfig(executable="codex", model="test-reviewer"),
        limits=Limits(max_parallel_workers=2, per_task_seconds=30, total_run_seconds=300,
                      provider_retries=1, repair_rounds_per_task=2),
        isolation=IsolationConfig(mode="supervised"),
        publication=PublicationPolicy(
            mode="none", remote="origin", branch_prefix="pw-dev",
            author_name="harshkvpatil98", author_email="harshkvpatil@gmail.com",
        ),
    )


@pytest.fixture
def store(config: Config) -> RunStore:
    with RunStore(config.db_path(), config.runs_dir()) as handle:
        yield handle
