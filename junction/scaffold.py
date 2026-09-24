"""
scaffold.py — Core file generation and copy logic.

Handles:
  - Rendering Jinja2 templates against a PlatformConfig
  - Copying agent-agnostic framework files (skills, instructions, knowledge)
  - Writing rendered files to the target directory
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from junction import __version__
from junction.config_builder import MCP_BACKENDS, PlatformConfig

# ─── Path helpers ─────────────────────────────────────────────────────────────

# The directory that contains this module (junction/)
_BOOTSTRAP_DIR = Path(__file__).parent

# Templates live in junction/templates/
_TEMPLATES_DIR = _BOOTSTRAP_DIR / "templates"

# Framework files shipped inside the package (mirrors of the repo's .github/
# content, kept in sync by scripts/sync_framework.py). Stored under github/
# because wheels do not reliably carry dot-directories.
FRAMEWORK_DIR = _BOOTSTRAP_DIR / "framework"

# Target-relative paths copied verbatim into every scaffolded repo
FRAMEWORK_FILES: list[str] = [
    # Skills — core, triage, domain template
    ".github/skills/_core/drift-detection/SKILL.md",
    ".github/skills/_core/env-promotion/SKILL.md",
    ".github/skills/_core/post-push-monitor/SKILL.md",
    ".github/skills/_core/self-healing-deploy/SKILL.md",
    ".github/skills/_core/knowledge-curation/SKILL.md",
    ".github/skills/_core/v1-v2-migration/SKILL.md",
    ".github/skills/_triage/iac-triage/SKILL.md",
    ".github/skills/_triage/sre-log-fetching/SKILL.md",
    ".github/skills/_domain/_TEMPLATE.md",
    # Instructions
    ".github/instructions/iac-standards.instructions.md",
    ".github/instructions/compute-patterns.instructions.md",
    ".github/instructions/prod-guardrails.instructions.md",
    ".github/instructions/gcp-fast-stack.instructions.md",
    # Knowledge (templates — user fills these in)
    ".github/knowledge/service-registry.md",
    ".github/knowledge/deployment-policies.md",
    # MCP server interface documentation
    ".github/mcp-servers/README.md",
]


def framework_source(target_rel: str) -> Path:
    """Packaged source file for a target-relative framework path."""
    return FRAMEWORK_DIR / target_rel.replace(".github/", "github/", 1)


# Container registry URI patterns, keyed by `platform.container_registry`. These
# used to be hardcoded to the AWS ECR shape regardless of the chosen registry —
# fixed after testing bootstrap end-to-end against a GCP target.
REGISTRY_URI_PATTERNS: dict[str, str] = {
    "ecr": "{account}.dkr.ecr.{region}.amazonaws.com/{repo}:{tag}",
    "gcr": "gcr.io/{account}/{repo}:{tag}",
    "acr": "{account}.azurecr.io/{repo}:{tag}",
    "dockerhub": "docker.io/{account}/{repo}:{tag}",
    "ghcr": "ghcr.io/{account}/{repo}:{tag}",
}

# CI/CD systems that expose a queryable cloud log group vs. ones whose logs
# live only in the CI system's own UI (no CloudWatch-style log group to name).
CICD_LOG_GROUP_PATTERNS: dict[str, str] = {
    "codebuild": "/aws/codebuild/{repo}-{env}",
}
_CICD_LOG_GROUP_FALLBACK = "n/a — {cicd_type} logs live in its own console/UI, not a named log group"


# ─── Jinja environment ────────────────────────────────────────────────────────


def _jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # Add a tojson filter for lists in YAML output
    import json
    env.filters["tojson"] = lambda v: json.dumps(v)
    env.filters["lower"] = lambda v: str(v).lower()
    return env


# ─── Template context builder ─────────────────────────────────────────────────


def _build_context(platform: PlatformConfig, graph: Optional[dict] = None) -> dict[str, Any]:
    """Build the template context from a PlatformConfig (and, when available,
    the validated agent graph — the single source of truth for naming)."""
    mcp_env_vars = {
        "cloud_logs": MCP_BACKENDS["cloud_logs"]["env_vars"].get(platform.mcp.cloud_logs_backend, []),
        "issue_tracker": MCP_BACKENDS["issue_tracker"]["env_vars"].get(platform.mcp.issue_tracker_backend, []),
        "observability": MCP_BACKENDS["observability"]["env_vars"].get(platform.mcp.observability_backend, []),
        "log_aggregator": MCP_BACKENDS["log_aggregator"]["env_vars"].get(platform.mcp.log_aggregator_backend, []),
    }
    naming_pattern = graph["naming"]["pattern"] if graph else "{application}-{environment}-{service}"
    cicd_log_group = CICD_LOG_GROUP_PATTERNS.get(
        platform.cicd_type, _CICD_LOG_GROUP_FALLBACK.format(cicd_type=platform.cicd_type)
    )
    return {
        "platform": platform,
        "mcp_env_vars": mcp_env_vars,
        "enabled_servers": platform.mcp.enabled_servers(),
        "version": __version__,
        "naming_pattern": naming_pattern,
        "registry_uri_pattern": REGISTRY_URI_PATTERNS.get(platform.container_registry, "{account}/{repo}:{tag}"),
        "cicd_log_group": cicd_log_group,
    }


# ─── Rendering helpers ────────────────────────────────────────────────────────


def render_template(template_name: str, platform: PlatformConfig, graph: Optional[dict] = None) -> str:
    """Render a Jinja2 template by filename and return the content string."""
    jenv = _jinja_env()
    tmpl = jenv.get_template(template_name)
    return tmpl.render(**_build_context(platform, graph))


# ─── Core scaffold operations ─────────────────────────────────────────────────


def render_platform_yml(platform: PlatformConfig, graph: Optional[dict] = None) -> str:
    return render_template("platform.yml.j2", platform, graph)


def render_env_example(platform: PlatformConfig) -> str:
    return render_template("env_example.j2", platform)


def render_mcp_json(platform: PlatformConfig) -> str:
    return render_template("mcp_json.j2", platform)


def generate_copilot_instructions(platform: PlatformConfig) -> str:
    """Render a customized copilot-instructions.md from the platform config."""
    env_rows = "\n".join(
        f"| {e.name} | `{e.branch}` | `{e.account_id}` | `{e.prefix}` | `{e.tfvars}` |"
        for e in platform.environments
    )
    return f"""# AI Coding Agent Instructions — {platform.name}
#
# Generated by junction v{__version__}
# Customize this file for YOUR infrastructure repository.

## Agent Operating Model

Work is split across the six-agent graph in `.github/config/agent-graph.yml`. Every request
starts with the **Orchestrator** (`.github/agents/orchestrator.agent.md`), which runs the
Boot Protocol (confirm branch → environment → risk tier) and routes to one specialist:
`terraform-builder` → `iac-validator` (must pass), `sre-observer` (read-only),
`knowledge-curator`, and `migration-executor` (HIGH risk, human gate).

**Critical rules:**
- Never assume which branch you are on — always `git branch --show-current` first
- All operational data via MCP tools — never local scripts
- Post-push: agent enters Closed Loop — monitors build, triages failures, posts issue tracker updates

## Environment Reference

| Env | Branch | Account | Prefix | tfvars |
|-----|--------|---------|--------|--------|
{env_rows}

## Key Conventions

- **IaC tool**: `{platform.iac_tool}`
- **Cloud**: `{platform.cloud}`
- **Compute**: `{platform.compute_type}`
- **CI/CD**: `{platform.cicd_type}`
- **Service independence**: Each service `.tf` owns env vars, secrets, IAM
- **Image source of truth**: `var.services` in tfvars
- **Secrets lifecycle**: `ignore_changes = [secret_string]` — IaC never overwrites live values
- **MCP-first**: All issue tracking, log, and observability operations via MCP tools

## Infrastructure Organization

```
services.tf           # for_each over var.services
service-locals.tf     # Container definitions, env vars, computed locals
{{service-name}}.tf   # Per-service: env vars, secrets, IAM
iam.tf                # Shared IAM policies
locals.tf             # Common locals
variables.tf          # Variable definitions
tfvars/               # Per-environment config
```

## Tool Usage Rules

| Need | Use | NEVER use |
|------|-----|-----------|
| Issue tracking | Issue tracker MCP server | Direct API calls, local scripts |
| Cloud logs/builds | Cloud logs MCP server | CLI log commands |
| Observability | Observability MCP server | Direct API calls |
| File search | `grep_search` agent tool | Shell grep/find |
| Git operations | Terminal | — |

## Variable Management

- `var.services` is single source of truth for service deployments
- `tfvars/{{env}}.tfvars` for env overrides — NEVER hardcode env-specific values in `.tf` files
"""


def generate_gitignore_additions() -> str:
    """Return .gitignore lines to append for the framework."""
    return """
# IaC Agent Framework
.github/.env-private
.github/memories/
"""


# ─── File collection (dry-run support) ───────────────────────────────────────


def collect_files(
    platform: PlatformConfig,
    graph: Optional[dict] = None,
    answers: Optional[dict] = None,
    skip_terraform_generation: bool = False,
) -> dict[str, str]:
    """
    Return a dict mapping target-relative path → file content.

    This is the agent-agnostic set of files the scaffolder would write (the
    adapter adds agent-specific ones). ``graph`` is the validated agent graph;
    ``answers`` are the discovery answers, recorded for reproducibility.
    ``skip_terraform_generation`` is set when the caller intends to have the
    terraform-builder agent generate infra/ itself after scaffolding, so the
    deterministic template generator's output shouldn't be written first and
    then overwritten/collide with it.
    """
    from junction.discovery import render_implementation_plan
    from junction.graph_generator import dump_agent_graph
    from junction.terraform_generator import generate_terraform

    files: dict[str, str] = {}
    if graph is not None:
        files[".github/config/agent-graph.yml"] = dump_agent_graph(graph)
        files[".github/config/implementation-plan.md"] = render_implementation_plan(answers or {}, graph)

        if not skip_terraform_generation:
            tf_files = generate_terraform(platform, graph, answers or {})
            if tf_files is not None:
                files.update(tf_files)
    if answers:
        files[".github/config/discovery-answers.yml"] = (
            "# Discovery answers — replay with: junction --discover --answers <this file>\n"
            + yaml.safe_dump(answers, sort_keys=False, allow_unicode=True)
        )

    # Rendered templates
    files[".github/config/platform.yml"] = render_platform_yml(platform, graph)
    files[".github/.env-private.example"] = render_env_example(platform)
    files[".vscode/mcp.json"] = render_mcp_json(platform)
    files[".github/copilot-instructions.md"] = generate_copilot_instructions(platform)

    # Agent-agnostic framework files (verbatim copies)
    for rel in FRAMEWORK_FILES:
        src = framework_source(rel)
        if not src.exists():
            raise FileNotFoundError(f"Packaged framework file missing: {src}")
        files[rel] = src.read_text(encoding="utf-8")

    return files


# ─── Write to target directory ────────────────────────────────────────────────


def write_files(
    files: dict[str, str],
    target_dir: Path,
    overwrite: bool = False,
) -> list[str]:
    """
    Write a dict of {relative_path: content} into target_dir.

    Returns a list of paths that were written.
    Raises FileExistsError if a file exists and overwrite=False.
    """
    written: list[str] = []

    for rel_path, content in files.items():
        dest = target_dir / rel_path
        if dest.exists() and not overwrite:
            raise FileExistsError(
                f"{rel_path} already exists in target. Use --overwrite to replace."
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        written.append(rel_path)

    return written


def copy_framework_files(
    platform: PlatformConfig,
    target_dir: Path,
    overwrite: bool = False,
) -> list[str]:
    """
    Collect all framework files, write them, and return list of written paths.
    Agent-specific files are NOT included here — call the adapter after this.
    """
    files = collect_files(platform)
    return write_files(files, target_dir, overwrite=overwrite)


def append_gitignore(target_dir: Path) -> None:
    """Add framework-specific gitignore entries if not already present."""
    gitignore = target_dir / ".gitignore"
    addition = generate_gitignore_additions()

    if gitignore.exists():
        existing = gitignore.read_text(encoding="utf-8")
        if ".env-private" in existing:
            return  # Already handled
        gitignore.write_text(existing.rstrip() + "\n" + addition, encoding="utf-8")
    else:
        gitignore.write_text(addition, encoding="utf-8")
