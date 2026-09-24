---
name: knowledge-curation
description: "Use when: an incident is resolved, a runbook is missing or stale, the service registry or architecture notes need updating, or a stale-check of the knowledge base is requested."
---

# Skill: Knowledge Curation (Knowledge Curator)

Keeps the OKF (Organizational Knowledge Framework) knowledge base small, current and navigable, so other agents read an index instead of scanning the repository.

## §1 — What belongs in knowledge

| Belongs | Does not belong |
|---------|-----------------|
| Services and their health contracts | Ticket or story state |
| Architecture and dependencies | Migration progress (use `memories/`) |
| Runbooks for known failure modes | Chat transcripts, partial findings |
| Contracts (APIs, topics, schemas) | Anything that changes per deploy |
| Policies (deployment, risk, naming) | Secrets or account credentials |

## §2 — Workflows

### After an incident is resolved (edge from `sre-observer`)

1. Read the triage summary: symptom, root cause, fix, evidence
2. Find the existing runbook for the service or failure mode (index first)
3. Update it, or create `knowledge/runbooks/<service>-<failure-mode>.md` with:
   - **Symptom** (what alerts/logs show)
   - **Root cause**
   - **Fix** (steps, and which agent performs them)
   - **Prevention** (validator rule, policy, or test to add)
4. Cross-link it from `knowledge/service-registry.md`

### Stale check

1. For each knowledge file, compare facts against the code (service names, log groups, health endpoints, module versions)
2. Report mismatches as a table: file, claim, reality, proposed fix
3. Fix only documentation; never edit IaC

## §3 — Rules

- Keep the index navigable in two reads: `knowledge/README` or the registry → the specific file
- One fact, one place: link instead of copying
- No decorative formatting; agents pay tokens for every line
