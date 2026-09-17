"""Provider adapters.

The interface is deliberately narrow -- one method, `invoke`, returning one
`ProviderResult` -- so an SDK-backed adapter can be added later without the
controller learning anything new. There is no generic multi-provider framework
here and no second HTTP backend: two CLI adapters, one shape.
"""

from .base import FailureKind, ProviderAdapter, ProviderResult, Usage
from .claude_cli import ClaudeCliAdapter
from .codex_cli import CodexCliAdapter

__all__ = [
    "FailureKind", "ProviderAdapter", "ProviderResult", "Usage",
    "ClaudeCliAdapter", "CodexCliAdapter",
]
