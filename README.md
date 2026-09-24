# Junction — Bootstrap CLI

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Topics](https://img.shields.io/badge/topics-coding--agent%20%7C%20iac%20%7C%20sre%20%7C%20platform--engineering-blue)](#)

**Junction is where your infrastructure repo and your coding agent meet.** One command turns any
repo into an **agent-operated repo**: answer a short set of *junction questions* (or accept the
defaults) and get a **schema-validated six-agent graph** scaffolded for your coding agent of
choice — **GitHub Copilot**, **Claude Code**, **Cursor**, **Continue.dev**, or anything that reads
`AGENTS.md`.

```
discovery answers ──► agent-graph.yml (validated) ──► 6 agent files + skills + guardrails + knowledge + MCP wiring
```

Instead of dropping one general-purpose assistant into your infra repo and hoping it stays in its
lane, Junction gives you a **graph of specialists** — each with its own zone, tools, model and risk
gate — plus the guardrails, knowledge base and phased build plan that keep them from drifting.

| Agent | Role | Access | Risk gate | Default model |
|---|---|---|---|---|
| `orchestrator` | Dispatch + context assembly | read-only | none | `claude-opus-5` (planner) |
| `iac-validator` | Correctness gate | read-only | none | `claude-sonnet-5` (validator) |
| `terraform-builder` | IaC code generation | read-write | MEDIUM | `claude-opus-5` (builder) |
| `sre-observer` | Post-deploy health + triage | read-only | none | `claude-sonnet-5` (observer) |
| `knowledge-curator` | OKF knowledge maintenance | read-write (docs) | LOW | `claude-sonnet-5` (curator) |
| `migration-executor` | V1 → V2 state machine | read-write | HIGH | `claude-opus-5` (planner) |

New to the idea? Start with the [Graph Agent Engineering Wiki](docs/wiki/Home.md) — it covers the
bootstrap idea, the agent graph, the discovery engine, governance, and the production learnings
baked into the defaults.

---

## Install

Requires Python 3.11+.

```bash
# From GitHub (works today)
pip install "git+https://github.com/egen/junction"

# From a local clone
git clone https://github.com/egen/junction
cd junction && pip install .

# From a built wheel
python -m build && pip install dist/junction-*.whl

# Once published to PyPI
pip install junction-sdk      # or: pipx install junction-sdk
```

This installs the `junction` command (the PyPI distribution is named `junction-sdk` since `junction` was already taken; the CLI and the importable package are both still `junction`). `python -m junction` does the same thing.

---

## Quickstart

```bash
# End-to-end, interactive: 16 junction questions, phase by phase
junction --discover --target ./my-infra-repo

# End-to-end, no prompts (CI or a demo): defaults for everything not preset
junction --discover --defaults \
  --agent claude-code --domain payments \
  --target ./my-infra-repo --yes

# Replay a saved answers file (every run writes one)
junction --answers .github/config/discovery-answers.yml --target ./another-repo

# Validate a graph after hand edits
junction --validate-graph ./my-infra-repo/.github/config/agent-graph.yml
```

The run prints every decision, the phased plan, and the validated agent graph. Then it writes the files.

---

## CLI Reference

| Flag | Description | Default |
|------|-------------|---------|
| `--discover` | Run the discovery engine end to end: answers → agent graph → scaffold | off |
| `--answers FILE` | YAML/JSON answers to preset (implies `--discover`). Unanswered questions are asked | none |
| `--defaults` | Take the default for every question not preset (implies `--discover`) | off |
| `--domain NAME` | Business domain used in resource names (presets `domain_name`) | prompted |
| `--services a,b,...` | Comma-separated service names to generate Terraform for (GCP only). Default: one service named after `--domain` | one service |
| `--model TIER=MODEL` | Override a model tier (`planner`, `builder`, `validator`, `observer`, `curator`). Repeatable | see table |
| `--validate-graph FILE` | Validate an `agent-graph.yml` against schema v2.0 and the safety invariants, then exit | — |
| `--agent` | `copilot` \| `claude-code` \| `cursor` \| `continue` \| `agnostic` | prompted |
| `--cloud` | `aws` \| `gcp` \| `azure` \| `multi` | prompted |
| `--iac` | `terraform` \| `opentofu` \| `pulumi` \| `cdk` \| `cloudformation` | prompted |
| `--config FILE` | Pre-filled `platform.yml` (environments, accounts, MCP backends) | none |
| `--target DIR` | Target repo root | `.` |
| `--overwrite` | Replace existing files | off |
| `--dry-run` | List files without writing | off |
| `--yes`, `-y` | Don't prompt to create the target directory (existing files still need `--overwrite`) | off |
| `--generate-iac-with-agent` | Experimental: after scaffolding, drive the scaffolded `terraform-builder` subagent itself (via the `claude` CLI) to generate `infra/`, instead of the deterministic template. Requires `--agent claude-code`, `claude`/`terraform` on PATH, and real API usage | off |
| `--version` | Print the version | — |

Without `--discover`, the classic platform wizard (or `--config` / `--agent --cloud --iac`) runs, and the **default** six-agent graph is generated for that platform. You always get all six agents.

### Answers file

Any subset of question ids, plus optional `environments` (full records with account ids) and `models`:

```yaml
agent: claude-code
domain_name: payments
env_names: dev,staging,prod
jira_required: yes
has_msk: yes
models:
  validator: claude-haiku-4-5
environments:            # optional: overrides env_names with real accounts
  - {name: dev,     branch: dev,  account_id: "111111111111", risk_tier: LOW}
  - {name: staging, branch: stg,  account_id: "222222222222", risk_tier: MEDIUM}
  - {name: prod,    branch: main, account_id: "333333333333", risk_tier: HIGH}
```

A full example is in [`examples/discovery-answers.example.yml`](examples/discovery-answers.example.yml).

---

## What Gets Scaffolded

For every agent:

```
.github/
├── config/
│   ├── agent-graph.yml             # six nodes, edges, gates, failure policy, evals (schema v2.0)
│   ├── implementation-plan.md      # 7 gated phases + the decisions you made
│   ├── discovery-answers.yml       # replayable answers (discovery runs)
│   └── platform.yml                # environments, compute, MCP backends
├── skills/_core/                   # self-healing-deploy, env-promotion, drift-detection, post-push-monitor,
│                                   # knowledge-curation, v1-v2-migration
├── skills/_triage/                 # iac-triage, sre-log-fetching
├── skills/_domain/_TEMPLATE.md
├── instructions/                   # iac-standards, compute-patterns, prod-guardrails
├── knowledge/                      # service-registry, deployment-policies (OKF)
├── mcp-servers/README.md           # MCP interface contracts
├── copilot-instructions.md
└── .env-private.example
.vscode/mcp.json
```

Plus the six agents in the chosen agent's native format:

| `--agent` | Agent files | Extras |
|---|---|---|
| `copilot` | `.github/agents/<agent>.agent.md` ×6: `tools`, `agents`, and graph edges as `handoffs` | — |
| `claude-code` | `.claude/agents/<agent>.md` ×6 subagents: `tools`, `model` alias, `disallowedTools` on read-only agents; the orchestrator gets `Agent(...)` | `CLAUDE.md`, `/deploy`, `/promote`, `/drift-check`, `/sre-triage`, `/health-check`, `/migrate` |
| `cursor` | `.cursor/rules/<agent>.mdc` ×6 (orchestrator always applied) | `iac-standards.mdc` |
| `continue` | `.continue/rules/<agent>.md` ×6 | `config.json` slash commands, context file |
| `agnostic` | `.agents/<agent>.md` ×6 | `AGENTS.md` |

### Generated Terraform (`cloud: gcp`)

For `--cloud gcp`, `junction/terraform_generator.py` turns the same discovery answers into real,
`terraform validate`-clean HCL under `infra/`:

```
infra/
├── versions.tf / providers.tf / variables.tf / locals.tf
├── store-firestore.tf / store-pubsub.tf / store-gcs.tf / store-secret.tf   # only if selected
├── platform-run.tf                 # service accounts, IAM bindings, Cloud Run (for_each var.services)
├── service-<name>.tf               # one per service, outputs only (url, secret id if any)
└── tfvars/<env>.tfvars             # one per environment
```

Services scale up with `for_each` over a `services` map, never `count`. Use `--services api,worker,...`
to generate more than the single default service; each gets independent image/cpu/memory/replica/public/secret
settings in the generated tfvars. Public exposure (`allUsers` on Cloud Run) is opt-in per service, and IAM
grants are scoped to specific resources, never project-wide `roles/editor`/`roles/owner`.

AWS and Azure don't generate Terraform yet — `generate_terraform()` returns `None` for those clouds so the
gap stays visible rather than silently producing nothing.

### Agent-generated Terraform (experimental, opt-in)

The generator above is a deterministic Python template — fast, free, and reliably valid, but not actually
driven by the `terraform-builder` agent's own persona or context. `--generate-iac-with-agent` is the real
alternative: it skips the template and shells out to the `claude` CLI in headless mode
(`claude -p --agent terraform-builder ...`), running it inside the freshly scaffolded repo so it's grounded
in `platform.yml`, `service-registry.md`, and the `iac-standards`/`compute-patterns`/`prod-guardrails`
instructions the same way an interactive session would be. It loops `terraform init/validate`, feeding
errors back to the agent, up to 3 attempts.

This is opt-in and not the default: it requires `--agent claude-code` (the only adapter with a headless CLI
this module can drive today), the `claude` and `terraform` binaries on PATH, real API usage per bootstrap
run, and produces non-deterministic output — unlike the template, two runs on the same input can generate
different, though both potentially valid, Terraform. See `junction/agent_iac_generator.py`.

---

## The agent graph and its schema

`agent-graph.yml` is validated **every time it is generated or written**, and again on demand with `--validate-graph`. Validation uses JSON Schema ([`junction/schemas/agent-graph.schema.json`](junction/schemas/agent-graph.schema.json)) plus safety invariants the schema can't express:

- all six nodes are present, and the orchestrator can route to each of them
- `iac-validator` and `sre-observer` have no edit/write tools
- `migration-executor` is `HIGH` risk with `retry: 0`
- the `terraform-builder → iac-validator` "must pass" gate exists, and the fix loop has `max_cycles`
- the Jira gate edge and `governance.jira_gate.enabled` agree
- token budgets are ordered: warn < hard ≤ work-graph hard

An invalid graph is never written. The CLI exits 1 and lists every violation.

See [Agent Graph](docs/wiki/Agent-Graph.md) and [Governance, Safety and Evals](docs/wiki/Governance-Safety-and-Evals.md) for the full model.

### Model tiers

Reasoning-heavy tiers default to `claude-opus-5`, and read-only tiers to `claude-sonnet-5`. Override any tier with `--model`, `models:` in an answers file, or `generate_agent_graph(answers, models={...})`. Claude Code subagents get the family alias (`opus` / `sonnet` / `haiku`), so they keep tracking the latest model.

---

## SDK

```python
from junction import Bootstrap

# End-to-end from discovery answers (missing answers take defaults)
b = Bootstrap.from_discovery(
    {"agent": "claude-code", "domain_name": "payments", "env_names": "dev,staging,prod"},
    target_dir="./my-infra-repo",
    models={"validator": "claude-haiku-4-5"},
)
b.graph          # the validated agent graph (dict)
b.validate()     # paths that already exist
b.dry_run()      # {path: content}, no writes
b.run()          # write everything, return the paths written
```

```python
from junction import Bootstrap, Platform, generate_agent_graph, validate_agent_graph

platform = Platform.from_yaml("./my-platform.yml", agent="cursor")
graph = generate_agent_graph({"domain_name": "savings", "jira_required": False})
validate_agent_graph(graph)                      # raises AgentGraphValidationError
Bootstrap(platform, target_dir="./repo", graph=graph).run()
```

```python
from junction import run_discovery, print_implementation_plan

result = run_discovery(prefilled={"agent": "copilot"}, use_defaults=False)  # interactive
print_implementation_plan(result)
```

| API | Description |
|---|---|
| `Bootstrap(platform, target_dir=".", overwrite=False, graph=None, answers=None)` | Scaffolder. Generates the default graph if `graph` is omitted |
| `Bootstrap.from_discovery(answers, target_dir, overwrite, models)` | Answers → platform + graph → scaffolder |
| `.validate()` / `.dry_run()` / `.run()` / `.graph` / `.answers` | Conflicts, preview, write, graph, answers |
| `Platform.from_answers(dict)` / `Platform.from_yaml(path, agent)` | Platform config |
| `run_discovery(prefilled=None, use_defaults=False)` | Junction questions → `DiscoveryResult(answers, phase_plan)` |
| `generate_agent_graph(answers, models=None)` | Validated graph dict |
| `write_agent_graph(graph, path)` | Validate + write YAML |
| `validate_agent_graph(graph)` | Raises `AgentGraphValidationError` (`.errors` lists every violation) |

---

## GitHub Action

```yaml
# .github/workflows/bootstrap.yml
name: Bootstrap IaC Agent Graph
on:
  workflow_dispatch:
    inputs:
      agent:
        type: choice
        default: copilot
        options: [copilot, claude-code, cursor, continue, agnostic]
jobs:
  bootstrap:
    runs-on: ubuntu-latest
    permissions: {contents: write}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install "git+https://github.com/egen/junction"
      - run: |
          junction --answers .github/config/discovery-answers.yml \
            --agent ${{ inputs.agent }} --target . --overwrite --yes
      - run: junction --validate-graph .github/config/agent-graph.yml
      - run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add . && git commit -m "chore: scaffold six-agent graph (${{ inputs.agent }})" || echo "No changes"
          git push
```

---

## Documentation

The [Graph Agent Engineering Wiki](docs/wiki/Home.md) is the deep-dive companion to this README:

| If you want to… | Read |
|---|---|
| Understand the idea and why it's a graph | [The Bootstrap Idea](docs/wiki/Bootstrap-Idea.md) |
| See the six agents, their edges and the `agent-graph.yml` schema | [Agent Graph](docs/wiki/Agent-Graph.md) |
| Know which questions the bootstrap asks, and why then | [Discovery Engine](docs/wiki/Discovery-Engine.md) |
| Follow the build from empty repo to first agent-built service | [Implementation Phases](docs/wiki/Implementation-Phases.md) |
| Review risk tiers, gates, failure policy and token budgets | [Governance, Safety and Evals](docs/wiki/Governance-Safety-and-Evals.md) |
| Learn the anti-patterns the framework prevents | [Production Learnings](docs/wiki/Production-Learnings.md) |
| Install and run it, step by step | [Getting Started](docs/wiki/Getting-Started.md) |
| Map the idea to files in this repo | [Architecture and Repo Map](docs/wiki/Architecture-and-Repo-Map.md) |
| See what's done and what's still open | [Roadmap and Open Items](docs/wiki/Roadmap-and-Open-Items.md) |

---

## Development

```bash
pip install -e ".[dev]"
pytest                              # unit + end-to-end CLI tests
python scripts/sync_framework.py    # after editing .github/ skills/instructions/knowledge
python -m build                     # sdist + wheel in dist/
./scripts/local-e2e-check.sh        # optional: discovery → graph → agents → real `terraform validate` (needs terraform)
```

The skills, instructions and knowledge templates that junction copies are shipped inside the package (`junction/framework/`), so a pip install works without a repo checkout. `scripts/sync_framework.py` mirrors them from `.github/`, and a test fails if the two copies drift.

To add an adapter: subclass `AgentAdapter`, implement `generate_files(platform, graph=None)` using `self.agents(platform, graph)` (the six specs with rendered bodies), register it in `junction/agent_adapters/__init__.py`, and add it to `AGENT_CHOICES`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports, new coding-agent adapters, and new domain skills are especially welcome.

## Code of Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE)
