"""
agent_discovery.py — let the user's own local coding-agent CLI look at the
target repo and propose answers to the junction discovery questionnaire,
instead of answering every question by hand.

Read-only and single-shot, unlike agent_iac_generator.py's write/validate/fix
loop: the agent is only ever given Read/Glob/Grep (no Write/Edit/Bash), so it
can inspect package manifests, Dockerfiles, existing IaC, README, and CI
config for signal, but it never touches the filesystem itself. It returns its
answers as a single fenced YAML block in its final reply; junction parses,
type-checks each field against the real question catalog, and merges the
result in as if it were an answers file — the agent proposes, junction (and
the user, reviewing "Key Decisions Resolved") disposes.

Opt-in via --discover-with-agent. Shells out to the `claude` CLI in headless
mode (`claude -p`) — the only local coding-agent CLI with a non-interactive
mode this module can drive today, independent of which --agent format
(copilot/cursor/claude-code/continue/agnostic) the target repo is scaffolded
for. If `claude` isn't installed, this fails clearly rather than blocking
discovery: the caller falls back to asking every question normally.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import yaml

from junction.discovery import all_questions, normalize_answer

DEFAULT_TIMEOUT_SECS = 180

# Injectable so tests never shell out to a real, billed coding-agent process:
# Runner(args, cwd, timeout) -> CompletedProcess.
Runner = Callable[[list[str], Path, int], "subprocess.CompletedProcess[str]"]


@dataclass
class AgentDiscoveryResult:
    success: bool
    answers: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    message: str = ""
    agent_stdout_tail: str = ""


def _default_runner(args: list[str], cwd: Path, timeout: int) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(args, cwd=cwd, timeout=timeout, capture_output=True, text=True)


def _prompt() -> str:
    catalog = "\n".join(
        f"- id: {q['id']}\n"
        f"  question: {q['question']}\n"
        f"  type: {q['type']}"
        + (f"\n  options: {q['options']!r}" if q.get("options") else "")
        + (f"\n  format: {q['pattern_hint']}" if q.get("pattern_hint") else "")
        for q in all_questions()
    )
    return f"""Inspect this repository (read-only — you have no write or execute tools, so
just look) and propose answers to the junction discovery questionnaire below, based on
what you find: package manifests, Dockerfiles, existing IaC, README, CI config, and the
git remote/repo name. Where the repo gives no real signal for a question, use your best
generic default rather than leaving it out.

Questions:
{catalog}

Respond with ONLY a single fenced yaml code block containing a flat mapping of question
id to answer — no prose before or after it. Booleans as true/false. For "type: choice"
questions, copy the chosen option verbatim from its options list.
"""


def _run_agent(prompt: str, target_dir: Path, timeout: int, runner: Runner) -> "subprocess.CompletedProcess[str]":
    args = [
        "claude", "-p",
        "--permission-mode", "acceptEdits",
        "--allowedTools", "Read,Glob,Grep",
        "--output-format", "json",
        prompt,
    ]
    return runner(args, target_dir, timeout)


def _extract_yaml_block(text: str) -> Optional[str]:
    match = re.search(r"```ya?ml\s*\n(.*?)```", text, re.DOTALL)
    return match.group(1) if match else None


def propose_answers_with_agent(
    target_dir: Path,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECS,
    runner: Optional[Runner] = None,
) -> AgentDiscoveryResult:
    """Ask the local `claude` CLI to inspect ``target_dir`` and propose answers.

    Never raises for an expected failure mode (missing repo, missing `claude`
    binary, timeout, unparseable reply) — always returns an
    AgentDiscoveryResult with ``success=False`` and a clear ``message``, so the
    caller can fall back to asking every question normally instead of crashing
    the whole discovery run.
    """
    runner = runner or _default_runner

    if not target_dir.is_dir():
        return AgentDiscoveryResult(
            success=False,
            message=f"{target_dir} does not exist — nothing for the agent to inspect.",
        )

    try:
        proc = _run_agent(_prompt(), target_dir, timeout, runner)
    except subprocess.TimeoutExpired:
        return AgentDiscoveryResult(success=False, message=f"claude -p timed out after {timeout}s.")
    except FileNotFoundError:
        return AgentDiscoveryResult(
            success=False,
            message="`claude` CLI not found on PATH — install Claude Code to use --discover-with-agent.",
        )

    stdout_tail = (proc.stdout or "")[-2000:]
    if proc.returncode != 0:
        return AgentDiscoveryResult(
            success=False, message=f"claude -p exited {proc.returncode}.", agent_stdout_tail=stdout_tail,
        )

    try:
        reply_text = json.loads(proc.stdout).get("result", proc.stdout)
    except (json.JSONDecodeError, AttributeError):
        reply_text = proc.stdout

    yaml_block = _extract_yaml_block(reply_text)
    if yaml_block is None:
        return AgentDiscoveryResult(
            success=False, message="Agent's reply did not contain a yaml code block.", agent_stdout_tail=stdout_tail,
        )

    try:
        raw = yaml.safe_load(yaml_block)
    except yaml.YAMLError as exc:
        return AgentDiscoveryResult(
            success=False, message=f"Agent's yaml block did not parse: {exc}", agent_stdout_tail=stdout_tail,
        )

    if not isinstance(raw, dict):
        return AgentDiscoveryResult(
            success=False, message="Agent's yaml block was not a mapping of question id to answer.",
            agent_stdout_tail=stdout_tail,
        )

    by_id = {q["id"]: q for q in all_questions()}
    answers: dict = {}
    warnings: list[str] = []
    for key, value in raw.items():
        if key not in by_id:
            warnings.append(f"ignored unknown field {key!r} proposed by the agent")
            continue
        try:
            answers[key] = normalize_answer(by_id[key], value)
        except ValueError as exc:
            warnings.append(f"ignored invalid value for {key!r}: {exc}")

    return AgentDiscoveryResult(
        success=True,
        answers=answers,
        warnings=warnings,
        message=f"Agent proposed {len(answers)} of {len(by_id)} answers"
        + (f" ({len(warnings)} skipped, see warnings)" if warnings else ""),
        agent_stdout_tail=stdout_tail,
    )
