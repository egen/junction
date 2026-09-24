## Description

<!-- Provide a concise summary of what changed and why. -->

## Type of Change

- [ ] Bug fix (CLI, SDK, or generated-agent behavior correction)
- [ ] New skill or agent adapter
- [ ] Agent graph / schema change (`agent-graph.yml`, `graph_schema.py`)
- [ ] Configuration change (`platform.yml` schema)
- [ ] Documentation update

## Checklist

- [ ] I have read [CONTRIBUTING.md](../CONTRIBUTING.md)
- [ ] Skill files follow the `---` YAML front-matter format (name, description)
- [ ] No secrets, account IDs, or env-specific values are hardcoded in committed files
- [ ] `platform.yml` placeholders remain as `{placeholder}` (not real values)
- [ ] Ran `python scripts/sync_framework.py` if I touched `.github/skills`, `.github/instructions`, `.github/knowledge`, or `.github/mcp-servers`
- [ ] `pytest` passes locally

## Testing Notes

<!-- How did you verify the change? E.g., "Ran junction --discover --defaults --agent cursor and confirmed the 6 rule files." -->

## Related Issues

<!-- Closes #123 -->
