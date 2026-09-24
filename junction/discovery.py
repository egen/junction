"""
discovery.py — Interactive Discovery Engine for Junction

Learns about the user's existing infrastructure, asks junction questions to
prevent drift and repetition, and produces a phased implementation plan.

Inspired by production learnings from scaffolding solution-dp-person:
- Graph Engineering: 6 specialist agents with zone defense
- OKF Knowledge: platform-durable facts only (no story state)
- JIRA Gate: every task must link to a ticket before work begins
- CPE Naming: dp-{env}-{domain}-{resource-type}-{purpose}
- Error Decontamination: failed states never carry forward
- Parallel Research: fan-out/fan-in before acting
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from junction.config_builder import (
    AGENT_CHOICES,
    CLOUD_PROVIDERS,
    IAC_TOOLS,
    EnvironmentConfig,
    PlatformConfig,
    cloud_defaults,
    default_risk_tier,
)

console = Console()


# ─── Junction Questions (reduce drift by asking at the right time) ────────────

PHASE_QUESTIONS = {
    "platform": [
        {
            "id": "agent",
            "question": "Which coding agent will run the agent graph?",
            "type": "choice",
            "options": AGENT_CHOICES,
            "default": "copilot",
            "rationale": "Decides the agent file format: Copilot agents, Claude Code subagents, Cursor/Continue rules or AGENTS.md.",
        },
        {
            "id": "cloud",
            "question": "Which cloud provider?",
            "type": "choice",
            "options": CLOUD_PROVIDERS,
            "default": "aws",
            "rationale": "Sets compute, registry, CI/CD and MCP backend defaults.",
        },
        {
            "id": "iac_tool",
            "question": "Which IaC tool?",
            "type": "choice",
            "options": IAC_TOOLS,
            "default": "terraform",
            "rationale": "The builder and validator agents target this tool.",
        },
    ],
    "discovery": [
        {
            "id": "existing_repo",
            "question": "Do you have an existing IaC repo you're migrating FROM?",
            "type": "confirm",
            "default": False,
            "follow_up": "existing_repo_details",
            "rationale": "If migrating, we extract env vars, secrets, and naming patterns from V1.",
        },
        {
            "id": "domain_name",
            "question": "What business domain does this repo serve?",
            "type": "text",
            "default": "platform",
            "examples": "person, health, savings, leaves, payments",
            "rationale": "Domain name becomes part of all resource names: dp-{env}-{domain}-*",
        },
        {
            "id": "env_count",
            "question": "How many environments do you deploy to?",
            "type": "int",
            "default": 3,
            "rationale": "Determines branch strategy, risk tiers, and promotion chain.",
        },
        {
            "id": "env_names",
            "question": "Environment names (comma-separated, lowest→highest risk)?",
            "type": "text",
            "default": "dv,qc,pr",
            "rationale": "Maps to branches, tfvars files, and AWS profiles.",
        },
        {
            "id": "service_count",
            "question": "How many ECS services will this repo manage?",
            "type": "int",
            "default": 5,
            "rationale": "Determines if for_each pattern or individual files. >3 = for_each.",
        },
        {
            "id": "shared_services",
            "question": "Do multiple services share the same Docker image (e.g., MDM entities)?",
            "type": "confirm",
            "default": False,
            "follow_up": "domain_map",
            "rationale": "If yes, we use for_each domain map pattern (8 services → 1 file).",
        },
    ],
    "naming": [
        {
            "id": "naming_pattern",
            "question": "What naming standard does your org use for AWS resources?",
            "type": "choice",
            "options": [
                "dp-{env}-{domain}-{resource-type}-{purpose} (CPE standard)",
                "{app}-{env}-{service} (simple)",
                "Custom (I'll provide the pattern)",
            ],
            "rationale": "Naming is enforced by IaC Validator agent. Must be decided upfront.",
        },
        {
            "id": "resource_type_tokens",
            "question": "Do resource names include AWS service type (ecs, rds, msk, lambda)?",
            "type": "confirm",
            "default": True,
            "rationale": "CPE standard requires it. Affects locals.tf prefix definitions.",
        },
        {
            "id": "module_registry",
            "question": "Where are your Terraform modules hosted?",
            "type": "choice",
            "options": [
                "CodeCommit (git::codecommit://module-aws-*?ref=vN)",
                "Terraform Registry (hashicorp/aws)",
                "GitHub private (git::https://github.com/org/module?ref=vN)",
                "Local modules (./modules/*)",
            ],
            "rationale": "Module source pattern enforced across all .tf files.",
        },
    ],
    "data_stores": [
        {
            "id": "has_rds",
            "question": "Does this domain use RDS/Aurora PostgreSQL?",
            "type": "confirm",
            "default": True,
            "follow_up": "rds_details",
            "rationale": "If yes, generates store-aurora.tf with IAM auth + SG rules.",
        },
        {
            "id": "has_msk",
            "question": "Does this domain use MSK/Kafka for streaming?",
            "type": "confirm",
            "default": True,
            "follow_up": "msk_details",
            "rationale": "If yes, generates store-msk.tf with topics, IAM, SG rules.",
        },
        {
            "id": "msk_cluster_shared",
            "question": "Are the MSK topics on a shared cluster (vs a dedicated one)?",
            "type": "confirm",
            "default": True,
            "only_if": "has_msk",
            "rationale": "Shared clusters need a domain topic prefix and cross-account IAM; dedicated ones own the cluster.",
        },
        {
            "id": "has_s3",
            "question": "Does this domain use S3 for data storage?",
            "type": "confirm",
            "default": True,
            "rationale": "If yes, generates store-s3.tf with KMS + lifecycle.",
        },
        {
            "id": "kms_strategy",
            "question": "KMS encryption strategy?",
            "type": "choice",
            "options": [
                "Cross-account key (central KMS account, per-env keys)",
                "Same-account key (one per env within workload account)",
                "AWS managed keys (no custom KMS)",
            ],
            "rationale": "Cross-account needs key policy with service principals.",
        },
    ],
    "agent_graph": [
        {
            "id": "jira_required",
            "question": "Must every task be linked to a JIRA/Linear ticket?",
            "type": "confirm",
            "default": True,
            "rationale": "If yes, JIRA gate blocks orchestrator until ticket validated.",
        },
        {
            "id": "auto_fix_dv",
            "question": "Should the agent auto-fix failures in dev (up to 3 retries)?",
            "type": "confirm",
            "default": True,
            "rationale": "Self-healing deploy loop. Only for LOW risk environments.",
        },
        {
            "id": "parallel_research",
            "question": "Enable parallel log/metric fetching before diagnosis?",
            "type": "confirm",
            "default": True,
            "rationale": "Fan-out/fan-in pattern: fetch logs + metrics + knowledge in parallel.",
        },
        {
            "id": "model_optimization",
            "question": "Optimize model selection per agent (cheaper for read-only)?",
            "type": "confirm",
            "default": True,
            "rationale": "Validators/observers use Sonnet (cheaper), builders use Opus.",
        },
    ],
    "secrets": [
        {
            "id": "secret_strategy",
            "question": "How do services get database credentials?",
            "type": "choice",
            "options": [
                "IAM auth (no passwords, token-based)",
                "Secrets Manager (JSON bundle per service)",
                "Both (IAM where possible, SM for external systems)",
            ],
            "rationale": "IAM auth = zero secrets for internal services. SM = external deps.",
        },
        {
            "id": "external_systems",
            "question": "List external systems that need credentials (comma-separated)?",
            "type": "text",
            "default": "",
            "examples": "UDP Kafka, Identity Service API, AAAS API",
            "rationale": "Each external system = one SM secret bundle with ignore_changes.",
        },
        {
            "id": "nr_license_strategy",
            "question": "How is New Relic license key provided?",
            "type": "choice",
            "options": [
                "Cross-account SM ARN (shared ECR account secret)",
                "Per-env SM secret (managed in this repo)",
                "Not using New Relic",
            ],
            "rationale": "Cross-account = hardcoded ARN. Per-env = variable.",
        },
    ],
}


# ─── Phased Implementation Plan ──────────────────────────────────────────────

IMPLEMENTATION_PHASES = [
    {
        "phase": 0,
        "name": "Discovery + Design",
        "description": "Ask questions, resolve naming, confirm architecture",
        "outputs": ["platform.yml", "agent-graph.yml", "naming-standard.md"],
        "gate": "User confirms design decisions",
        "junction_questions": ["platform", "discovery", "naming"],
    },
    {
        "phase": 1,
        "name": "Scaffold Agent Graph",
        "description": "Create agents, skills, instructions, knowledge structure",
        "outputs": ["6 agents", "8 skills", "3 instructions", "OKF knowledge dirs"],
        "gate": "Agent graph config passes schema validation",
        "junction_questions": ["agent_graph"],
    },
    {
        "phase": 2,
        "name": "Build Store Layer",
        "description": "Stateful resources (Aurora, MSK, S3) with KMS",
        "outputs": ["store-aurora.tf", "store-msk.tf", "store-s3.tf"],
        "gate": "terraform validate passes",
        "junction_questions": ["data_stores", "secrets"],
    },
    {
        "phase": 3,
        "name": "Build Platform Layer",
        "description": "ECS cluster, services for_each, IAM, ALB, log groups",
        "outputs": ["platform-ecs*.tf", "platform-kms.tf", "platform-vpc.tf"],
        "gate": "Module interface validation (clone modules, check outputs)",
        "junction_questions": [],
    },
    {
        "phase": 4,
        "name": "Build Service Layer",
        "description": "Per-service env vars, secrets, IAM policies",
        "outputs": ["service-*.tf files", "Secrets Manager resources"],
        "gate": "Env var parity confirmed against running V1 (if migrating)",
        "junction_questions": ["secrets"],
    },
    {
        "phase": 5,
        "name": "MCP + DevContainer",
        "description": "Wire MCP servers, devcontainer for local plan",
        "outputs": [".vscode/mcp.json", ".devcontainer/", "MCP server.py files"],
        "gate": "MCP servers start without errors",
        "junction_questions": [],
    },
    {
        "phase": 6,
        "name": "Evals + First Test",
        "description": "Run evals, test agent graph with a real task",
        "outputs": ["evals.log", "First service added via agent graph"],
        "gate": "Evals PASS, agent produces valid TF, IaC Validator approves",
        "junction_questions": [],
    },
]


# ─── Discovery Runner ─────────────────────────────────────────────────────────


@dataclass
class DiscoveryResult:
    answers: dict[str, Any] = field(default_factory=dict)
    phase_plan: list[dict] = field(default_factory=list)


def all_questions() -> list[dict]:
    """Every junction question, in the order discovery asks them."""
    ordered = []
    for phase in IMPLEMENTATION_PHASES:
        for group in phase["junction_questions"]:
            for q in PHASE_QUESTIONS[group]:
                if q not in ordered:
                    ordered.append(q)
    return ordered


def default_answers() -> dict[str, Any]:
    """The answer every question takes when accepted with its default."""
    answers: dict[str, Any] = {}
    for q in all_questions():
        if q.get("only_if") and not answers.get(q["only_if"]):
            continue
        answers[q["id"]] = _default_for(q)
    return answers


def run_discovery(
    prefilled: Optional[dict[str, Any]] = None,
    use_defaults: bool = False,
    out: Optional[Console] = None,
) -> DiscoveryResult:
    """Ask the junction questions phase by phase.

    ``prefilled`` answers (CLI flags or an answers file) are used as-is and not
    asked. With ``use_defaults`` every remaining question takes its default, so
    the run is fully non-interactive.
    """
    out = out or console
    prefilled = dict(prefilled or {})
    result = DiscoveryResult()
    # Keys that are not questions (environments, models, …) pass straight through
    known = {q["id"] for q in all_questions()}
    result.answers.update({k: v for k, v in prefilled.items() if k not in known})

    out.print(Panel(
        "[bold cyan]Junction — Agent Graph Bootstrap[/]\n\n"
        "Junction questions are asked at the phase where each decision matters.\n"
        "Each answer shapes the six-agent graph and prevents drift later.",
        title="Discovery Engine",
    ))

    asked = set()
    for phase in IMPLEMENTATION_PHASES:
        questions = [
            q for group in phase["junction_questions"] for q in PHASE_QUESTIONS[group]
            if q["id"] not in asked
        ]
        out.print(f"\n[bold]Phase {phase['phase']}: {phase['name']}[/] [dim]— {phase['description']}[/]")
        for q in questions:
            asked.add(q["id"])
            if q.get("only_if") and not result.answers.get(q["only_if"]):
                continue
            if q["id"] in prefilled:
                answer = normalize_answer(q, prefilled[q["id"]])
                out.print(f"  [green]✓[/] {q['question']} [cyan]{_show(answer)}[/] [dim](preset)[/]")
            elif use_defaults:
                answer = _default_for(q)
                out.print(f"  [green]✓[/] {q['question']} [cyan]{_show(answer)}[/] [dim](default)[/]")
            else:
                answer = _ask_question(q, out)
            result.answers[q["id"]] = answer
        out.print(f"  [green]Gate:[/] {phase['gate']}")

    result.phase_plan = IMPLEMENTATION_PHASES
    return result


def normalize_answer(q: dict, value: Any) -> Any:
    """Coerce a preset answer to the question's type; raise ValueError if invalid."""
    qtype = q["type"]
    if qtype == "confirm":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("y", "yes", "true", "1", "on"):
            return True
        if text in ("n", "no", "false", "0", "off"):
            return False
        raise ValueError(f"{q['id']}: expected yes/no, got {value!r}")
    if qtype == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{q['id']}: expected an integer, got {value!r}") from None
    if qtype == "choice":
        value = str(value)
        if value in q["options"]:
            return value
        for opt in q["options"]:
            if opt.split(" ")[0] == value or opt.lower().startswith(value.lower()):
                return opt
        contains = [opt for opt in q["options"] if value.lower() in opt.lower()]
        if len(contains) == 1:
            return contains[0]
        if q["id"] == "naming_pattern" and "{env}" in value:
            return value
        raise ValueError(f"{q['id']}: {value!r} is not one of {q['options']}")
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return "" if value is None else str(value)


def _default_for(q: dict) -> Any:
    if q["type"] == "choice":
        return q.get("default", q["options"][0])
    if q["type"] == "confirm":
        return bool(q.get("default", False))
    if q["type"] == "int":
        return int(q.get("default", 1))
    return q.get("default", "")


def _show(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value) if value != "" else "—"


def _ask_question(q: dict, out: Console) -> Any:
    """Ask a single question with rationale shown."""
    out.print(f"  [dim italic]{q['rationale']}[/]")
    default = _default_for(q)

    if q["type"] == "confirm":
        return Confirm.ask(f"  {q['question']}", default=default, console=out)
    if q["type"] == "int":
        return IntPrompt.ask(f"  {q['question']}", default=default, console=out)
    if q["type"] == "choice":
        for i, opt in enumerate(q["options"], 1):
            out.print(f"    [{i}] {opt}")
        default_index = q["options"].index(default) + 1 if default in q["options"] else 1
        while True:
            choice = IntPrompt.ask(f"  {q['question']} (number)", default=default_index, console=out)
            if 1 <= choice <= len(q["options"]):
                return q["options"][choice - 1]
            out.print(f"  [red]Pick 1–{len(q['options'])}[/]")
    if q.get("examples"):
        out.print(f"    [dim](e.g., {q['examples']})[/]")
    return Prompt.ask(f"  {q['question']}", default=default, console=out)


# ─── Answers files ────────────────────────────────────────────────────────────


def load_answers(path: str | Path) -> dict[str, Any]:
    """Load discovery answers from a YAML or JSON file and validate them."""
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text) if str(path).endswith(".json") else yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: answers file must be a mapping of question id → answer")
    by_id = {q["id"]: q for q in all_questions()}
    return {k: normalize_answer(by_id[k], v) if k in by_id else v for k, v in data.items()}


# ─── Answers → platform ───────────────────────────────────────────────────────


def build_platform_config(answers: dict[str, Any]) -> PlatformConfig:
    """Build the PlatformConfig for an end-to-end discovery run.

    Environments come from ``answers["environments"]`` when given (full
    records with account ids), otherwise from ``env_names`` with risk tiers
    LOW → MEDIUM → HIGH and placeholder account ids to fill in later.
    """
    from junction.graph_generator import env_values

    cloud = answers.get("cloud", "aws")
    defaults = cloud_defaults(cloud)
    if answers.get("environments"):
        envs = [EnvironmentConfig.from_dict(e) for e in answers["environments"]]
    else:
        names = env_values(answers)
        envs = []
        for i, name in enumerate(names):
            tier = default_risk_tier(i, len(names))
            envs.append(EnvironmentConfig.from_dict({
                "name": name,
                "branch": name,
                "account_id": "000000000000",
                "prefix": name[:2],
                "risk_tier": tier,
                "profile": f"my-{cloud}-{name}",
            }))
    domain = str(answers.get("domain_name") or "platform")
    return PlatformConfig(
        name=answers.get("platform_name") or f"{domain.title()} Platform",
        iac_tool=answers.get("iac_tool", "terraform"),
        cloud=cloud,
        repo_name=answers.get("repo_name") or f"{domain}-infra",
        description=f"Infrastructure-as-Code for the {domain} domain, operated by a six-agent graph",
        agent=answers.get("agent", "copilot"),
        environments=envs,
        compute_type=answers.get("compute_type", defaults["compute_type"]),
        container_registry=defaults["container_registry"],
        cicd_type=answers.get("cicd_type", defaults["cicd_type"]),
        application_name=domain,
        mcp=defaults["mcp"],
    )


# ─── Plan output ──────────────────────────────────────────────────────────────


def print_implementation_plan(result: DiscoveryResult, out: Optional[Console] = None) -> None:
    """Print the phased plan based on discovery answers."""
    out = out or console
    out.print("\n")
    out.print(Panel("[bold]Phased Implementation Plan[/]", title="Output"))

    table = Table(show_header=True)
    table.add_column("Phase", style="bold")
    table.add_column("Name")
    table.add_column("Outputs")
    table.add_column("Gate")

    for phase in result.phase_plan or IMPLEMENTATION_PHASES:
        table.add_row(
            str(phase["phase"]),
            phase["name"],
            ", ".join(phase["outputs"][:3]),
            phase["gate"],
        )

    out.print(table)

    out.print("\n[bold]Key Decisions Resolved:[/]")
    for key, value in result.answers.items():
        if key in ("environments", "models"):
            continue
        out.print(f"  {key}: [cyan]{_show(value)}[/]")


def render_implementation_plan(answers: dict[str, Any], graph: dict) -> str:
    """Markdown version of the phased plan, written into the target repo."""
    decisions = "\n".join(
        f"| `{k}` | {_show(v)} |" for k, v in answers.items() if k not in ("environments", "models")
    ) or "| *(defaults)* | |"
    phases = "\n".join(
        f"| {p['phase']} | **{p['name']}** | {p['description']} | {', '.join(p['outputs'])} | {p['gate']} |"
        for p in IMPLEMENTATION_PHASES
    )
    stores = [label for key, label in (("has_rds", "Aurora"), ("has_msk", "MSK"), ("has_s3", "S3")) if answers.get(key)]
    return f"""# Implementation Plan — {graph["graph"]["description"]}

Generated by `junction`. Each phase ends at a gate; do not start the
next phase until its gate holds. The agent graph is in `agent-graph.yml`.

## Phases

| # | Phase | What happens | Outputs | Gate |
|---|---|---|---|---|
{phases}

## Decisions resolved in discovery

| Question | Answer |
|---|---|
{decisions}

## Scope notes

- Environments: {", ".join(graph["naming"]["env_values"])} (single `{graph["naming"]["variable"]}`)
- Naming: `{graph["naming"]["pattern"]}`
- Store layer: {", ".join(stores) if stores else "none selected"}
- Ticket gate: {"on" if graph["governance"]["jira_gate"]["enabled"] else "off"}
"""
