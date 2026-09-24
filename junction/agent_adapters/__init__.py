"""
junction/agent_adapters/__init__.py

Registry of agent adapters. Import get_adapter() to retrieve the right adapter
for a given agent name string.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from junction.agent_adapters._base import AgentAdapter

ADAPTER_NAMES = ["copilot", "cursor", "claude-code", "continue", "agnostic"]


def get_adapter(agent: str) -> "AgentAdapter":
    """Return the adapter instance for the given agent name."""
    agent = agent.lower()
    if agent == "copilot":
        from junction.agent_adapters.copilot import CopilotAdapter
        return CopilotAdapter()
    if agent == "cursor":
        from junction.agent_adapters.cursor import CursorAdapter
        return CursorAdapter()
    if agent in ("claude-code", "claude_code"):
        from junction.agent_adapters.claude_code import ClaudeCodeAdapter
        return ClaudeCodeAdapter()
    if agent in ("continue", "continue_dev"):
        from junction.agent_adapters.continue_dev import ContinueDevAdapter
        return ContinueDevAdapter()
    if agent == "agnostic":
        from junction.agent_adapters._base import AgnosticAdapter
        return AgnosticAdapter()
    raise ValueError(
        f"Unknown agent: {agent!r}. Valid choices: {', '.join(ADAPTER_NAMES)}"
    )
