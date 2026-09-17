"""Generic role prompts, loaded from disk so they can be reviewed as text."""

from __future__ import annotations

import functools
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent

ROLES = ("shared_rules", "planner", "worker", "verifier", "reviewer", "repair")


@functools.lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    if name not in ROLES:
        raise KeyError(f"unknown role prompt {name!r}; known: {list(ROLES)}")
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def role_prompt(name: str) -> str:
    """A role prompt with the shared rules prepended."""
    if name == "shared_rules":
        return load_prompt(name)
    return f"{load_prompt('shared_rules')}\n\n---\n\n{load_prompt(name)}"
