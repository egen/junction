from pathlib import Path
from unittest.mock import patch

import yaml
from click.testing import CliRunner

from junction import Bootstrap, Platform, __version__
from junction.agent_discovery import AgentDiscoveryResult
from junction.cli import main
from junction.graph_generator import NODE_ORDER
from junction.scaffold import FRAMEWORK_FILES, framework_source

ROOT = Path(__file__).resolve().parent.parent


def test_packaged_framework_matches_repo():
    for rel in FRAMEWORK_FILES:
        assert framework_source(rel).read_bytes() == (ROOT / rel).read_bytes(), (
            f"{rel} drifted — run scripts/sync_framework.py"
        )


def test_version_is_consistent():
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert f'version = "{__version__}"' in pyproject


def test_cli_discover_end_to_end(tmp_path):
    target = tmp_path / "repo"
    result = CliRunner().invoke(main, [
        "--discover", "--defaults", "--agent", "claude-code", "--domain", "payments",
        "--model", "curator=claude-haiku-4-5", "--target", str(target), "--yes",
    ])
    assert result.exit_code == 0, result.output
    for node in NODE_ORDER:
        assert (target / ".claude/agents" / f"{node}.md").exists()
    graph = yaml.safe_load((target / ".github/config/agent-graph.yml").read_text())
    assert graph["graph"]["domain"] == "payments"
    assert graph["models"]["curator"] == "claude-haiku-4-5"
    answers = yaml.safe_load((target / ".github/config/discovery-answers.yml").read_text())
    assert answers["agent"] == "claude-code"
    assert (target / ".github/config/implementation-plan.md").exists()
    assert (target / ".github/skills/_core/v1-v2-migration/SKILL.md").exists()

    replay = CliRunner().invoke(main, [
        "--answers", str(target / ".github/config/discovery-answers.yml"),
        "--target", str(tmp_path / "replay"), "--yes",
    ])
    assert replay.exit_code == 0, replay.output
    assert (tmp_path / "replay/.claude/agents/migration-executor.md").exists()

    validate = CliRunner().invoke(main, ["--validate-graph", str(target / ".github/config/agent-graph.yml")])
    assert validate.exit_code == 0 and "valid agent graph" in validate.output


def test_cli_refuses_to_overwrite_with_yes(tmp_path):
    args = ["--discover", "--defaults", "--target", str(tmp_path), "--yes"]
    assert CliRunner().invoke(main, args).exit_code == 0
    again = CliRunner().invoke(main, args)
    assert again.exit_code == 1 and "--overwrite" in again.output
    assert CliRunner().invoke(main, args + ["--overwrite"]).exit_code == 0


def test_cli_config_path_writes_six_agents(tmp_path):
    result = CliRunner().invoke(main, [
        "--config", str(ROOT / ".github/config/platform.yml"), "--agent", "copilot",
        "--target", str(tmp_path), "--yes",
    ])
    assert result.exit_code == 0, result.output
    assert len(list((tmp_path / ".github/agents").glob("*.agent.md"))) == 6


def test_cli_rejects_invalid_graph(tmp_path, graph):
    graph["nodes"]["migration-executor"]["risk_gate"] = "LOW"
    bad = tmp_path / "bad.yml"
    bad.write_text(yaml.safe_dump(graph))
    result = CliRunner().invoke(main, ["--validate-graph", str(bad)])
    assert result.exit_code == 1 and "risk_gate must be HIGH" in result.output


def test_discover_with_agent_fills_gaps_but_flags_win(tmp_path):
    """The agent's proposal fills questions the user didn't answer, but an
    explicit --domain always wins over what the agent proposed for the same
    field — and target must already exist (this inspects a real repo)."""
    target = tmp_path / "repo"
    target.mkdir()
    (target / "requirements.txt").write_text("fastapi\n")

    proposed = AgentDiscoveryResult(
        success=True,
        answers={"domain_name": "agent-guessed-name", "has_msk": False, "cloud": "gcp"},
        message="Agent proposed 3 of 17 answers",
    )
    with patch("junction.agent_discovery.propose_answers_with_agent", return_value=proposed) as mocked:
        result = CliRunner().invoke(main, [
            "--discover-with-agent", "--defaults", "--domain", "payments",
            "--target", str(target), "--yes",
        ])

    assert result.exit_code == 0, result.output
    assert mocked.call_args[0][0] == target.resolve()
    assert "(agent)" in result.output
    graph = yaml.safe_load((target / ".github/config/agent-graph.yml").read_text())
    # --domain (a real flag) beats the agent's guess for the same field
    assert graph["graph"]["domain"] == "payments"
    answers = yaml.safe_load((target / ".github/config/discovery-answers.yml").read_text())
    assert answers["has_msk"] is False  # not overridden anywhere else, so the agent's answer sticks
    assert answers["cloud"] == "gcp"


def test_discover_with_agent_missing_target_fails_clearly(tmp_path):
    result = CliRunner().invoke(main, [
        "--discover-with-agent", "--defaults", "--target", str(tmp_path / "nope"), "--yes",
    ])
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_sdk_from_discovery(tmp_path):
    b = Bootstrap.from_discovery({"agent": "cursor", "domain_name": "savings"}, target_dir=tmp_path)
    files = b.dry_run()
    assert ".github/config/agent-graph.yml" in files
    assert len([p for p in files if p.startswith(".cursor/rules/") and p != ".cursor/rules/iac-standards.mdc"]) == 6
    written = b.run()
    assert (tmp_path / ".cursor/rules/orchestrator.mdc").exists() and len(written) == len(files)


def test_sdk_platform_only_still_gets_graph(tmp_path):
    platform = Platform.from_answers({"agent": "agnostic", "environments": [{"name": "dev"}, {"name": "prod", "risk_tier": "HIGH"}]})
    files = Bootstrap(platform, target_dir=tmp_path).dry_run()
    graph = yaml.safe_load(files[".github/config/agent-graph.yml"])
    assert graph["naming"]["env_values"] == ["dev", "prod"]
    assert "AGENTS.md" in files


def test_platform_yml_is_cloud_aware_and_naming_matches_graph(tmp_path):
    """Regression test for the AWS-only platform.yml.j2 bugs found testing bootstrap
    against a GCP target: registry URI, CI/CD log group, version string, and the
    naming.pattern split-brain between platform.yml and agent-graph.yml."""
    from junction import __version__
    from junction.config_builder import PlatformConfig
    from junction.graph_generator import generate_agent_graph
    from junction.scaffold import render_platform_yml

    gcp_platform = PlatformConfig(
        cloud="gcp", container_registry="gcr", cicd_type="github_actions", application_name="orders",
    )
    graph = generate_agent_graph({"domain_name": "orders", "naming_pattern": "CPE"})
    rendered = render_platform_yml(gcp_platform, graph)

    assert f"v{__version__}" in rendered
    assert "amazonaws.com" not in rendered and "aws/codebuild" not in rendered
    assert "gcr.io/{account}/{repo}:{tag}" in rendered
    assert "github_actions logs live in its own console" in rendered
    assert f'pattern: "{graph["naming"]["pattern"]}"' in rendered

    aws_platform = PlatformConfig(cloud="aws", container_registry="ecr", cicd_type="codebuild")
    aws_rendered = render_platform_yml(aws_platform, generate_agent_graph({}))
    assert "amazonaws.com" in aws_rendered and "/aws/codebuild/" in aws_rendered
