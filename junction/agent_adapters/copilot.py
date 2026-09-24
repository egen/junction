"""
copilot.py — Adapter for GitHub Copilot (VS Code custom agents).

Generates one custom agent per graph node:
  .github/agents/{orchestrator,iac-validator,terraform-builder,
                  sre-observer,knowledge-curator,migration-executor}.agent.md

Graph edges become Copilot ``handoffs`` buttons, and the orchestrator is the
only agent allowed to invoke the others as subagents.
"""

from __future__ import annotations

import json
from typing import Optional

from junction.agent_adapters._base import AgentAdapter
from junction.agent_specs import MCP_TOOL_TO_SERVER, AgentSpec, agent_title
from junction.config_builder import PlatformConfig

# Graph tool names → Copilot tool sets
_TOOL_MAP = {
    "read": "read",
    "get-errors": "read",
    "search": "search",
    "grep": "search",
    "edit": "edit",
    "terminal": "execute",
    "runSubagent": "agent",
}


class CopilotAdapter(AgentAdapter):
    name = "copilot"

    def generate_files(self, platform: PlatformConfig, graph: Optional[dict] = None) -> dict[str, str]:
        agents = self.agents(platform, graph)
        names = [spec.name for spec, _ in agents]
        return {
            f".github/agents/{spec.name}.agent.md": _agent_file(spec, body, names)
            for spec, body in agents
        }


def copilot_tools(spec: AgentSpec) -> list[str]:
    tools: list[str] = []
    for tool in spec.tools:
        if tool.startswith("mcp:"):
            mapped = f"{MCP_TOOL_TO_SERVER.get(tool, tool[4:])}/*"
        else:
            mapped = _TOOL_MAP.get(tool)
        if mapped and mapped not in tools:
            tools.append(mapped)
    if "todo" not in tools and spec.name in ("orchestrator", "migration-executor"):
        tools.append("todo")
    return tools


def _agent_file(spec: AgentSpec, body: str, all_names: list[str]) -> str:
    lines = [
        "---",
        f"name: {spec.name}",
        f"description: {json.dumps(spec.description, ensure_ascii=False)}",
        f"tools: {json.dumps(copilot_tools(spec), ensure_ascii=False)}",
    ]
    if spec.name == "orchestrator":
        lines.append(f"agents: {json.dumps([n for n in all_names if n != 'orchestrator'], ensure_ascii=False)}")
    else:
        lines.append("agents: []")
    handoffs = [e for e in spec.outbound if e["to"] != spec.name]
    if handoffs:
        lines.append("handoffs:")
        for edge in handoffs:
            target = edge["to"]
            label = f"Send to {agent_title(target)}"
            prompt = f"Handoff from {spec.name} on '{edge['trigger']}'. Continue with the context above."
            lines += [
                f"  - label: {json.dumps(label, ensure_ascii=False)}",
                f"    agent: {target}",
                f"    prompt: {json.dumps(prompt, ensure_ascii=False)}",
                "    send: false",
            ]
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body
