import pytest

from junction.agent_adapters import ADAPTER_NAMES, get_adapter
from junction.graph_generator import NODE_ORDER

EXPECTED_AGENT_PATHS = {
    "copilot": ".github/agents/{}.agent.md",
    "claude-code": ".claude/agents/{}.md",
    "cursor": ".cursor/rules/{}.mdc",
    "continue": ".continue/rules/{}.md",
    "agnostic": ".agents/{}.md",
}


@pytest.mark.parametrize("agent", ADAPTER_NAMES)
def test_every_adapter_emits_six_agents(agent, platform, graph):
    files = get_adapter(agent).generate_files(platform, graph)
    for node in NODE_ORDER:
        path = EXPECTED_AGENT_PATHS[agent].format(node)
        assert path in files, path
        body = files[path]
        assert body.startswith("---\n")
        assert graph["models"][graph["nodes"][node]["model"]] in body
        assert "\\u" not in body


def test_copilot_frontmatter(platform, graph):
    files = get_adapter("copilot").generate_files(platform, graph)
    orch = files[".github/agents/orchestrator.agent.md"]
    assert '"agent"' in orch and "handoffs:" in orch and "agent: terraform-builder" in orch
    observer = files[".github/agents/sre-observer.agent.md"]
    assert '"cloud-logs/*"' in observer and '"edit"' not in observer.split("---")[1]


def test_claude_code_subagents(platform, graph):
    files = get_adapter("claude-code").generate_files(platform, graph)
    orch = files[".claude/agents/orchestrator.md"]
    assert "tools: Agent(iac-validator, terraform-builder, sre-observer, knowledge-curator, migration-executor)" in orch
    assert "model: opus" in orch
    validator = files[".claude/agents/iac-validator.md"]
    assert "model: sonnet" in validator and "disallowedTools: Edit, Write" in validator
    builder = files[".claude/agents/terraform-builder.md"]
    assert "disallowedTools" not in builder
    assert ".claude/commands/migrate.md" in files
    assert "acts as the Orchestrator" in files["CLAUDE.md"]


def test_adapter_generates_default_graph_when_omitted(platform):
    files = get_adapter("copilot").generate_files(platform)
    assert len([p for p in files if p.endswith(".agent.md")]) == 6
