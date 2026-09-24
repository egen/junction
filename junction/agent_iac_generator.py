"""
agent_iac_generator.py — drive the scaffolded terraform-builder subagent as a
real coding-agent invocation to write infra/, instead of the deterministic
Python template in terraform_generator.py.

This is the "Path 2" design: host-delegated, not API-based. It shells out to
the coding-agent CLI the target repo was already scaffolded for (today: only
`claude-code`, via the `claude` CLI's headless --print mode), running it
*inside* the freshly-scaffolded repo so the agent is grounded in exactly the
context discovery produced: platform.yml, service-registry.md, iac-standards/
compute-patterns/prod-guardrails instructions, and its own persona file
(.claude/agents/terraform-builder.md), which `--agent terraform-builder`
auto-discovers.

This is opt-in (--generate-iac-with-agent) and never the default: it needs
the `claude` CLI installed and authenticated, costs real API usage, and is
non-deterministic — two runs on the same input can produce different, though
both potentially valid, Terraform. The deterministic generator remains the
default for cloud: gcp + iac: terraform/opentofu.

Only claude-code is supported today. Copilot/Cursor/Continue don't expose an
equivalent headless CLI this module can drive non-interactively, so other
agents get a clear "not supported" result rather than a confusing subprocess
failure.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from junction.config_builder import PlatformConfig

SUPPORTED_AGENTS = ("claude-code",)

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_AGENT_TIMEOUT_SECS = 600
DEFAULT_TERRAFORM_TIMEOUT_SECS = 120

# Injectable so tests never shell out to a real, billed, non-deterministic
# coding-agent process: Runner(args, cwd, timeout) -> CompletedProcess.
Runner = Callable[[list[str], Path, int], "subprocess.CompletedProcess[str]"]


@dataclass
class AgentIacResult:
    success: bool
    attempts: int
    message: str
    last_validate_errors: Optional[str] = None
    agent_stdout_tail: str = ""


def _default_runner(args: list[str], cwd: Path, timeout: int) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(args, cwd=cwd, timeout=timeout, capture_output=True, text=True)


def _initial_prompt(platform: PlatformConfig) -> str:
    return f"""You are acting as the terraform-builder agent for this repository.

Generate real Terraform for cloud: {platform.cloud}, iac_tool: {platform.iac_tool} under infra/,
grounded in this repo's own scaffolded context — read before writing anything:
  - .github/config/platform.yml (environments, compute, naming)
  - .github/knowledge/service-registry.md
  - .github/instructions/iac-standards.instructions.md
  - .github/instructions/compute-patterns.instructions.md
  - .github/instructions/prod-guardrails.instructions.md
  - .github/config/discovery-answers.yml, if present

Follow the store-*.tf / platform-*.tf / service-<name>.tf file convention documented
in those instructions. When you are done, run `terraform init -backend=false`, `terraform fmt`,
and `terraform validate` yourself and fix anything they flag before finishing.
"""


def _retry_prompt(validate_errors: str) -> str:
    return f"""`terraform validate` found problems in the infra/ you just wrote:

{validate_errors}

Fix these specific errors in the existing files under infra/. Do not start over from scratch.
Then re-run `terraform validate` yourself to confirm it is clean.
"""


def _run_agent(prompt: str, target_dir: Path, timeout: int, runner: Runner, resume: bool) -> "subprocess.CompletedProcess[str]":
    args = [
        "claude", "-p",
        "--agent", "terraform-builder",
        "--permission-mode", "acceptEdits",
        "--allowedTools", "Read,Write,Edit,Glob,Grep,Bash(terraform *)",
        "--output-format", "json",
    ]
    if resume:
        args.append("--continue")
    args.append(prompt)
    return runner(args, target_dir, timeout)


def _terraform_validate(target_dir: Path, terraform_bin: str, timeout: int) -> tuple[bool, str]:
    """Mirrors scripts/local-e2e-check.sh's init/fmt/validate sequence. Returns
    (clean, diagnostics_text) — diagnostics_text is fed back to the agent verbatim
    on failure, and is empty when clean."""
    infra_dir = target_dir / "infra"
    if not infra_dir.is_dir():
        return False, "infra/ does not exist — the agent did not write any files."

    init = subprocess.run(
        [terraform_bin, "init", "-backend=false", "-input=false"],
        cwd=infra_dir, capture_output=True, text=True, timeout=timeout,
    )
    if init.returncode != 0:
        return False, f"terraform init failed:\n{init.stdout}\n{init.stderr}"

    validate = subprocess.run(
        [terraform_bin, "validate", "-json"],
        cwd=infra_dir, capture_output=True, text=True, timeout=timeout,
    )
    try:
        result = json.loads(validate.stdout)
    except json.JSONDecodeError:
        return False, f"terraform validate produced non-JSON output:\n{validate.stdout}\n{validate.stderr}"

    if result.get("valid"):
        return True, ""

    diagnostics = "\n".join(
        f"- {d.get('severity')}: {d.get('summary')}" for d in result.get("diagnostics", [])
    )
    return False, diagnostics or "terraform validate reported invalid with no diagnostics"


def generate_iac_with_agent(
    target_dir: Path,
    platform: PlatformConfig,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    agent_timeout: int = DEFAULT_AGENT_TIMEOUT_SECS,
    terraform_timeout: int = DEFAULT_TERRAFORM_TIMEOUT_SECS,
    terraform_bin: str = "terraform",
    runner: Optional[Runner] = None,
) -> AgentIacResult:
    """Drive the scaffolded terraform-builder subagent to generate infra/ for
    real, with a validate/fix loop up to max_attempts. Never raises for an
    expected failure mode (unsupported agent, missing persona file, CLI
    failure, validate staying red) — always returns an AgentIacResult so the
    CLI can report clearly and exit non-zero rather than crash."""
    runner = runner or _default_runner

    if platform.agent not in SUPPORTED_AGENTS:
        return AgentIacResult(
            success=False, attempts=0,
            message=(
                f"--generate-iac-with-agent only supports --agent claude-code today "
                f"(this platform is --agent {platform.agent}). No infra/ was generated."
            ),
        )

    persona_file = target_dir / ".claude" / "agents" / "terraform-builder.md"
    if not persona_file.is_file():
        return AgentIacResult(
            success=False, attempts=0,
            message=f"Expected {persona_file} to exist (scaffolding should have written it) — aborting.",
        )

    prompt = _initial_prompt(platform)
    last_validate_errors = ""

    for attempt in range(1, max_attempts + 1):
        try:
            proc = _run_agent(prompt, target_dir, agent_timeout, runner, resume=(attempt > 1))
        except subprocess.TimeoutExpired:
            return AgentIacResult(
                success=False, attempts=attempt,
                message=f"claude -p timed out after {agent_timeout}s on attempt {attempt}.",
                last_validate_errors=last_validate_errors,
            )
        except FileNotFoundError:
            return AgentIacResult(
                success=False, attempts=attempt,
                message="`claude` CLI not found on PATH — install Claude Code to use --generate-iac-with-agent.",
            )

        stdout_tail = (proc.stdout or "")[-2000:]
        if proc.returncode != 0:
            return AgentIacResult(
                success=False, attempts=attempt,
                message=f"claude -p exited {proc.returncode} on attempt {attempt}.",
                last_validate_errors=last_validate_errors,
                agent_stdout_tail=stdout_tail,
            )

        try:
            clean, diagnostics = _terraform_validate(target_dir, terraform_bin, terraform_timeout)
        except subprocess.TimeoutExpired:
            return AgentIacResult(
                success=False, attempts=attempt,
                message=f"terraform validate timed out after {terraform_timeout}s on attempt {attempt}.",
                agent_stdout_tail=stdout_tail,
            )
        except FileNotFoundError:
            return AgentIacResult(
                success=False, attempts=attempt,
                message="`terraform` binary not found on PATH — cannot verify the agent's output.",
                agent_stdout_tail=stdout_tail,
            )

        if clean:
            return AgentIacResult(
                success=True, attempts=attempt,
                message=f"Agent-generated infra/ is terraform validate-clean after {attempt} attempt(s).",
                agent_stdout_tail=stdout_tail,
            )

        last_validate_errors = diagnostics
        prompt = _retry_prompt(diagnostics)

    return AgentIacResult(
        success=False, attempts=max_attempts,
        message=f"Still not terraform validate-clean after {max_attempts} attempts.",
        last_validate_errors=last_validate_errors,
    )
