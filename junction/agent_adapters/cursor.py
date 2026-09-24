"""
cursor.py — Adapter for Cursor IDE.

Generates one .cursor/rules/<agent>.mdc rule per graph agent (six), plus an
always-on IaC standards rule. The orchestrator rule is always applied; the
specialists are agent-requested by description.
"""

from __future__ import annotations

import json
from typing import Optional

from junction.agent_adapters._base import AgentAdapter
from junction.agent_specs import AgentSpec
from junction.config_builder import PlatformConfig

_GLOBS = {
    "iac-validator": ["**/*.tf", "**/*.tfvars"],
    "terraform-builder": ["**/*.tf", "**/*.tfvars"],
    "knowledge-curator": [".github/knowledge/**", "docs/**"],
}


class CursorAdapter(AgentAdapter):
    name = "cursor"

    def generate_files(self, platform: PlatformConfig, graph: Optional[dict] = None) -> dict[str, str]:
        files = {
            f".cursor/rules/{spec.name}.mdc": _agent_rule(spec, body)
            for spec, body in self.agents(platform, graph)
        }
        files[".cursor/rules/iac-standards.mdc"] = _iac_standards_rule(platform)
        return files


def _agent_rule(spec: AgentSpec, body: str) -> str:
    always = spec.name == "orchestrator"
    lines = ["---", f"description: {json.dumps(spec.description, ensure_ascii=False)}"]
    if spec.name in _GLOBS:
        lines.append(f"globs: {json.dumps(_GLOBS[spec.name], ensure_ascii=False)}")
    lines += [f"alwaysApply: {str(always).lower()}", "---"]
    return "\n".join(lines) + "\n\n" + body


# ─── Rule generators ──────────────────────────────────────────────────────────


def _iac_standards_rule(p: PlatformConfig) -> str:
    return f"""---
description: IaC coding standards for {p.name}. Always apply when editing .tf or .tfvars files.
globs: ["**/*.tf", "**/*.tfvars"]
alwaysApply: true
---

# IaC Standards — {p.name}

## Naming

`{p.application_name}-{{environment}}-{{service}}[-{{suffix}}]`
- Always computed in locals — never hardcoded in resource blocks

## File Organization

- One `.tf` per logical component / service
- Env-specific values in `tfvars/{{env}}.tfvars` ONLY
- NEVER hardcode ARNs, account IDs, or endpoints in `.tf` files

## Secrets

- `lifecycle {{ ignore_changes = [secret_string] }}` always
- NEVER hardcode credentials
- Initial value: `jsonencode({{}})`

## Tags

- Always `tags = var.tags` or `merge(var.tags, {{ Component = "..." }})`

## Security Groups

- NEVER `0.0.0.0/0` in production egress
- Use `source_security_group_id` within same VPC

## Env-Leak Prevention

Before every push, verify no cross-env values exist:
{chr(10).join(f"- No `{e.account_id}` on `{p.environments[i].branch if i < len(p.environments) else 'other'}` branch" for i, e in enumerate(p.environments) if e.account_id != "000000000000")}
"""
