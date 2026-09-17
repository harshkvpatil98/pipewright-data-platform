"""Filesystem isolation: path scopes, an enforced write boundary, worktrees, patches."""

from .guard import PathGuard, PathViolation
from .patches import PatchBundle, apply_bundle, export_bundle
from .sandbox import SandboxSupport, detect_sandbox_support, sandbox_wrapper
from .worktrees import WorktreeManager

__all__ = [
    "PathGuard", "PathViolation", "PatchBundle", "apply_bundle", "export_bundle",
    "SandboxSupport", "detect_sandbox_support", "sandbox_wrapper", "WorktreeManager",
]
