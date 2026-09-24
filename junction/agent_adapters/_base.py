"""
_base.py — Abstract base class for agent adapters + AgnosticAdapter.

An adapter's job is to translate PlatformConfig into IDE-native configuration
files. Every adapter must implement generate_files() which returns a dict of
{target-relative-path: content}.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from typing import Optional

from junction.agent_specs import AgentSpec, build_agent_specs, render_agent_body
from junction.config_builder import PlatformConfig


def resolve_graph(platform: PlatformConfig, graph: Optional[dict]) -> dict:
    """Use the given agent graph, or generate the default one for this platform."""
    if graph is not None:
        return graph
    from junction.graph_generator import answers_from_platform, generate_agent_graph
    return generate_agent_graph(answers_from_platform(platform))


class AgentAdapter(ABC):
    """Base class for all agent adapters."""

    name: str = "base"

    @abstractmethod
    def generate_files(self, platform: PlatformConfig, graph: Optional[dict] = None) -> dict[str, str]:
        """
        Return a dict mapping target-relative path → file content.
        These files are in addition to the agent-agnostic scaffold files.
        ``graph`` is the agent graph; the default graph is generated when omitted.
        """

    def agents(self, platform: PlatformConfig, graph: Optional[dict] = None) -> list[tuple[AgentSpec, str]]:
        """The six graph agents with their rendered markdown bodies."""
        graph = resolve_graph(platform, graph)
        return [(spec, render_agent_body(spec, platform, graph)) for spec in build_agent_specs(graph)]

    def write(self, platform: PlatformConfig, target_dir: Path, overwrite: bool = False) -> list[str]:
        """Write adapter files into target_dir and return list of written paths."""
        from junction.scaffold import write_files
        files = self.generate_files(platform)
        return write_files(files, target_dir, overwrite=overwrite)


class AgnosticAdapter(AgentAdapter):
    """
    Agnostic adapter — copies only markdown skill/instruction files, no IDE config.
    This is the minimal option for teams that don't use any of the supported IDEs.
    """

    name = "agnostic"

    def generate_files(self, platform: PlatformConfig, graph: Optional[dict] = None) -> dict[str, str]:
        # AGENTS.md at the repo root plus one markdown brief per graph agent.
        agents = self.agents(platform, graph)
        files = {"AGENTS.md": _agents_md(platform, [spec for spec, _ in agents])}
        for spec, body in agents:
            files[f".agents/{spec.name}.md"] = (
                f"---\nname: {spec.name}\ndescription: {json.dumps(spec.description, ensure_ascii=False)}\n"
                f"model: {spec.model}\nrisk_gate: {spec.risk_gate}\n---\n\n{body}"
            )
        return files


# ─── Shared content helpers ───────────────────────────────────────────────────


def agent_table(specs: list[AgentSpec], path: str) -> str:
    """Markdown table of the six agents; ``path`` is a format string taking ``name``."""
    rows = "\n".join(
        f"| **{s.title}** | `{path.format(name=s.name)}` | {s.role} | `{s.risk_gate}` | `{s.tier}` |"
        for s in specs
    )
    return "| Agent | File | Role | Risk gate | Model tier |\n|---|---|---|---|---|\n" + rows


def _agents_md(platform: PlatformConfig, specs: list[AgentSpec]) -> str:
    env_rows = "\n".join(
        f"| {e.name} | `{e.branch}` | `{e.account_id}` | `{e.prefix}` |"
        for e in platform.environments
    )
    return f"""# AI Agent Platform — {platform.name}

> Scaffolded by [junction](https://github.com/egen/junction)

This repository is configured with Junction.
The skills and instructions in `.github/` work with any AI coding assistant that
can read files from your repository.

## Environments

| Env | Branch | Account | Prefix |
|-----|--------|---------|--------|
{env_rows}

## Agent Graph

Work is split across six specialist agents defined in `.github/config/agent-graph.yml`.
Start every task with the **Orchestrator**: it runs the boot protocol and routes to the others.

{agent_table(specs, ".agents/{name}.md")}

## Available Skills

| Skill | Location | Description |
|-------|----------|-------------|
| env-promotion | `.github/skills/_core/env-promotion/SKILL.md` | Promote changes across environments |
| self-healing-deploy | `.github/skills/_core/self-healing-deploy/SKILL.md` | Full deploy lifecycle with auto-remediation |
| drift-detection | `.github/skills/_core/drift-detection/SKILL.md` | Detect env config drift |
| post-push-monitor | `.github/skills/_core/post-push-monitor/SKILL.md` | CI/CD closed-loop monitoring |
| iac-triage | `.github/skills/_triage/iac-triage/SKILL.md` | Triage IaC plan/apply failures |
| sre-log-fetching | `.github/skills/_triage/sre-log-fetching/SKILL.md` | On-demand log retrieval |
| knowledge-curation | `.github/skills/_core/knowledge-curation/SKILL.md` | Maintain OKF knowledge |
| v1-v2-migration | `.github/skills/_core/v1-v2-migration/SKILL.md` | Gated V1 → V2 migration state machine |

## Guardrails

- `.github/instructions/iac-standards.instructions.md`
- `.github/instructions/compute-patterns.instructions.md`
- `.github/instructions/prod-guardrails.instructions.md`

## Configuration

See `.github/config/platform.yml` for your platform configuration.
"""
