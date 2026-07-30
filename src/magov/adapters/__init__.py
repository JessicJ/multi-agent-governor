"""Agent runtime adapters shipped with Multi-Agent Governor."""

from .codex_cli import CodexCliRuntime, CodexCliRuntimeConfig
from .fake import ScriptedRuntime

__all__ = [
    "CodexCliRuntime",
    "CodexCliRuntimeConfig",
    "ScriptedRuntime",
]
