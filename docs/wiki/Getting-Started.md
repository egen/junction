# Getting Started

## Requirements

- Python 3.11+
- Dependencies (installed automatically): `click`, `jinja2`, `jsonschema`, `pyyaml`, `rich`
- A coding agent: GitHub Copilot Chat, Cursor, Claude Code, Continue.dev, or any agent that reads `AGENTS.md`
- Cloud credentials for the environments you'll operate

## Install

```bash
# From GitHub
pip install "git+https://github.com/egen/junction"

# Or from a clone of this repo
git clone https://github.com/egen/junction
cd junction
pip install -e ".[dev]"

# Once published: pip install junction-sdk (PyPI distribution name; CLI is still `junction`)
```

The wheel is self-contained: the skills, instructions, knowledge templates and graph schema ship inside the package.

## 1 · Design the agent graph (discovery) and scaffold in one command

```bash
junction --discover --target ./my-infra-repo
```

This runs the junction questions, prints the phased plan and the validated six-agent graph, then writes everything into the repo. Use `--defaults --yes` for a run with no prompts, `--answers FILE` to preset answers, and `--model TIER=MODEL` to change a model tier.

Or from Python:

```python
from junction import run_discovery, print_implementation_plan
from junction import generate_agent_graph, write_agent_graph

result = run_discovery()
print_implementation_plan(result)

graph = generate_agent_graph(result.answers)
write_agent_graph(graph, "my-infra-repo/agent-graph.yml")
```

If you already know your answers, skip the prompts and pass a dict to `generate_agent_graph` directly (see [Agent Graph](Agent-Graph.md#generating-one)).

## 2 · Other ways to scaffold

Without `--discover`, the default six-agent graph is generated for your platform:

```bash
# Interactive wizard
junction --target ./my-infra-repo

# Flag-driven (CI, GitHub Action, marketplace)
junction --agent claude-code --cloud aws --iac terraform --target ./my-infra-repo

# From an existing platform.yml
junction --config my-platform.yml --agent cursor --target ./my-infra-repo

# Preview only
junction --dry-run --target ./my-infra-repo
```

| Flag | Values | Default |
|---|---|---|
| `--agent` | `copilot` · `cursor` · `claude-code` · `continue` · `agnostic` | prompted |
| `--cloud` | `aws` · `gcp` · `azure` · `multi` | prompted |
| `--iac` | `terraform` · `opentofu` · `pulumi` · `cdk` · `cloudformation` | prompted |
| `--config` | path to `platform.yml` | none |
| `--target` | target repo root | `.` |
| `--overwrite` | overwrite existing files | off |
| `--dry-run` | preview without writing | off |
| `--discover` / `--defaults` / `--answers FILE` | discovery end to end, with defaults, or from a saved answers file | off |
| `--domain` | business domain (presets `domain_name`) | prompted |
| `--model TIER=MODEL` | override a model tier (repeatable) | opus/sonnet tiers |
| `--validate-graph FILE` | validate an `agent-graph.yml` and exit | — |
| `--yes` | don't prompt to create the target directory | off |

### What each agent adapter writes

| Agent | Files |
|---|---|
| `copilot` | `.github/agents/<node>.agent.md` ×6 (with handoffs) |
| `cursor` | `.cursor/rules/<node>.mdc` ×6 + `iac-standards.mdc` |
| `claude-code` | `.claude/agents/<node>.md` ×6 subagents, `CLAUDE.md`, `.claude/commands/{deploy,promote,drift-check,sre-triage,health-check,migrate}.md` |
| `continue` | `.continue/rules/<node>.md` ×6, `.continue/config.json`, `.continue/context/iac-platform.md` |
| `agnostic` | `.agents/<node>.md` ×6, `AGENTS.md` |

`<node>` is `orchestrator`, `iac-validator`, `terraform-builder`, `sre-observer`, `knowledge-curator` or `migration-executor`.

Every agent also gets the shared layer: `agent-graph.yml`, `implementation-plan.md`, `platform.yml`, eight skills, instructions, knowledge, MCP contracts, `.vscode/mcp.json`, `.env-private.example`, and `.gitignore` entries.

## 3 · Or use the SDK

```python
from junction import Bootstrap, Platform

platform = Platform.from_answers({
    "cloud": "aws", "iac_tool": "terraform", "agent": "claude-code",
    "environments": [
        {"name": "dv", "branch": "dev",  "account_id": "111111111111", "risk_tier": "LOW"},
        {"name": "qc", "branch": "qc",   "account_id": "222222222222", "risk_tier": "MEDIUM"},
        {"name": "pr", "branch": "main", "account_id": "333333333333", "risk_tier": "HIGH"},
    ],
})

b = Bootstrap(platform=platform, target_dir="./my-infra-repo")   # default graph
# or end to end: b = Bootstrap.from_discovery({"domain_name": "payments"}, target_dir="./my-infra-repo")
b.validate()   # paths that already exist
b.dry_run()    # {path: content}, no writes
b.run()        # write files, return the paths written
```

## 4 · Fill in the three files that make it yours

1. `.github/config/platform.yml`: environments, accounts, risk tiers, compute, MCP backends
2. `.github/knowledge/service-registry.md`: services, health endpoints, log groups
3. `.github/mcp-servers/README.md` → your MCP servers for cloud logs, issue tracker, observability and log aggregation

These three live at the root of your *scaffolded* repo (not this one) — junction writes templates into them, but the values are yours to fill in.

## 5 · Talk to the graph

Pick the **orchestrator** agent (Copilot), or just open the repo (Claude Code: the main session is the orchestrator), and describe the task:

```text
deploy my-api 1.5.0 to dev                → terraform-builder → iac-validator → self-healing deploy
promote dev to staging                    → terraform-builder → iac-validator
health check all services in staging      → sre-observer (read-only)
advance the V1 → V2 migration one phase   → migration-executor (HIGH risk)
```

In Claude Code the same flows are also slash commands: `/deploy`, `/promote`, `/drift-check`, `/sre-triage`, `/health-check`, `/migrate`.

Next: [Architecture and Repo Map](Architecture-and-Repo-Map.md)
