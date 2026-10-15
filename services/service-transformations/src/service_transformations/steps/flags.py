"""Settings every step can carry besides its own: turned off, a note and a group (E1).

They live in the step's settings, prefixed with an underscore, so the
shared copy merges them like any other setting, recipe-as-code writes them,
and bundles and promotion carry them, with nothing new to keep in step. They
are taken out before a step runs, is checked or is described: a step that is
turned off passes its input through unchanged, and its kept result is the one
before it.
"""

from __future__ import annotations

from typing import Any

#: False turns the step off; absent or True leaves it on.
ENABLED = "_enabled"
#: A note shown on the step and kept with the recipe; it changes nothing.
NOTE = "_note"
#: The named group a step is in: steps next to each other with one name show,
#: turn off and save as a template together (a macro). It changes nothing.
GROUP = "_group"
FLAGS = (ENABLED, NOTE, GROUP)
#: The flags that never change what a step makes.
REMARKS = (NOTE, GROUP)


def is_enabled(config: dict[str, Any] | None) -> bool:
    return (config or {}).get(ENABLED, True) is not False


def without_flags(config: dict[str, Any] | None) -> dict[str, Any]:
    return {key: value for key, value in (config or {}).items() if key not in FLAGS}


def step_enabled(step: Any) -> bool:
    """For a TransformationStep or a step dict."""
    config = step.get("config") if isinstance(step, dict) else getattr(step, "config", None)
    return is_enabled(config)
