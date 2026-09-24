import copy

import pytest
import yaml

from junction.graph_generator import NODE_ORDER, dump_agent_graph, generate_agent_graph, write_agent_graph
from junction.graph_schema import AgentGraphValidationError, graph_errors, validate_agent_graph_file
from junction.models import DEFAULT_MODELS, claude_code_alias, parse_model_overrides, resolve_models


def test_default_graph_has_six_nodes_and_is_valid(graph):
    assert list(graph["nodes"]) == NODE_ORDER
    assert graph_errors(graph) == []


def test_default_models_are_current_tiers(graph):
    assert graph["models"] == DEFAULT_MODELS
    assert graph["models"]["planner"] == "claude-opus-5"
    assert graph["models"]["validator"] == "claude-sonnet-5"
    assert "Claude Opus 4" not in dump_agent_graph(graph)


def test_model_overrides_and_no_optimization():
    g = generate_agent_graph({"model_optimization": False}, models={"validator": "claude-haiku-4-5"})
    assert g["models"]["observer"] == "claude-opus-5"
    assert g["models"]["validator"] == "claude-haiku-4-5"


def test_model_override_validation():
    with pytest.raises(ValueError):
        resolve_models({"nope": "x"})
    with pytest.raises(ValueError):
        parse_model_overrides(["validator"])
    assert parse_model_overrides(["builder=claude-fable-5-1"]) == {"builder": "claude-fable-5-1"}


def test_claude_code_alias():
    assert claude_code_alias("claude-opus-5") == "opus"
    assert claude_code_alias("claude-sonnet-5") == "sonnet"
    assert claude_code_alias("gpt-x") == "inherit"


def test_answers_shape_graph():
    g = generate_agent_graph({
        "jira_required": False, "auto_fix_dv": False, "parallel_research": False,
        "env_names": ["dev", "prod"], "naming_pattern": "{app}-{env}-{service} (simple)",
    })
    assert not any(e.get("gate") == "jira_ticket_linked" for e in g["edges"])
    assert g["failure_policy"]["default"]["retry"] == 0
    assert "parallel" not in g
    assert g["naming"] == {"pattern": "{app}-{env}-{service}", "env_values": ["dev", "prod"], "variable": "var.environment"}


@pytest.mark.parametrize("mutate, message", [
    (lambda g: g["nodes"]["sre-observer"]["tools"].append("edit"), "read-only"),
    (lambda g: g["nodes"]["migration-executor"].update(risk_gate="LOW"), "risk_gate must be HIGH"),
    (lambda g: g["failure_policy"]["per_node"]["migration-executor"].update(retry=2), "retry must be 0"),
    (lambda g: g["edges"].pop(0), "jira_ticket_linked"),
    (lambda g: g["nodes"].pop("knowledge-curator"), "knowledge-curator"),
    (lambda g: g["nodes"]["orchestrator"].update(model="genius"), "genius"),
    (lambda g: g["graph"].update(version="1.0"), "2.0"),
    (lambda g: g["evals"]["token_budget"].update(per_node_warn=999999), "token_budget"),
])
def test_invalid_graphs_are_rejected(graph, mutate, message):
    bad = copy.deepcopy(graph)
    mutate(bad)
    errors = graph_errors(bad)
    assert errors and any(message in e for e in errors), errors


def test_write_and_validate_file_roundtrip(graph, tmp_path):
    path = tmp_path / "agent-graph.yml"
    write_agent_graph(graph, str(path))
    text = path.read_text(encoding="utf-8")
    assert "\\u2014" not in text and "—" in text
    assert validate_agent_graph_file(path) == yaml.safe_load(text)


def test_write_refuses_invalid_graph(graph, tmp_path):
    graph["nodes"]["iac-validator"]["tools"].append("write")
    with pytest.raises(AgentGraphValidationError):
        write_agent_graph(graph, str(tmp_path / "g.yml"))
    assert not (tmp_path / "g.yml").exists()
