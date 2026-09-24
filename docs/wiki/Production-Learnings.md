# Production Learnings

`junction/LEARNINGS.py` records the drift-prevention patterns and anti-patterns behind the discovery
questions — cloud- and stack-agnostic by design, and unimported by any other module (reference
material, not runtime logic). The bootstrap uses these learnings to decide **which questions to
ask, when to ask them, and which defaults to hard-wire** — never a specific cloud's resource names.

## Drift-prevention patterns

Each pattern names the right approach, the anti-pattern, the junction where it has to be decided, and what deferring the decision costs.

| Pattern | Do | Don't | Decide in | Cost of deferring |
|---|---|---|---|---|
| **Single env variable** | One `var.environment` value, one source of truth | A second `var.env_label` carrying the same information under a different name | Phase 0, before any IaC file | Every file touches both variables, and validators can't catch leaks |
| **Naming with resource type** | `{domain}-{env}-{resource-type}-{purpose}` | `{domain}-{env}-{purpose}` (missing the resource-type token) | Phase 0, before `locals.tf` | Bulk rename of every resource, and name-based rules break |
| **`for_each` over `count`** | `for_each` over a services map | `count = length(var.services)` | Phase 1, compute orchestration pattern | Removing one service shifts indices and destroys unrelated resources |
| **Secrets vs env vars** | A secrets manager (or identity-based auth) for credentials and external connection strings, env vars for the rest | Deterministic, non-secret values stored in the secrets manager just because they're config | Phase 4, wiring env vars | Secrets need manual rotation forever; identity-based auth doesn't |
| **Knowledge is platform-only** | Curated knowledge holds services, architecture, runbooks | Ticket state or migration progress mixed into knowledge | Phase 1, knowledge structure | Knowledge goes stale and agents read irrelevant state |
| **Ticket gate before work** | Every task links to a ticket before routing (when `jira_required` is on) | The agent starts work and posts partial updates | Phase 1, orchestrator behavior | Untracked changes, and partial updates confuse stakeholders |
| **Module interface validation** | Resolve module/provider outputs before referencing them | Guessing output names from docs | Phase 3, before module calls | `terraform plan` fails on "output not found", with nothing to go on |
| **Error decontamination** | On failure, reload knowledge fresh | Retrying with the context that caused the failure | Phase 1, `agent-graph.yml` error handling | The error cascades and all 3 retries fail the same way |

## Anti-patterns detected in production

| Anti-pattern | Symptom | Prevention in the framework | Learned from |
|---|---|---|---|
| **Legacy naming leak** | Old naming tokens/abbreviations from a prior platform in the new repo | IaC Validator scans for stale/legacy naming patterns before push | V1→V2 migration: dozens of stale references in the first draft |
| **Decorative comments** | Decorative banner/separator blocks in generated IaC files | Governance rule: no decorative blocks | Thousands of tokens of pure decoration the agents had to parse |
| **Full workspace scan** | The agent reads the whole repo instead of the knowledge index | Evals flag it as a costly pattern and require index traversal instead | A full-repo scan where two index reads would have been enough |
| **Premature ticket updates** | "Starting work on…" and partial results posted to the tracker | Report only on confirmed completion with real health/SRE evidence | Several partial updates before the actual deploy confused stakeholders |

## How the learnings reach the code

| Learning | Where it's enforced |
|---|---|
| Naming, single env var | `naming` block and `governance.coding_standards` in `agent-graph.yml`, the iac-validator zone, and the `iac-standards` instructions |
| `for_each` over `count` | Enforced in the generated Terraform templates (`terraform_generator.py`), not by a discovery question — there's no per-repo choice here |
| Secrets strategy | `secret_strategy` and `external_systems` questions |
| Knowledge scope | `governance.knowledge_scope` and the knowledge-curator zone |
| Ticket gate | `jira_required` question, the orchestrator self-edge and `report_only_on_confirmed` |
| Module interfaces | Phase 3 gate |
| Decontamination | `error_handling.decontamination` (always emitted) |
| Token waste | `evals.token_budget` and `evals.costly_patterns` (always emitted) |

Next: [Getting Started](Getting-Started.md)
