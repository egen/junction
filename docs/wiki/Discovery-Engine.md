# Discovery Engine

`junction/discovery.py` is the interactive front door of the bootstrap. It doesn't ask everything up front. It asks **junction questions**, each at the phase where its answer first changes what gets generated. Every question is shown with its rationale, so the person answering knows what it controls.

> **Why junctions?** A decision made too late turns into a bulk rename or a rewrite. A decision made too early is a guess. Asking at the junction avoids both, and it stops the same question from coming up again later.

## How it runs

From the CLI, end to end (answers → graph → six agent files):

```bash
junction --discover --target ./repo                        # interactive
junction --discover --defaults --domain payments --target ./repo --yes
junction --answers discovery-answers.yml --target ./repo   # preset answers; the rest are asked
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

## The 24 junction questions

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
| `domain_name` | What business domain does this repo serve? (e.g. person, health, payments) | Becomes part of every resource name: `dp-{env}-{domain}-*`. |
| `env_count` | How many environments do you deploy to? (default 3) | Drives branch strategy, risk tiers and the promotion chain. |
| `env_names` | Environment names, lowest → highest risk (default `dv,qc,pr`) | Maps to branches, tfvars files and cloud profiles. |
| `service_count` | How many ECS services will this repo manage? (default 5) | More than 3 means the `for_each` pattern instead of individual files. |
| `shared_services` | Do multiple services share one Docker image? | If yes, a `for_each` domain map (for example 8 services in 1 file). |

### Phase 0 · `naming`: lock it before any `.tf` exists

| Id | Question | Why it matters |
|---|---|---|
| `naming_pattern` | Which naming standard does your org use? (CPE `dp-{env}-{domain}-{resource-type}-{purpose}` / simple `{app}-{env}-{service}` / custom) | The IaC Validator enforces it, so it has to be decided up front. |
| `resource_type_tokens` | Do resource names include the AWS service type (ecs, rds, msk, lambda)? | Required by the CPE standard, and it affects the `locals.tf` prefixes. |
| `module_registry` | Where are Terraform modules hosted? (CodeCommit / Terraform Registry / GitHub private / local) | The module source pattern is enforced across all `.tf` files. |

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
| `has_rds` | Does this domain use RDS/Aurora PostgreSQL? | `store-aurora.tf` with IAM auth + SG rules. |
| `has_msk` | Does this domain use MSK/Kafka? | `store-msk.tf` with topics, IAM and SG rules. |
| `msk_cluster_shared` | Are the MSK topics on a shared cluster? *(asked only if `has_msk`)* | Shared clusters need a topic prefix and cross-account IAM. |
| `has_s3` | Does this domain use S3? | `store-s3.tf` with KMS + lifecycle. |
| `kms_strategy` | KMS strategy? (cross-account / same-account / AWS-managed) | A cross-account key needs a key policy with service principals. |

### Phases 2 and 4 · `secrets`: credentials, only where needed

| Id | Question | Why it matters |
|---|---|---|
| `secret_strategy` | How do services get DB credentials? (IAM auth / Secrets Manager / both) | IAM auth means no stored secrets for internal services, and SM is kept for external dependencies. |
| `external_systems` | Which external systems need credentials? | Each one gets exactly one SM secret bundle with `ignore_changes`. |
| `nr_license_strategy` | How is the New Relic license key provided? | A cross-account secret uses a hard-coded ARN, and a per-env secret uses a variable. |

## The seven questions that prevent most rework

`LEARNINGS.py` names seven questions that, from production experience, eliminate about **80% of post-scaffold fixes**:

1. Is there an existing repo you're migrating from? *(triggers env-var extraction)*
2. Do multiple services share one Docker image? *(triggers the domain-map pattern)*
3. Do services authenticate to the DB with IAM or a password? *(avoids Secrets Manager bloat)*
4. Are MSK topics on a shared or a dedicated cluster? *(sets the topic prefix)*
5. Must every task link to a Jira ticket? *(sets the orchestrator's gate)*
6. Which naming standard does your org enforce? *(must be locked before ANY `.tf` file)*
7. Which external systems need credentials? *(only those get SM secrets)*

All seven are asked. Question 4 is `msk_cluster_shared`, a follow-up that is asked only when `has_msk` is yes.

## Answers files and replay

Every discovery run writes `.github/config/discovery-answers.yml` into the target. Pass it back with `--answers` to reproduce the same graph, for example in CI or for another coding agent (`--agent` overrides the saved value). Values are type-checked: `yes`/`no` for confirms, integers, and a unique prefix or substring of a choice (`naming_pattern: CPE`). A bad value stops the run with a clear error. See [`examples/discovery-answers.example.yml`](../../examples/discovery-answers.example.yml).

## Relationship to the setup wizard

There are two interactive flows in `junction/`:

| Flow | Module | Produces | Wired into CLI? |
|---|---|---|---|
| Setup wizard | `config_builder.interactive_build()` | `platform.yml` (agent, cloud, IaC tool, envs, compute, CI/CD, MCP backends) | Yes: `junction` |
| Discovery engine | `discovery.run_discovery()` | answers → `agent-graph.yml`, `implementation-plan.md`, `discovery-answers.yml`, and the platform config | Yes: `--discover`, `--defaults`, `--answers` |

Next: [Implementation Phases](Implementation-Phases.md)
