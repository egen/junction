"""
graph_generator.py — Generate agent-graph.yml from discovery answers.

Takes DiscoveryResult and produces a complete agent graph configuration
tailored to the user's infrastructure, domain, and preferences.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from junction.graph_schema import validate_agent_graph
from junction.models import STRONG_MODEL, resolve_models

DEFAULT_NAMING_PATTERN = "dp-{env}-{domain}-{resource-type}-{purpose}"
DEFAULT_ENV_NAMES = "dv,qc,pr"

NODE_ORDER = [
    "orchestrator",
    "iac-validator",
    "terraform-builder",
    "sre-observer",
    "knowledge-curator",
    "migration-executor",
]

NODE_SKILLS = {
    "orchestrator": ["env-promotion", "drift-detection"],
    "iac-validator": ["drift-detection", "iac-triage"],
    "terraform-builder": ["self-healing-deploy", "post-push-monitor"],
    "sre-observer": ["sre-log-fetching", "iac-triage"],
    "knowledge-curator": ["knowledge-curation"],
    "migration-executor": ["v1-v2-migration"],
}


def env_values(answers: dict[str, Any]) -> list[str]:
    """Environment names from answers — accepts ``"dv,qc,pr"`` or a list."""
    raw = answers.get("env_names", DEFAULT_ENV_NAMES)
    if isinstance(raw, str):
        raw = raw.split(",")
    values = [str(e).strip() for e in raw if str(e).strip()]
    return values or DEFAULT_ENV_NAMES.split(",")


def naming_pattern(answers: dict[str, Any]) -> str:
    """Extract the pattern from a naming answer like ``"dp-{env}-... (CPE standard)"``."""
    raw = str(answers.get("naming_pattern") or DEFAULT_NAMING_PATTERN)
    match = re.match(r"\s*(\S*\{env\}\S*)", raw)
    return match.group(1) if match else DEFAULT_NAMING_PATTERN


def answers_from_platform(platform: Any) -> dict[str, Any]:
    """Default discovery answers derived from a PlatformConfig (no prompts)."""
    envs = [e.name for e in getattr(platform, "environments", [])]
    answers: dict[str, Any] = {"domain_name": getattr(platform, "application_name", None) or "platform"}
    if envs:
        answers["env_names"] = ",".join(envs)
    return answers


def generate_agent_graph(answers: dict[str, Any], models: dict[str, str] | None = None) -> dict:
    """Generate a validated agent-graph.yml structure from discovery answers.

    ``models`` (or ``answers["models"]``) overrides per-tier model ids.
    """
    domain = str(answers.get("domain_name") or "platform")
    jira_gate = bool(answers.get("jira_required", True))
    auto_fix = bool(answers.get("auto_fix_dv", True))
    parallel = bool(answers.get("parallel_research", True))
    model_opt = bool(answers.get("model_optimization", True))
    envs = env_values(answers)
    pattern = naming_pattern(answers)

    graph = {
        "graph": {
            "version": "2.0",
            "type": "org",
            "description": f"IaC coding agent graph — {domain} domain",
            "domain": domain,
        },
        "naming": {
            "pattern": pattern,
            "env_values": envs,
            "variable": "var.environment",
        },
    }

    # Model selection: tiered when optimizing, otherwise every tier on the strong model
    overrides = {**(answers.get("models") or {}), **(models or {})}
    if model_opt:
        graph["models"] = resolve_models(overrides)
    else:
        graph["models"] = resolve_models({tier: STRONG_MODEL for tier in resolve_models()} | overrides)

    # Agent nodes (always 6 — zone defense pattern)
    graph["nodes"] = {
        "orchestrator": {
            "role": "Dispatch + Context Assembly",
            "model": "planner",
            "zone": ["routing", "context-loading", "user-intent"],
            "tools": ["read", "search", "ask-questions", "runSubagent"],
            "risk_gate": "none",
        },
        "iac-validator": {
            "role": "Correctness Gate",
            "model": "validator",
            "zone": ["naming", "env-leak-detection", "reference-integrity"],
            "tools": ["read", "search", "grep", "get-errors"],
            "risk_gate": "none",
        },
        "terraform-builder": {
            "role": "IaC Code Generation",
            "model": "builder",
            "zone": ["terraform-files", "module-calls", "variable-wiring"],
            "tools": ["read", "edit", "search", "terminal", "get-errors"],
            "risk_gate": "MEDIUM",
        },
        "sre-observer": {
            "role": "Post-Deploy Health + Triage",
            "model": "observer",
            "zone": ["health-checks", "log-analysis", "metric-queries"],
            "tools": ["read", "search", "terminal", "mcp:aws-logs", "mcp:newrelic"],
            "risk_gate": "none",
        },
        "knowledge-curator": {
            "role": "OKF Graph Maintenance",
            "model": "curator",
            "zone": ["knowledge-docs", "cross-links", "runbooks"],
            "tools": ["read", "edit", "search"],
            "risk_gate": "LOW",
        },
        "migration-executor": {
            "role": "V1→V2 State Machine",
            "model": "planner",
            "zone": ["migration-state", "phase-gates", "rollback"],
            "tools": ["read", "edit", "search", "terminal", "mcp:aws-logs"],
            "risk_gate": "HIGH",
        },
    }

    # Edges
    edges = [
        {"from": "orchestrator", "to": "terraform-builder", "trigger": "build | scaffold | edit-tf"},
        {"from": "orchestrator", "to": "iac-validator", "trigger": "validate | check | pre-push"},
        {"from": "orchestrator", "to": "sre-observer", "trigger": "triage | health | logs"},
        {"from": "orchestrator", "to": "migration-executor", "trigger": "migrate | phase | cutover"},
        {"from": "orchestrator", "to": "knowledge-curator", "trigger": "update-docs | stale-check"},
        {"from": "terraform-builder", "to": "iac-validator", "trigger": "always", "gate": "must pass"},
        {"from": "iac-validator", "to": "terraform-builder", "trigger": "violations && auto_fixable", "max_cycles": 3},
        {"from": "sre-observer", "to": "knowledge-curator", "trigger": "incident_resolved"},
        {"from": "migration-executor", "to": "sre-observer", "trigger": "phase_completed && health_gate"},
    ]

    if jira_gate:
        edges.insert(0, {"from": "orchestrator", "to": "orchestrator", "trigger": "always_first", "gate": "jira_ticket_linked"})

    graph["edges"] = edges

    for name in NODE_ORDER:
        graph["nodes"][name]["skills"] = NODE_SKILLS[name]

    # Parallel patterns
    if parallel:
        graph["parallel"] = {
            "fan_out_in": {
                "pattern": [
                    {"phase": "research", "parallel": True, "nodes": [
                        {"agent": "sre-observer", "task": "fetch logs"},
                        {"agent": "sre-observer", "task": "query metrics"},
                        {"agent": "knowledge-curator", "task": "load OKF context"},
                    ], "timeout": "30s", "fail_strategy": "partial_ok"},
                    {"phase": "synthesize", "agent": "orchestrator", "action": "deduplicate + rank"},
                    {"phase": "act", "agent": "terraform-builder", "gate": "iac-validator"},
                ],
            },
        }

    # Error handling
    graph["error_handling"] = {
        "decontamination": {
            "on_node_failure": "snapshot context, isolate, do NOT carry forward",
            "on_retry": "reload OKF fresh — never reuse stale context",
            "max_error_chain": 3,
            "after_max": "hard reset — discard in-flight, escalate clean",
        },
    }

    # Failure policy
    graph["failure_policy"] = {
        "default": {"retry": 3 if auto_fix else 0, "backoff": "exponential", "fallback": "escalate_to_human"},
        "per_node": {
            "terraform-builder": {"retry": 3 if auto_fix else 1},
            "sre-observer": {"retry": 1, "fallback": "escalate with raw logs"},
            "migration-executor": {"retry": 0, "fallback": "pause + human gate"},
        },
    }

    # Evals
    graph["evals"] = {
        "token_budget": {"per_node_warn": 50000, "per_node_hard": 100000, "per_work_graph_hard": 500000},
        "costly_patterns": [
            {"pattern": "full workspace scan instead of OKF navigation", "severity": "HIGH"},
            {"pattern": "generating code without knowledge load", "severity": "HIGH"},
            {"pattern": "redundant MCP calls within 5min", "severity": "MEDIUM"},
        ],
    }

    # Governance
    graph["governance"] = {
        "jira_gate": {"enabled": jira_gate, "report_only_on_confirmed": True},
        "knowledge_scope": {"belongs": ["services", "architecture", "runbooks", "contracts", "policies"]},
        "coding_standards": {
            "terraform": [
                "No decorative comment blocks",
                f"Single var.environment ({','.join(envs)})",
                f"Naming: {pattern}",
                "Modules: pinned refs only",
                "Secrets: ignore_changes = [secret_string]",
            ],
        },
    }

    validate_agent_graph(graph)
    return graph


def dump_agent_graph(graph: dict) -> str:
    """Validate and serialize a graph to YAML text."""
    validate_agent_graph(graph)
    header = "# agent-graph.yml — generated by junction. Validate: junction --validate-graph <file>\n"
    return header + yaml.safe_dump(graph, default_flow_style=False, sort_keys=False, width=120, allow_unicode=True)


def write_agent_graph(graph: dict, output_path: str) -> None:
    """Validate and write agent-graph.yml to disk."""
    text = dump_agent_graph(graph)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)
