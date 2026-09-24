# Production Learnings

`junction/LEARNINGS.py` records what went wrong while scaffolding a real enterprise platform: 15 ECS services, MSK, Aurora and 6 coding agents. The bootstrap uses these learnings to decide **which questions to ask, when to ask them, and which defaults to hard-wire**.

## Drift-prevention patterns

Each pattern names the right approach, the anti-pattern, the junction where it has to be decided, and what deferring the decision costs.

| Pattern | Do | Don't | Decide in | Cost of deferring |
|---|---|---|---|---|
| **Single env variable** | One `var.environment` (`dv/qc/pr`) | Both `var.environment` (`d1/u1/p1`) and `var.env_label` (`dv/qc/pr`) | Phase 0, before any `.tf` | Every file touches both variables, and validators can't catch leaks |
| **Naming with resource type** | `dp-{env}-{domain}-{resource-type}-{purpose}` | `dp-{env}-{domain}-{purpose}` | Phase 0, before `locals.tf` | Bulk rename of every resource, and SG rules break |
| **`for_each` over `count`** | `for_each` over a `var.ecs_services` map | `count = length(var.services)` | Phase 1, ECS orchestration pattern | Removing one service shifts indices and destroys unrelated resources |
| **Secrets vs env vars** | SM for credentials and external connection strings, env vars for the rest | Deterministic values (e.g. MSK bootstrap from IAM) in SM | Phase 4, wiring env vars | SM secrets need manual rotation, and IAM auth doesn't |
| **Knowledge is platform-only** | OKF holds services, architecture, runbooks | Jira story state or migration progress in knowledge | Phase 1, knowledge structure | Knowledge goes stale and agents read irrelevant state |
| **Jira gate before work** | Every task links to a ticket before routing | The agent starts work and posts partial updates | Phase 1, orchestrator behavior | Untracked changes, and partial updates confuse stakeholders |
| **Module interface validation** | Clone modules and check outputs exist before referencing them | Guessing output names from docs | Phase 3, before module calls | `terraform plan` fails on "output not found", with nothing to go on |
| **Error decontamination** | On failure, reload OKF fresh | Retrying with the context that caused the failure | Phase 1, `agent-graph.yml` error handling | The error cascades and all 3 retries fail the same way |

## Anti-patterns detected in production

| Anti-pattern | Symptom | Prevention in the framework | Learned from |
|---|---|---|---|
| **Legacy naming leak** | `dp-com`, `cortex`, `d1`, `u1`, `p1` in the new repo | IaC Validator scans for these patterns before push | V1→V2 migration: 28 stale references in the first draft |
| **Decorative comments** | `═══════` / `───────` blocks in `.tf` | Governance rule: no decorative blocks | 3K tokens of comments the agents had to parse |
| **Full workspace scan** | The agent reads the whole repo instead of the OKF index | Evals flag it as a HIGH costly pattern and require index traversal | A 74K-token scan where 2 index reads would have been enough |
| **Premature Jira posting** | "Starting work on…" and partial results posted to the ticket | Report only on confirmed completion with SRE metrics | 5 partial updates before the actual deploy confused stakeholders |

## How the learnings reach the code

| Learning | Where it's enforced |
|---|---|
| Naming, single env var | `naming` block and `governance.coding_standards` in `agent-graph.yml`, the iac-validator zone, and the `iac-standards` instructions |
| `for_each`, domain maps | `service_count` and `shared_services` discovery questions |
| Secrets strategy | `secret_strategy`, `external_systems` and `nr_license_strategy` questions |
| Knowledge scope | `governance.knowledge_scope` and the knowledge-curator zone |
| Jira gate | `jira_required` question, the orchestrator self-edge and `report_only_on_confirmed` |
| Module interfaces | Phase 3 gate |
| Decontamination | `error_handling.decontamination` (always emitted) |
| Token waste | `evals.token_budget` and `evals.costly_patterns` (always emitted) |

Next: [Getting Started](Getting-Started.md)
