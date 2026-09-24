# Roadmap and Open Items

## Milestones

| Milestone | Status |
|---|---|
| v0.1: Bootstrap scaffolding (agents, skills, MCP interface, core adapters) | Done |
| v0.2: Bootstrap CLI + SDK (`junction`, multi-agent adapters) | Done |
| v0.3: End-to-end discovery CLI, six agents for every adapter, JSON Schema validation, configurable model tiers, self-contained wheel | Done |
| v0.4: Concrete MCP servers (CloudWatch, Jira, New Relic) | Planned |
| v0.5: GCP and Azure adapter packs | Planned |
| v0.6: Web UI for `platform.yml` configuration | Future |

## Resolved in v0.3

| # | Item | Resolution |
|---|---|---|
| 1 | Discovery wasn't in the CLI | `--discover`, `--defaults`, `--answers FILE` run discovery → graph → scaffold end to end, and write a replayable `discovery-answers.yml` |
| 2 | 6 graph nodes but 2 agent files | Every adapter renders all six agents (Copilot handoffs, Claude Code subagents, Cursor/Continue rules, `.agents/`), including the migration executor |
| 3 | Phase 1 outputs didn't match what shipped | 6 agents and 8 skills (new: `knowledge-curation`, `v1-v2-migration`). The phase now says 3 instructions |
| 4 | No schema validation | JSON Schema v2.0 plus safety invariants, enforced on generate and write, and by `--validate-graph` |
| 5 | Shared vs dedicated MSK question missing | `msk_cluster_shared`, asked only when `has_msk` is yes |
| 6 | Hard-coded old model names | Tier defaults `claude-opus-5` / `claude-sonnet-5` in `junction/models.py`, overridable with `--model` or answers `models:` |
| 8 | Escaped em dash in YAML | `allow_unicode=True`, plus no `\u` escapes in agent frontmatter |
| — | pip install shipped no skills | Framework content is packaged in `junction/framework/` and kept in sync by `scripts/sync_framework.py` and a test |

## Resolved: real Terraform generation (GCP)

| # | Item | Resolution |
|---|---|---|
| 7 | Store/secret answers didn't generate Terraform | `junction/terraform_generator.py` combines `PlatformConfig` + the validated agent graph + discovery answers into real `store-*.tf` / `platform-*.tf` / `service-<name>.tf` files for `cloud: gcp`, wired into `scaffold.py`'s `collect_files()` so every `junction --discover --cloud gcp` run writes them. Services scale up via Terraform's native `for_each` over a `var.services` map — a new `--services api,worker,...` CLI flag lets a user request more than the single default service. Verified end to end through the actual packaged CLI (not just the generator function): built the wheel, installed it fresh, ran `junction --discover --defaults --cloud gcp --domain orders --services api,worker --target <dir> --yes`, and confirmed `infra/service-api.tf` and `infra/service-worker.tf` both exist with independent config in the generated `tfvars/dv.tfvars`. `terraform init`, `fmt -check`, and `validate` all pass with 0 errors on that output; `terraform plan` stops exactly at "could not find default credentials" — the expected boundary once real cloud auth would be needed. 20 unit tests (`tests/test_terraform_generator.py`) additionally check governance rules `validate` can't catch on its own: `allUsers` is gated per-service by `public = true` and appears exactly once, IAM roles are scoped to specific resources (never `roles/editor`/`roles/owner`), Firestore is named (never `(default)`), and secrets use `ignore_changes = [secret_data]`. AWS/Azure are unsupported by design for now — `generate_terraform()` returns `None` (not `{}`) for other clouds, so the gap is visible rather than silently empty. |
| 9 | AWS/ECS-centric questions | Service-count, MSK and KMS questions assume ECS on AWS | Pick question sets per `compute.type` and cloud adapter |
| 10 | MCP servers are contracts only | `.vscode/mcp.json` points at `server.py` files that v0.4 will provide | Ship reference servers |
| 11 | `env_count` isn't cross-checked against `env_names` | `env_names` wins | Warn on mismatch |

## Resolved by the GCP end-to-end test

Real-repo test: an "Order Processing Service" scaffolded end to end for `cloud: gcp`, which builds
real Terraform for it (Cloud SQL, Pub/Sub, GCS, GKE Autopilot, Secret Manager, Cloud KMS), validated
with `terraform init && validate` against the real `hashicorp/google` provider schema — 0 errors.
Reproduce it locally with `./scripts/local-e2e-check.sh -d orders -p <your-gcp-project>`.

| # | Item | Resolution |
|---|---|---|
| 12 | `platform.yml.j2` hardcoded the AWS ECR registry URI regardless of `container_registry` | `REGISTRY_URI_PATTERNS` in `scaffold.py`, keyed by registry type |
| 13 | `cicd.log_group` was always the AWS CodeBuild path, even for `github_actions`/etc. | `CICD_LOG_GROUP_PATTERNS`, with a plain-language fallback for CI systems with no log-group concept |
| 14 | `observability` group/index patterns hardcoded `ecs/`/`ecs-` regardless of compute type | Dropped the ECS-specific prefix; the pattern is now compute-agnostic |
| 15 | `platform.yml`'s `naming.pattern` could disagree with `agent-graph.yml`'s | `platform.yml.j2` now takes `naming_pattern` from the same validated graph |
| 16 | `platform.yml`'s own header showed a stale hardcoded version | Renders `junction.__version__` |

## Confirmed still open, with evidence

| # | Item | Evidence |
|---|---|---|
| 9 (detail) | Instructions/skills are AWS-specific static text, not cloud-templated | `compute-patterns.instructions.md` names `aws_iam_role_policy_attachment` and "Secrets Manager resources" verbatim even when `cloud: gcp` |
| — | No serverless GCP compute option | `COMPUTE_TYPES` has `gke` but not `cloud_run`; the GCP test used GKE Autopilot |
| — | Naming pattern doesn't account for globally-unique bucket names | GCS (unlike S3) needs a project-id suffix; the CPE pattern alone collides across projects |
| — | `kms_strategy` and `account_id` are AWS-worded | "cross-account key" / "AWS managed keys" have no GCP equivalent; `account_id` means "project id" on GCP |

## Contributing

New agent adapters, MCP server implementations, and new domain skills are the most useful contributions. See [CONTRIBUTING.md](../../CONTRIBUTING.md).
