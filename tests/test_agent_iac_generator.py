import subprocess
from unittest.mock import patch

import pytest

from junction.agent_iac_generator import AgentIacResult, generate_iac_with_agent
from junction.config_builder import PlatformConfig


def _cp(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=["claude"], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def claude_code_platform():
    return PlatformConfig(cloud="gcp", iac_tool="terraform", agent="claude-code", application_name="orders")


@pytest.fixture
def scaffolded_repo(tmp_path):
    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "terraform-builder.md").write_text("# terraform-builder persona\n")
    return tmp_path


def test_unsupported_agent_never_shells_out(scaffolded_repo):
    """copilot/cursor/continue don't have an equivalent headless CLI this module
    can drive — must fail fast and clearly, never attempt a subprocess call."""
    copilot_platform = PlatformConfig(cloud="gcp", agent="copilot", application_name="orders")
    runner = lambda *a, **k: pytest.fail("must not shell out for an unsupported agent")  # noqa: E731
    result = generate_iac_with_agent(scaffolded_repo, copilot_platform, runner=runner)
    assert result.success is False
    assert result.attempts == 0
    assert "claude-code" in result.message


def test_missing_persona_file_fails_fast(tmp_path, claude_code_platform):
    """No .claude/agents/terraform-builder.md means scaffolding didn't run —
    give a clear error instead of a confusing claude CLI failure."""
    runner = lambda *a, **k: pytest.fail("must not shell out with no persona file")  # noqa: E731
    result = generate_iac_with_agent(tmp_path, claude_code_platform, runner=runner)
    assert result.success is False
    assert result.attempts == 0
    assert "terraform-builder.md" in result.message


def test_success_on_first_attempt(scaffolded_repo, claude_code_platform):
    calls = []

    def runner(args, cwd, timeout):
        calls.append(args)
        return _cp(returncode=0)

    with patch(
        "junction.agent_iac_generator._terraform_validate",
        return_value=(True, ""),
    ):
        result = generate_iac_with_agent(scaffolded_repo, claude_code_platform, runner=runner)

    assert result.success is True
    assert result.attempts == 1
    assert len(calls) == 1
    assert "--agent" in calls[0] and "terraform-builder" in calls[0]
    assert "--continue" not in calls[0]  # first attempt is a fresh session


def test_retries_with_validate_errors_then_succeeds(scaffolded_repo, claude_code_platform):
    calls = []

    def runner(args, cwd, timeout):
        calls.append(args)
        return _cp(returncode=0)

    validate_results = [(False, "- error: bad resource"), (True, "")]

    with patch(
        "junction.agent_iac_generator._terraform_validate",
        side_effect=validate_results,
    ):
        result = generate_iac_with_agent(scaffolded_repo, claude_code_platform, max_attempts=3, runner=runner)

    assert result.success is True
    assert result.attempts == 2
    assert len(calls) == 2
    # second attempt resumes the same session and includes the validate error text
    assert "--continue" in calls[1]
    assert "bad resource" in calls[1][-1]


def test_gives_up_after_max_attempts(scaffolded_repo, claude_code_platform):
    def runner(args, cwd, timeout):
        return _cp(returncode=0)

    with patch(
        "junction.agent_iac_generator._terraform_validate",
        return_value=(False, "- error: still broken"),
    ):
        result = generate_iac_with_agent(scaffolded_repo, claude_code_platform, max_attempts=2, runner=runner)

    assert result.success is False
    assert result.attempts == 2
    assert result.last_validate_errors == "- error: still broken"


def test_agent_cli_nonzero_exit_stops_immediately_not_a_retry(scaffolded_repo, claude_code_platform):
    """A claude -p failure (bad flags, auth error, crash) is not something a
    validate-error retry can fix — stop immediately rather than burning
    attempts on a broken invocation."""
    calls = []

    def runner(args, cwd, timeout):
        calls.append(args)
        return _cp(returncode=1, stderr="authentication error")

    result = generate_iac_with_agent(scaffolded_repo, claude_code_platform, max_attempts=3, runner=runner)

    assert result.success is False
    assert result.attempts == 1
    assert len(calls) == 1


def test_agent_timeout_reported_not_raised(scaffolded_repo, claude_code_platform):
    def runner(args, cwd, timeout):
        raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)

    result = generate_iac_with_agent(scaffolded_repo, claude_code_platform, agent_timeout=5, runner=runner)
    assert result.success is False
    assert "timed out" in result.message


def test_missing_claude_binary_reported_not_raised(scaffolded_repo, claude_code_platform):
    def runner(args, cwd, timeout):
        raise FileNotFoundError("claude")

    result = generate_iac_with_agent(scaffolded_repo, claude_code_platform, runner=runner)
    assert result.success is False
    assert "PATH" in result.message
