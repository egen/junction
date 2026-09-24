# Discovery Engine

`junction/discovery.py` is the interactive front door of the bootstrap. It doesn't ask everything up front. It asks **junction questions**, each at the phase where its answer first changes what gets generated. Every question is shown with its rationale, so the person answering knows what it controls.

> **Why junctions?** A decision made too late turns into a bulk rename or a rewrite. A decision made too early is a guess. Asking at the junction avoids both, and it stops the same question from coming up again later.

## How it runs

From the CLI, end to end (answers → graph → six agent files):

```bash
junction --discover --target ./repo                        # interactive
junction --discover --defaults --domain payments --target ./repo --yes
junction --answers discovery-answers.yml --target ./repo   # preset answers; the rest are asked
junction --discover-with-agent --target ./repo             # your local agent proposes answers first
```

From Python:

```python
from junction import run_discovery, print_implementation_plan

result = run_discovery()           # interactive, rich-powered prompts
result = run_discovery(prefilled={"agent": "cursor"}, use_defaults=True)  # no prompts
print_implementation_plan(result)  # phase table + "Key Decisions Resolved"
result.answers                     # dict of question id → answer
```

`run_discovery()` walks the [implementation phases](Implementation-Phases.md) in order. For each phase it asks the question groups that phase lists, prints any follow-up it will need later, and then prints the phase's gate. The result is a `DiscoveryResult` with `answers` and `phase_plan`. The answers are what [`generate_agent_graph`](Agent-Graph.md#generating-one) takes.

Question types: `confirm` (yes/no), `int`, `choice` (numbered options) and `text` (with examples).

## The 17 junction questions

Every question below is actually consumed by `graph_generator.py` or `terraform_generator.py` —
nothing here just decorates the run. Earlier versions asked 8 more (environment *count* alongside
environment *names*, an ECS-specific service count, a Docker-image-sharing question, AWS-only
naming/module-registry questions, a shared-vs-dedicated MSK follow-up, a KMS strategy question, and
a New-Relic-only license question) that never fed any generator and only made sense on one cloud.
They were dropped: fewer questions, faster to adopt, no single-cloud assumptions baked in.

### Phase 0 · `profile`: what are you building?

| Id | Question | Why it matters |
|---|---|---|
| `use_case_profile` | What are you building? (web/API service, data pipeline/ETL, event-driven microservices, ML/AI platform, internal platform, or not sure yet) | Presets the *defaults* for the `data_stores` and `secrets` questions below (see `USE_CASE_PROFILES` in `discovery.py`) — every question is still asked and still overridable, but accepting the suggested default for the rest of the run now takes almost no thought. "Not sure yet / custom" applies no overrides. |

### Phase 0 · `platform`: which toolchain?

| Id | Question | Why it matters |
|---|---|---|
| `agent` | Which coding agent will run the agent graph? | Decides the agent file format (Copilot, Claude Code, Cursor, Continue, `AGENTS.md`). |
| `cloud` | Which cloud provider? | Sets compute, registry, CI/CD and MCP backend defaults. |
| `iac_tool` | Which IaC tool? | The builder and validator target this tool. |

### Phase 0 · `discovery`: what are we building?

| Id | Question | Why it matters |
|---|---|---|
| `existing_repo` | Do you have an existing IaC repo you're migrating FROM? | If migrating, env vars, secrets and naming patterns are extracted from V1. |
| `domain_name` | What business domain does this repo serve? (e.g. person, health, payments) | Becomes part of every generated resource name. |
| `env_names` | Environment names, lowest → highest risk (default `dv,qc,pr`) | Maps to branches, tfvars files and cloud accounts/projects. Environment *count* and risk tiers (LOW→HIGH) are both derived from this one list — there's no separate count to keep in sync. |

### Phase 0 · `naming`: lock it before any IaC file exists

| Id | Question | Why it matters |
|---|---|---|
| `naming_pattern` | What naming standard should generated resource names follow? (`{domain}-{env}-{resource-type}-{purpose}` recommended / simple `{app}-{env}-{service}` / custom) | The IaC Validator enforces it, so it has to be decided up front. Cloud-agnostic — no assumed provider or resource-type vocabulary. |

### Phase 1 · `agent_graph`: how autonomous is the org?

| Id | Question | Effect on `agent-graph.yml` |
|---|---|---|
| `jira_required` | Must every task link to a Jira/Linear ticket? | Adds the `orchestrator → orchestrator` `jira_ticket_linked` gate and sets `governance.jira_gate.enabled`. |
| `auto_fix_dv` | Auto-fix failures in dev (up to 3 retries)? | Default retry 3 (off: 0); builder retry 3 (off: 1). |
| `parallel_research` | Fetch logs and metrics in parallel before diagnosis? | Emits the `parallel.fan_out_in` pattern. |
| `model_optimization` | Use a cheaper model for read-only agents? | Emits the `models` tier map. |

### Phases 2 and 4 · `data_stores`: which stateful layers exist?

| Id | Question | What it generates |
|---|---|---|
| `has_rds` | Does this domain need a managed relational database (RDS/Aurora, Cloud SQL, Azure Database)? | A store-layer file with identity-based auth and network rules. |
| `has_msk` | Does this domain need a streaming/event backbone (MSK/Kafka, Pub/Sub, Event Hubs)? | A store-layer file with topics/subscriptions, IAM and network rules. |
| `has_s3` | Does this domain need object storage (S3, GCS, Blob Storage)? | A store-layer file with encryption and lifecycle rules. |

Today `terraform_generator.py` only implements the GCP shape of these three (Firestore/Pub-Sub/GCS
+ Secret Manager) — see [Roadmap and Open Items](Roadmap-and-Open-Items.md). The questions
themselves aren't AWS- or GCP-specific; the generator catching up on AWS/Azure is the open item.

### Phases 2 and 4 · `secrets`: credentials, only where needed

| Id | Question | Why it matters |
|---|---|---|
| `secret_strategy` | How do services get DB credentials? (identity-based auth / secrets manager / both) | Identity-based auth means no stored secrets for internal services, and a secrets manager is kept for external dependencies. |
| `external_systems` | Which external systems need credentials? | Each one gets exactly one secret bundle with `ignore_changes`. |

## The questions that prevent most rework

`LEARNINGS.py` names the junction questions that, from production experience, eliminate most
post-scaffold fixes — see `HIGH_VALUE_JUNCTION_QUESTIONS` there. All of them are asked above; none
require a specific cloud, compute type, or observability vendor to be useful.

## Answers files and replay

Every discovery run writes `.github/config/discovery-answers.yml` into the target. Pass it back with `--answers` to reproduce the same graph, for example in CI or for another coding agent (`--agent` overrides the saved value). Values are type-checked: `yes`/`no` for confirms, integers, and a unique prefix or substring of a choice (`naming_pattern: recommended`). A bad value stops the run with a clear error. See [`examples/discovery-answers.example.yml`](../../examples/discovery-answers.example.yml).

## Letting your local agent answer for you

`--discover-with-agent` (implies `--discover`) shells out to the `claude` CLI in headless mode
(`claude -p`), with only `Read`/`Glob`/`Grep` — no `Write`/`Edit`/`Bash` — so it can inspect the
`--target` repo (package manifests, Dockerfiles, existing IaC, README, CI config, git remote) but
never touches the filesystem itself. It returns its answers as one fenced YAML block; `junction`
(`junction/agent_discovery.py`) parses and type-checks each field against the real question
catalog, then merges the result in exactly like an `--answers` file — explicit flags (`--agent`,
`--domain`, …) and an `--answers` file both still win over anything the agent proposed for the same
field. Unanswered questions are still asked normally (or defaulted, with `--defaults`); the printed
decision log tags each one `(agent)` so it's clear which came from inspection versus a preset or a
default.

```bash
junction --discover-with-agent --agent claude-code --target ./existing-repo
```

This is independent of `--agent` (which output format to scaffold) — it always drives `claude`
specifically, since it's the only coding-agent CLI with a non-interactive mode today. If `claude`
isn't installed, or the repo doesn't parse into a usable answer set, it fails clearly and discovery
falls back to asking every question normally rather than blocking the run.

## Relationship to the setup wizard

There are two interactive flows in `junction/`:

| Flow | Module | Produces | Wired into CLI? |
|---|---|---|---|
| Setup wizard | `config_builder.interactive_build()` | `platform.yml` (agent, cloud, IaC tool, envs, compute, CI/CD, MCP backends) | Yes: `junction` |
| Discovery engine | `discovery.run_discovery()` | answers → `agent-graph.yml`, `implementation-plan.md`, `discovery-answers.yml`, and the platform config | Yes: `--discover`, `--defaults`, `--answers` |

Next: [Implementation Phases](Implementation-Phases.md)
