"""
agent_specs.py — The six graph agents as renderable specs.

Each adapter turns these specs into its own format (Copilot ``.agent.md``,
Claude Code subagents, Cursor rules, Continue rules, plain markdown). The
graph (agent-graph.yml) is the source of truth for zones, tools, risk gates,
model tiers and edges; this module adds the operating instructions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from junction.config_builder import PlatformConfig
from junction.graph_generator import NODE_ORDER


@dataclass
class AgentSpec:
    name: str
    title: str
    role: str
    summary: str
    tier: str
    model: str
    risk_gate: str
    zone: list[str]
    tools: list[str]
    skills: list[str]
    responsibilities: list[str]
    never: list[str]
    inbound: list[dict] = field(default_factory=list)
    outbound: list[dict] = field(default_factory=list)

    @property
    def read_only(self) -> bool:
        return not any(t in ("edit", "write") for t in self.tools)

    @property
    def can_run_terminal(self) -> bool:
        return "terminal" in self.tools

    @property
    def mcp_servers(self) -> list[str]:
        return sorted({MCP_TOOL_TO_SERVER.get(t, t[4:]) for t in self.tools if t.startswith("mcp:")})

    @property
    def description(self) -> str:
        return f"{self.title}: {self.summary}"


# Graph MCP tool names → the MCP server names scaffolded into .vscode/mcp.json
MCP_TOOL_TO_SERVER = {
    "mcp:aws-logs": "cloud-logs",
    "mcp:newrelic": "observability",
}

_CONTENT: dict[str, dict] = {
    "orchestrator": {
        "title": "Orchestrator",
        "summary": "entry point for every request. Runs the boot protocol, enforces the ticket gate, loads knowledge and routes work to the right specialist.",
        "responsibilities": [
            "Run the boot protocol: current branch, dirty state, branch → environment → risk tier, then confirm with the user",
            "Enforce the ticket gate before routing when it is enabled",
            "Load only the OKF knowledge the task needs (index first, never a full workspace scan)",
            "Classify intent and hand off to exactly one specialist per step, using the routing table",
            "For triage, fan out research in parallel, then deduplicate and rank findings before acting",
            "Report outcomes to the issue tracker only after confirmed completion with SRE metrics",
        ],
        "never": [
            "Edit IaC files or run deploy commands itself",
            "Route work without a linked ticket when the ticket gate is enabled",
            "Post partial progress or 'starting work' updates to the issue tracker",
        ],
    },
    "iac-validator": {
        "title": "IaC Validator",
        "summary": "correctness gate. Every change from the Terraform Builder must pass naming, env-leak and reference-integrity checks before it can be pushed.",
        "responsibilities": [
            "Check every resource name against the naming pattern and the single environment variable",
            "Detect env leaks: account IDs, endpoints, ARNs or legacy prefixes from another environment",
            "Verify every module output and variable reference exists (clone modules rather than guess)",
            "Reject decorative comment blocks, unpinned module refs and secrets without ignore_changes",
            "Return a verdict: PASS, or a list of violations each marked auto_fixable true/false",
        ],
        "never": [
            "Modify files: report violations and let the Terraform Builder fix them",
            "Pass a change that failed any check",
        ],
    },
    "terraform-builder": {
        "title": "Terraform Builder",
        "summary": "IaC code generation. Writes Terraform files, module calls and variable wiring, and always hands the result to the IaC Validator.",
        "responsibilities": [
            "Load the relevant knowledge and module interfaces before writing any code",
            "Use for_each over service maps, never count, and one var.environment",
            "Follow the naming pattern and pinned module refs",
            "Hand every change to the IaC Validator and fix auto-fixable violations",
            "After a validated push, run the post-push monitor and the self-healing deploy loop",
        ],
        "never": [
            "Skip the IaC Validator or push a change it has not passed",
            "Copy env-specific values between environments",
            "Apply to a MEDIUM or HIGH risk environment without the required approval",
        ],
    },
    "sre-observer": {
        "title": "SRE Observer",
        "summary": "read-only post-deploy health and triage. Queries logs, metrics and alerts through MCP servers and recommends fixes without executing them.",
        "responsibilities": [
            "Run health checks against the service registry's health contracts",
            "Fetch logs and metrics in parallel for triage, and correlate alerts to root causes",
            "Give the migration executor its health gate verdict after each phase",
            "Hand resolved incidents to the Knowledge Curator as a runbook update",
            "Escalate with raw logs when a diagnosis is not confident",
        ],
        "never": [
            "Modify infrastructure, code, databases or deployments",
            "Restart tasks or pods, or run apply/destroy",
            "Push git changes",
        ],
    },
    "knowledge-curator": {
        "title": "Knowledge Curator",
        "summary": "maintains the OKF knowledge graph (services, architecture, runbooks, contracts, policies) so every other agent navigates an index instead of scanning the repo.",
        "responsibilities": [
            "Turn resolved incidents into runbooks and cross-links",
            "Keep the service registry, architecture notes and contracts current",
            "Run stale checks and flag knowledge that contradicts the code",
            "Keep the knowledge index small enough to navigate in two reads",
        ],
        "never": [
            "Store ticket state, story progress or migration status in knowledge",
            "Edit IaC files",
        ],
    },
    "migration-executor": {
        "title": "Migration Executor",
        "summary": "runs V1 → V2 migrations as a state machine with phase gates and rollback. HIGH risk: no automatic retries, pauses at a human gate on any failure.",
        "responsibilities": [
            "Load the migration state and confirm the current phase before any action",
            "Extract env vars, secrets and naming from V1 and prove parity before cutover",
            "Advance one phase at a time; each phase needs the SRE Observer's health gate",
            "Keep a tested rollback path for every phase",
            "Pause and ask a human on any failure, then record the state",
        ],
        "never": [
            "Retry a failed phase automatically",
            "Skip a phase gate or cut over without parity and a health gate",
            "Delete V1 resources before V2 has passed its health gate",
        ],
    },
}


def build_agent_specs(graph: dict) -> list[AgentSpec]:
    """Return the six agent specs, in graph order, from a validated graph."""
    models = graph.get("models", {})
    specs = []
    for name in NODE_ORDER:
        node = graph["nodes"][name]
        content = _CONTENT[name]
        specs.append(AgentSpec(
            name=name,
            title=content["title"],
            role=node["role"],
            summary=content["summary"],
            tier=node["model"],
            model=models.get(node["model"], ""),
            risk_gate=node["risk_gate"],
            zone=list(node["zone"]),
            tools=list(node["tools"]),
            skills=list(node.get("skills", [])),
            responsibilities=content["responsibilities"],
            never=content["never"],
            inbound=[e for e in graph["edges"] if e["to"] == name and e["from"] != name],
            outbound=[e for e in graph["edges"] if e["from"] == name],
        ))
    return specs


def agent_title(name: str) -> str:
    return _CONTENT[name]["title"]


def _title(name: str) -> str:
    return _CONTENT[name]["title"]


def _edge_line(edge: dict, direction: str) -> str:
    other = edge["to"] if direction == "out" else edge["from"]
    if other == edge["from"] == edge["to"]:
        return f"- **Self-gate** on `{edge['trigger']}`: requires `{edge.get('gate', '')}`"
    arrow = "→" if direction == "out" else "←"
    extra = []
    if edge.get("gate"):
        extra.append(f"gate: {edge['gate']}")
    if edge.get("max_cycles"):
        extra.append(f"max {edge['max_cycles']} cycles")
    suffix = f" ({', '.join(extra)})" if extra else ""
    return f"- {arrow} **{_title(other)}** (`{other}`) when `{edge['trigger']}`{suffix}"


def render_agent_body(spec: AgentSpec, platform: PlatformConfig, graph: dict) -> str:
    """Render the tool-agnostic markdown body shared by every adapter."""
    env_rows = "\n".join(
        f"| {e.name} | `{e.branch}` | `{e.risk_tier}` |" for e in platform.environments
    ) or "| *(see platform.yml)* | | |"
    naming = graph["naming"]
    policy = graph["failure_policy"]["per_node"].get(spec.name, graph["failure_policy"]["default"])
    retry = policy.get("retry", graph["failure_policy"]["default"].get("retry", 0))
    fallback = policy.get("fallback", graph["failure_policy"]["default"].get("fallback", "escalate_to_human"))
    access = "Read-only" if spec.read_only else "Read-write"
    skills = "\n".join(f"- `{s}`: `.github/skills/{_skill_dir(s)}/SKILL.md`" for s in spec.skills) or "- *(none)*"
    handoffs = "\n".join(
        [_edge_line(e, "out") for e in spec.outbound] + [_edge_line(e, "in") for e in spec.inbound]
    ) or "- *(none)*"
    mcp = ", ".join(f"`{s}`" for s in spec.mcp_servers) or "none"
    decon = graph["error_handling"]["decontamination"]
    budget = graph["evals"]["token_budget"]

    return f"""# {spec.title} — {platform.name}

> **{spec.role}** · {access} · Risk gate: `{spec.risk_gate}` · Model tier: `{spec.tier}` (`{spec.model}`)
> One of six agents in `.github/config/agent-graph.yml`. Zone: {", ".join(f"`{z}`" for z in spec.zone)}.

{spec.summary[0].upper() + spec.summary[1:]}

## Responsibilities

{chr(10).join(f"{i}. {r}" for i, r in enumerate(spec.responsibilities, 1))}

## Never

{chr(10).join(f"- {n}" for n in spec.never)}

## Hand-offs (graph edges)

{handoffs}

## Skills

{skills}

## Environments

| Env | Branch | Risk tier |
|-----|--------|-----------|
{env_rows}

Naming: `{naming["pattern"]}` with a single `{naming["variable"]}` ({", ".join(naming["env_values"])}).
MCP servers: {mcp}.

## Failure policy

- Retries: **{retry}**, then **{fallback}**
- On failure: {decon["on_node_failure"]}. On retry: {decon["on_retry"]}.
- Token budget: warn at {budget["per_node_warn"]:,}, stop at {budget["per_node_hard"]:,} tokens for this agent.
"""


def _skill_dir(skill: str) -> str:
    triage = {"iac-triage", "sre-log-fetching"}
    return f"_triage/{skill}" if skill in triage else f"_core/{skill}"
