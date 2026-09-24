"""
graph_schema.py — Validate agent-graph.yml against the v2.0 JSON Schema plus
the safety invariants the schema alone cannot express.

This is the Phase 1 gate: "Agent graph config passes schema validation".
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).parent / "schemas" / "agent-graph.schema.json"

READ_ONLY_NODES = ("iac-validator", "sre-observer")
_WRITE_TOOLS = ("edit", "write")


class AgentGraphValidationError(ValueError):
    """Raised when an agent graph fails schema or invariant validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("agent graph is invalid:\n  - " + "\n  - ".join(errors))


@lru_cache(maxsize=1)
def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def graph_errors(graph: Any) -> list[str]:
    """Return every schema and invariant violation in ``graph`` (empty = valid)."""
    validator = Draft202012Validator(load_schema())
    errors = [
        f"{'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
        for err in sorted(validator.iter_errors(graph), key=lambda e: list(e.absolute_path))
    ]
    if errors:
        return errors
    return _invariant_errors(graph)


def validate_agent_graph(graph: Any) -> None:
    """Raise :class:`AgentGraphValidationError` if ``graph`` is invalid."""
    errors = graph_errors(graph)
    if errors:
        raise AgentGraphValidationError(errors)


def validate_agent_graph_file(path: str | Path) -> dict:
    """Load a YAML graph file, validate it, and return the parsed graph."""
    with open(path, encoding="utf-8") as f:
        graph = yaml.safe_load(f)
    validate_agent_graph(graph)
    return graph


def _invariant_errors(graph: dict) -> list[str]:
    errors: list[str] = []
    nodes = graph["nodes"]
    edges = graph["edges"]

    for name in READ_ONLY_NODES:
        tools = nodes[name]["tools"]
        if any(t in _WRITE_TOOLS for t in tools):
            errors.append(f"nodes/{name}: read-only node must not have edit/write tools")

    migration = nodes["migration-executor"]
    if migration["risk_gate"] != "HIGH":
        errors.append("nodes/migration-executor: risk_gate must be HIGH")
    per_node = graph["failure_policy"]["per_node"]
    if per_node.get("migration-executor", {}).get("retry", 0) != 0:
        errors.append("failure_policy/per_node/migration-executor: retry must be 0 (human gate)")

    if not any(
        e["from"] == "terraform-builder" and e["to"] == "iac-validator" and e.get("gate") == "must pass"
        for e in edges
    ):
        errors.append("edges: terraform-builder → iac-validator 'must pass' gate is required")

    for e in edges:
        if e["from"] == "iac-validator" and e["to"] == "terraform-builder" and "max_cycles" not in e:
            errors.append("edges: iac-validator → terraform-builder loop needs max_cycles")

    reachable = {e["to"] for e in edges if e["from"] == "orchestrator"}
    for name in nodes:
        if name != "orchestrator" and name not in reachable:
            errors.append(f"edges: orchestrator has no route to {name}")

    jira_enabled = graph["governance"]["jira_gate"]["enabled"]
    has_jira_edge = any(e.get("gate") == "jira_ticket_linked" for e in edges)
    if jira_enabled and not has_jira_edge:
        errors.append("edges: jira_gate is enabled but the jira_ticket_linked gate edge is missing")
    if has_jira_edge and not jira_enabled:
        errors.append("governance/jira_gate: jira_ticket_linked edge present but gate disabled")

    budget = graph["evals"]["token_budget"]
    if not budget["per_node_warn"] < budget["per_node_hard"] <= budget["per_work_graph_hard"]:
        errors.append("evals/token_budget: expected per_node_warn < per_node_hard <= per_work_graph_hard")

    return errors
