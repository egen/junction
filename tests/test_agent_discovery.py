import json
import subprocess

import pytest

from junction.agent_discovery import AgentDiscoveryResult, propose_answers_with_agent


def _cp(returncode=0, result_text="", stdout=None, stderr=""):
    """Build a fake claude -p --output-format json CompletedProcess.

    Pass ``result_text`` for the normal case (wrapped in the {"result": ...}
    envelope); pass ``stdout`` directly to simulate a non-JSON/malformed reply.
    """
    if stdout is None:
        stdout = json.dumps({"type": "result", "subtype": "success", "result": result_text})
    return subprocess.CompletedProcess(args=["claude"], returncode=returncode, stdout=stdout, stderr=stderr)


def _yaml_reply(body: str) -> str:
    return f"Here you go:\n```yaml\n{body}\n```\n"


def test_missing_target_dir_never_shells_out(tmp_path):
    runner = lambda *a, **k: pytest.fail("must not shell out for a nonexistent repo")  # noqa: E731
    result = propose_answers_with_agent(tmp_path / "does-not-exist", runner=runner)
    assert result.success is False
    assert "does not exist" in result.message


def test_success_parses_and_normalizes_answers(tmp_path):
    calls = []

    def runner(args, cwd, timeout):
        calls.append(args)
        return _cp(result_text=_yaml_reply(
            "domain_name: orders\nhas_rds: true\nhas_msk: no\ncloud: aws\n"
        ))

    result = propose_answers_with_agent(tmp_path, runner=runner)

    assert result.success is True
    assert result.answers == {"domain_name": "orders", "has_rds": True, "has_msk": False, "cloud": "aws"}
    assert result.warnings == []
    allowed_tools = calls[0][calls[0].index("--allowedTools") + 1]
    assert allowed_tools == "Read,Glob,Grep"
    assert calls[0][-1]  # the prompt is the last positional arg


def test_unknown_and_invalid_fields_are_warned_not_fatal(tmp_path):
    def runner(args, cwd, timeout):
        return _cp(result_text=_yaml_reply(
            "domain_name: orders\nnot_a_real_question: 42\ncloud: mars\n"
        ))

    result = propose_answers_with_agent(tmp_path, runner=runner)

    assert result.success is True
    assert result.answers == {"domain_name": "orders"}
    assert len(result.warnings) == 2
    assert any("not_a_real_question" in w for w in result.warnings)
    assert any("cloud" in w for w in result.warnings)


def test_invalid_domain_name_dropped_with_warning_not_fatal(tmp_path):
    """Regression test for the crash a verbose agent-proposed domain_name used
    to cause deep in terraform_generator.py, after the whole discovery run had
    already printed: normalize_answer's pattern check now catches it here, and
    propose_answers_with_agent's existing per-field try/except turns that into
    a warning + drop, exactly like any other invalid field."""
    def runner(args, cwd, timeout):
        return _cp(result_text=_yaml_reply(
            "domain_name: AI data factory (Cloud SQL database provisioning)\ncloud: gcp\n"
        ))

    result = propose_answers_with_agent(tmp_path, runner=runner)

    assert result.success is True
    assert result.answers == {"cloud": "gcp"}
    assert any("domain_name" in w and "lowercase" in w for w in result.warnings)


def test_no_yaml_block_in_reply_fails_clearly(tmp_path):
    def runner(args, cwd, timeout):
        return _cp(result_text="I looked around but didn't find much to go on.")

    result = propose_answers_with_agent(tmp_path, runner=runner)
    assert result.success is False
    assert "yaml" in result.message.lower()


def test_non_json_stdout_falls_back_to_raw_text(tmp_path):
    """--output-format json should always give JSON, but don't crash if a
    future CLI version or a flag mismatch ever returns plain text instead."""
    def runner(args, cwd, timeout):
        return _cp(stdout=_yaml_reply("domain_name: orders\n"))

    result = propose_answers_with_agent(tmp_path, runner=runner)
    assert result.success is True
    assert result.answers == {"domain_name": "orders"}


def test_agent_cli_nonzero_exit_fails_clearly(tmp_path):
    def runner(args, cwd, timeout):
        return _cp(returncode=1, stderr="authentication error")

    result = propose_answers_with_agent(tmp_path, runner=runner)
    assert result.success is False
    assert "exited 1" in result.message


def test_timeout_reported_not_raised(tmp_path):
    def runner(args, cwd, timeout):
        raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)

    result = propose_answers_with_agent(tmp_path, timeout=5, runner=runner)
    assert result.success is False
    assert "timed out" in result.message


def test_missing_claude_binary_reported_not_raised(tmp_path):
    def runner(args, cwd, timeout):
        raise FileNotFoundError("claude")

    result = propose_answers_with_agent(tmp_path, runner=runner)
    assert result.success is False
    assert "PATH" in result.message
