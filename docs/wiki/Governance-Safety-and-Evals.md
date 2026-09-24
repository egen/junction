# Governance, Safety and Evals

Autonomy in this framework is something you **configure**, not something the agent assumes. This page collects every control that limits what the agent graph can do, and how cost and quality are measured.

## Risk tiers (per environment)

Set in `.github/config/platform.yml` and enforced by the agents and the `prod-guardrails` instructions:

| Tier | Typical env | Agent behavior |
|---|---|---|
| **LOW** | dev / `dv` | Autonomous: build, push, auto-fix up to 3×, roll back |
| **MEDIUM** | staging / `qc` | Needs promotion approval before changes land |
| **HIGH** | prod / `pr` | Every change needs explicit human confirmation. Never auto-approved |

## Risk gates (per agent node)

Separately from the environment, each node in `agent-graph.yml` has its own gate:

| Node | Gate | Meaning |
|---|---|---|
| orchestrator, iac-validator, sre-observer | none | Read, route or check only. None of them can change infrastructure |
| knowledge-curator | LOW | Edits docs only |
| terraform-builder | MEDIUM | Writes IaC, and every write goes through the validator |
| migration-executor | HIGH | Stateful cutovers. No retries, pauses at a human gate |

The *effective* autonomy of an action is the stricter of the two gates. A LOW-risk env can't make a HIGH-risk node autonomous.

## Boot protocol

Before any action, the IaC agent must run the boot protocol:

1. **Orient:** current branch, dirty state, stashes.
2. **Confirm:** map branch → environment → risk tier from `platform.yml`, then **wait for user confirmation**.
3. **Load context:** architecture reference, the env's tfvars, recent build gotchas.
4. **Pre-flight:** check memories for recent failures in the target env.

## Jira gate

With `jira_required: true`:

- the orchestrator's first edge is a self-loop gated on `jira_ticket_linked`, so **no routing happens without a ticket**
- `governance.jira_gate.report_only_on_confirmed: true`, so the tracker is updated only on **confirmed completion with SRE metrics**, and never with "starting work…" or partial progress

## Error decontamination

The biggest driver of retry cascades is reusing a poisoned context. The graph always includes:

| Rule | Value |
|---|---|
| On node failure | Snapshot context, isolate it, **do not carry it forward** |
| On retry | Reload OKF knowledge fresh and never reuse stale context |
| Max error chain | 3 |
| After max | Hard reset: discard in-flight work, escalate cleanly |

## Failure policy

| Scope | Retry | Backoff | Fallback |
|---|---|---|---|
| Default | 3 (0 if `auto_fix_dv` is off) | exponential | escalate to human |
| terraform-builder | 3 (1 if off) | — | — |
| sre-observer | 1 | — | escalate with raw logs |
| migration-executor | **0** | — | pause + human gate |

## Evals: token budgets and costly patterns

Every generated graph has an `evals` block. It measures cost as well as correctness.

| Budget | Tokens |
|---|---|
| Per node warning | 50,000 |
| Per node hard limit | 100,000 |
| Per work graph hard limit | 500,000 |

| Costly pattern | Severity |
|---|---|
| Full workspace scan instead of OKF navigation | HIGH |
| Generating code without loading knowledge | HIGH |
| Redundant MCP calls within 5 minutes | MEDIUM |

## Knowledge scope (OKF)

The knowledge base holds **platform-durable facts only**: `services`, `architecture`, `runbooks`, `contracts`, `policies`. Story state, ticket progress and migration status don't belong there. Once they go stale, agents spend tokens reading irrelevant state.

## Terraform coding standards (generated)

- No decorative comment blocks (`═══`, `───`). They cost tokens and carry no information
- A single `var.environment`, with values taken from `env_names`
- Naming follows the locked `naming_pattern`
- Modules use pinned refs only
- Secrets use `ignore_changes = [secret_string]`

## Least-privilege agents

Every scaffolded repo gets six agents with tool access derived from the graph:

| Agent | Can edit? | Terminal? | Notes |
|---|---|---|---|
| orchestrator | No | No | Routes only. In Claude Code its `Agent(...)` allowlist names the five specialists |
| iac-validator | **No** | Yes (validate/lint) | Claude Code: `disallowedTools: Edit, Write, NotebookEdit` |
| terraform-builder | Yes | Yes | MEDIUM gate, and every change goes to the validator |
| sre-observer | **No** | Yes (read queries) | MCP: cloud-logs, observability |
| knowledge-curator | Docs only | No | LOW gate |
| migration-executor | Yes | Yes | HIGH gate, `retry: 0`, human gate on failure |

The schema invariants guarantee that the validator and observer never gain edit tools, and that the migration executor can't be downgraded, even if someone hand-edits `agent-graph.yml`.

Next: [Production Learnings](Production-Learnings.md)
