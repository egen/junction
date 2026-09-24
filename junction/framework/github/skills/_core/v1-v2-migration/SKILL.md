---
name: v1-v2-migration
description: "Use when: migrating services from a V1 (legacy) IaC repo or platform to V2, running a migration phase, checking migration status, cutting over traffic, or rolling back a migration phase. HIGH risk — human gate on every failure."
argument-hint: "phase=<next|status|rollback> service=<service_key> ticket=<TICKET>"
---

# Skill: V1 → V2 Migration (Migration Executor)

Runs a migration as an explicit state machine. One phase per invocation, a gate at the end of every phase, and **no automatic retries**: any failure pauses the migration for a human.

## §1 — Entry Contract

| Input | Required | Notes |
|-------|----------|-------|
| `TICKET` | Yes | Migration work is never untracked |
| `SERVICE_KEY` | Yes (or `all`) | Must exist in `knowledge/service-registry.md` |
| `PHASE` | Yes | `next`, `status` or `rollback` |

Pre-conditions: boot protocol done, correct branch, migration state file readable.

## §2 — State

Migration state lives in `.github/memories/migration-state.md` (story state is **not** OKF knowledge):

```
SERVICE: my-api
PHASE: 3-shadow
STARTED: 2026-01-01T10:00Z
LAST_GATE: PASS (sre-observer, 2026-01-01T11:02Z)
ROLLBACK: tfvars/dv.tfvars@abc1234
```

## §3 — Phases

```
0-inventory → 1-parity → 2-provision → 3-shadow → 4-cutover → 5-decommission
```

| Phase | Action | Gate to leave the phase |
|-------|--------|-------------------------|
| **0-inventory** | Extract V1 env vars, secrets, naming, dependencies | Inventory reviewed by a human |
| **1-parity** | Map every V1 value to V2 (env var vs Secrets Manager vs IAM auth) | 100% of V1 env vars accounted for |
| **2-provision** | `terraform-builder` creates V2 resources; `iac-validator` must pass | Validator PASS + plan reviewed |
| **3-shadow** | V2 runs alongside V1 with no traffic, or mirrored traffic | `sre-observer` health gate: HEALTHY for the soak window |
| **4-cutover** | Shift traffic V1 → V2 (weighted if supported) | `sre-observer` health gate + error rate within baseline |
| **5-decommission** | Remove V1 resources | Human approval; V2 HEALTHY for the full retention window |

## §4 — Rules

1. **One phase per run.** Confirm the current phase with the user before acting.
2. **Retry count is 0.** On any failure: stop, write the state, report, and wait for a human.
3. **Never skip a gate.** A phase is complete only when its gate passes.
4. **Rollback is always ready.** Record the rollback ref before changing anything.
5. **Never delete V1** before phase 5 is approved.
6. **Legacy names must not leak** into V2 (e.g. old prefixes like `d1`, `u1`, `p1`). The validator scans for them.

## §5 — Rollback

```
1. Load ROLLBACK ref from migration state
2. terraform-builder restores the recorded tfvars / traffic weights
3. iac-validator must pass
4. sre-observer confirms V1 HEALTHY
5. State → previous phase, LAST_GATE: ROLLED_BACK
```

## §6 — Report

Report to the issue tracker **only** when a phase gate passes, with the gate evidence (health status, error rate, latency vs baseline).
