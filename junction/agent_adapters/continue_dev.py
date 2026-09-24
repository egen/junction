"""
continue_dev.py — Adapter for Continue.dev.

Generates:
  .continue/config.json   — slash-command entries for each major skill
  .continue/context/      — context provider files
  .continue/rules/        — one rule per graph agent (six)
"""

from __future__ import annotations

import json
from typing import Optional

from junction.agent_adapters._base import AgentAdapter
from junction.agent_specs import AgentSpec
from junction.config_builder import PlatformConfig


class ContinueDevAdapter(AgentAdapter):
    name = "continue"

    def generate_files(self, platform: PlatformConfig, graph: Optional[dict] = None) -> dict[str, str]:
        files = {
            ".continue/config.json": _config_json(platform),
            ".continue/context/iac-platform.md": _platform_context(platform),
        }
        for spec, body in self.agents(platform, graph):
            files[f".continue/rules/{spec.name}.md"] = _agent_rule(spec, body)
        return files


def _agent_rule(spec: AgentSpec, body: str) -> str:
    return (
        "---\n"
        f"name: {spec.name}\n"
        f"description: {json.dumps(spec.description, ensure_ascii=False)}\n"
        f"alwaysApply: {str(spec.name == 'orchestrator').lower()}\n"
        "---\n\n" + body
    )


# ─── File generators ──────────────────────────────────────────────────────────


def _config_json(p: PlatformConfig) -> str:
    env_chain = " → ".join(e.name for e in p.environments)
    config = {
        "models": [],
        "slashCommands": [
            {
                "name": "deploy",
                "description": f"Self-healing deploy to {env_chain}",
                "prompt": (
                    f"You are an IaC deployment agent for {p.name}. "
                    f"Platform: {p.iac_tool} / {p.cloud} / {p.compute_type}. "
                    "Follow the self-healing deploy skill at .github/skills/_core/self-healing-deploy/SKILL.md. "
                    "Always run the Boot Protocol first. "
                    "User request: {{{ input }}}"
                ),
            },
            {
                "name": "promote",
                "description": f"Promote IaC changes across {env_chain}",
                "prompt": (
                    f"You are an IaC promotion agent for {p.name}. "
                    "Follow the env-promotion skill at .github/skills/_core/env-promotion/SKILL.md. "
                    "Always run the Boot Protocol first. Never copy env-specific values between branches. "
                    "User request: {{{ input }}}"
                ),
            },
            {
                "name": "drift",
                "description": "Detect configuration drift between environments",
                "prompt": (
                    f"You are a drift detection agent for {p.name}. "
                    "Follow the drift-detection skill at .github/skills/_core/drift-detection/SKILL.md. "
                    "User request: {{{ input }}}"
                ),
            },
            {
                "name": "triage",
                "description": "SRE triage — read-only log and APM analysis",
                "prompt": (
                    f"You are a read-only SRE triage agent for {p.name}. "
                    f"Observability backend: {p.mcp.observability_backend}. "
                    f"Log backend: {p.mcp.cloud_logs_backend}. "
                    "Follow the sre-log-fetching skill at .github/skills/_triage/sre-log-fetching/SKILL.md. "
                    "NEVER modify files. NEVER push commits. "
                    "User request: {{{ input }}}"
                ),
            },
            {
                "name": "migrate",
                "description": "Advance a gated V1 → V2 migration by one phase (HIGH risk)",
                "prompt": (
                    f"You are the migration executor for {p.name}. "
                    "Follow .continue/rules/migration-executor.md and .github/skills/_core/v1-v2-migration/SKILL.md. "
                    "Never retry a failed phase automatically; pause and ask a human. "
                    "User request: {{{ input }}}"
                ),
            },
            {
                "name": "iac-triage",
                "description": "Triage a CI/CD IaC plan/apply failure",
                "prompt": (
                    f"You are an IaC triage agent for {p.name}. "
                    "Follow the iac-triage skill at .github/skills/_triage/iac-triage/SKILL.md. "
                    "User request: {{{ input }}}"
                ),
            },
        ],
        "contextProviders": [
            {
                "name": "file",
                "params": {},
            },
            {
                "name": "iac-platform",
                "description": f"IaC Platform context for {p.name}",
                "params": {
                    "file": ".continue/context/iac-platform.md",
                },
            },
        ],
        "customInstructions": (
            f"This is an IaC + SRE agent platform for {p.name}. "
            f"IaC: {p.iac_tool}. Cloud: {p.cloud}. Compute: {p.compute_type}. "
            "Always read .github/config/platform.yml before infrastructure operations. "
            "Follow the Boot Protocol: git branch --show-current → match env → check risk tier. "
            "Never copy env-specific values between environments. "
            "All log/metric/issue queries must use MCP tools."
        ),
    }
    return json.dumps(config, indent=2, ensure_ascii=False)


def _platform_context(p: PlatformConfig) -> str:
    env_rows = "\n".join(
        f"| {e.name} | `{e.branch}` | `{e.account_id}` | `{e.prefix}` | `{e.risk_tier}` |"
        for e in p.environments
    )
    env_chain = " → ".join(e.name for e in p.environments)
    return f"""# IaC Platform Context — {p.name}

This file is loaded as context by Continue.dev for all IaC operations.

## Platform

- **IaC Tool**: {p.iac_tool}
- **Cloud**: {p.cloud}
- **Compute**: {p.compute_type}
- **CI/CD**: {p.cicd_type}
- **Application**: {p.application_name}

## Environment Chain

`{env_chain}` — promotion must follow this order.

| Env | Branch | Account | Prefix | Risk Tier |
|-----|--------|---------|--------|-----------|
{env_rows}

## Risk Rules

- `LOW` → autonomous
- `MEDIUM` → promotion approval required
- `HIGH` → explicit user confirmation required for every change

## MCP Backends

- Cloud logs: `{p.mcp.cloud_logs_backend}`
- Issue tracker: `{p.mcp.issue_tracker_backend}`
- Observability: `{p.mcp.observability_backend}`
- Log aggregator: `{p.mcp.log_aggregator_backend}`

## Skills

Read the SKILL.md in each directory before executing:

```
.github/skills/
├── _core/drift-detection/SKILL.md
├── _core/env-promotion/SKILL.md
├── _core/post-push-monitor/SKILL.md
├── _core/self-healing-deploy/SKILL.md
├── _triage/iac-triage/SKILL.md
└── _triage/sre-log-fetching/SKILL.md
```
"""
