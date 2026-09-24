# Contributing to Junction

Thank you for your interest in contributing! This guide explains how to submit bug fixes, new
coding-agent adapters, new skills, and other improvements to the `junction` bootstrap CLI.

## Code of Conduct

All contributors must follow the [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Ways to Contribute

### 1. Report a Bug

Open a [Bug Report issue](.github/ISSUE_TEMPLATE/bug_report.md) and include:
- The CLI flags or SDK call you used.
- The generated agent/graph node involved, if relevant.
- Observed vs. expected behavior.
- Any relevant `platform.yml` or `agent-graph.yml` excerpts (redact secrets and account IDs).

### 2. Request a Feature

Open a [Feature Request issue](.github/ISSUE_TEMPLATE/feature_request.md). Describe the use case,
which part of the graph or discovery flow it touches, and what problem it solves.

### 3. Submit a New Skill

Skills are Markdown files with a YAML front-matter block, shipped inside the package and copied
into every scaffolded repo. To add a domain skill:

1. Create `.github/skills/_domain/your-skill-name/SKILL.md`.
2. Copy the template from `.github/skills/_domain/_TEMPLATE.md`.
3. Fill in `name`, `description`, and a `## Workflow` section.
4. If the skill should ship by default, add its path to `FRAMEWORK_FILES` in `junction/scaffold.py`
   and run `python scripts/sync_framework.py`.
5. Submit a PR.

### 4. Submit a New Agent Adapter

Adapters render the six graph agents for a specific coding agent (Copilot, Cursor, Claude Code,
Continue.dev, `AGENTS.md`, …).

1. Subclass `AgentAdapter` in `junction/agent_adapters/`, implementing
   `generate_files(platform, graph=None)` using `self.agents(platform, graph)`.
2. Register it in `junction/agent_adapters/__init__.py` and add it to `AGENT_CHOICES`.
3. Add coverage in `tests/test_adapters.py`.

### 5. Improve Documentation

Docs live in `README.md`, `CONTRIBUTING.md`, `docs/wiki/`, and the `.github/knowledge/` templates.
Edit them directly and open a PR.

---

## Pull Request Guidelines

- **Atomic PRs**: One logical change per PR.
- **No hardcoded values**: Keep `platform.yml` fields as `{placeholder}` strings.
- **No secrets**: Never commit API tokens, account IDs, or credentials.
- **Skill format**: All `SKILL.md` files must have a valid YAML front-matter block with at minimum `name` and `description`.
- **Schema changes**: Changes to `agent-graph.yml`'s shape need a matching update to
  `junction/schemas/agent-graph.schema.json` and the safety invariants in `junction/graph_schema.py`.
- **Framework drift**: If you touch anything under this repo's `.github/skills`, `.github/instructions`,
  `.github/knowledge`, or `.github/mcp-servers`, run `python scripts/sync_framework.py` before
  committing — `pytest` fails if `junction/framework/` drifts from `.github/`.

---

## Development Setup

```bash
git clone https://github.com/egen/junction
cd junction
pip install -e ".[dev]"
pytest                              # unit + end-to-end CLI tests
python scripts/sync_framework.py    # sync .github/ → junction/framework/ after editing shipped content
python scripts/sync_framework.py --check   # verify only, no writes (what CI runs)
```

To exercise the full path — discovery → agent graph → scaffolded agents → real generated Terraform
validated against the `hashicorp/google` provider schema — run:

```bash
./scripts/local-e2e-check.sh            # needs python3 and terraform on PATH
```

---

## Commit Message Format

```
feat(cli): add --services flag for multi-service Terraform generation
fix(graph): correct migration-executor risk_gate validation
docs: update Getting Started with the --answers flow
```

---

## Questions?

Open a discussion or issue. We respond to all contributor questions.
