"""
LEARNINGS.py — Production patterns encoded from real enterprise IaC deployments.

These are the questions, patterns, and anti-patterns discovered during 
scaffolding of a 15-service ECS + MSK + Aurora platform with 6 coding agents.

Use these to:
1. Guide discovery questions (ask at the RIGHT junction)
2. Detect anti-patterns early (before they become tech debt)
3. Generate correct-by-default agent graph configurations
"""

# Patterns that PREVENT drift when asked at the right time
DRIFT_PREVENTION_PATTERNS = {
    "single_env_variable": {
        "pattern": "One var.environment (dv/qc/pr) — never dual vars",
        "anti_pattern": "Having both var.environment (d1/u1/p1) and var.env_label (dv/qc/pr)",
        "when_to_ask": "Phase 0 — before any .tf file is created",
        "cost_of_deferral": "Every file touches both vars, validators can't catch leaks",
    },
    "naming_with_resource_type": {
        "pattern": "dp-{env}-{domain}-{resource-type}-{purpose}",
        "anti_pattern": "dp-{env}-{domain}-{purpose} (missing resource type token)",
        "when_to_ask": "Phase 0 — naming standard must be locked before locals.tf",
        "cost_of_deferral": "All resource names need bulk rename, SG rules break",
    },
    "for_each_over_count": {
        "pattern": "Use for_each over var.ecs_services map, never count",
        "anti_pattern": "count = length(var.services) — index shift on remove",
        "when_to_ask": "Phase 1 — when defining ECS orchestration pattern",
        "cost_of_deferral": "Adding/removing service destroys unrelated resources",
    },
    "secrets_vs_env_vars": {
        "pattern": "SM for credentials + external connection strings. ENV for everything else.",
        "anti_pattern": "Putting deterministic values (MSK bootstrap from IAM) in SM",
        "when_to_ask": "Phase 4 — when wiring service env vars",
        "cost_of_deferral": "SM secrets need manual rotation, IAM auth doesn't",
    },
    "knowledge_is_platform_only": {
        "pattern": "OKF knowledge = platform-durable facts (services, arch, runbooks)",
        "anti_pattern": "Putting JIRA story state or migration progress in knowledge",
        "when_to_ask": "Phase 1 — when creating knowledge structure",
        "cost_of_deferral": "Knowledge gets stale, agents navigate irrelevant state",
    },
    "jira_gate_before_work": {
        "pattern": "Every task MUST link to ticket before orchestrator routes",
        "anti_pattern": "Agent starts work, posts partial updates to JIRA",
        "when_to_ask": "Phase 1 — when defining orchestrator behavior",
        "cost_of_deferral": "Untracked changes, partial JIRA updates confuse stakeholders",
    },
    "module_interface_validation": {
        "pattern": "Clone modules locally, validate outputs exist before referencing",
        "anti_pattern": "Guessing module output names from documentation",
        "when_to_ask": "Phase 3 — before writing module calls",
        "cost_of_deferral": "terraform plan fails on 'output not found', debugging blind",
    },
    "error_decontamination": {
        "pattern": "On failure, reload OKF fresh. Never carry stale context forward.",
        "anti_pattern": "Retrying with the same context that caused the failure",
        "when_to_ask": "Phase 1 — when defining error handling in agent-graph.yml",
        "cost_of_deferral": "Error cascades, 3 retries all fail the same way",
    },
}

# Questions that eliminate 80% of post-scaffold fixes
HIGH_VALUE_JUNCTION_QUESTIONS = [
    "Do you have an existing repo you're migrating FROM? (triggers env var extraction)",
    "Do multiple services share the same Docker image? (triggers domain map pattern)",
    "How do services authenticate to the database? IAM or password? (eliminates SM bloat)",
    "Are MSK topics on a shared cluster or dedicated? (determines topic prefix)",
    "Must every task link to a JIRA ticket? (determines orchestrator gate behavior)",
    "What naming standard does your org enforce? (must be locked before ANY .tf file)",
    "Which external systems need credentials? (only THOSE get SM secrets)",
]

# Anti-patterns detected in production that the framework prevents
DETECTED_ANTI_PATTERNS = {
    "legacy_naming_leak": {
        "symptom": "dp-com, cortex, d1, u1, p1 in new repo",
        "prevention": "IaC Validator agent scans for these patterns pre-push",
        "learned_from": "V1→V2 migration — 28 stale references in first draft",
    },
    "decorative_comments": {
        "symptom": "═══════, ─────── block comments in .tf files",
        "prevention": "Governance layer rule: no decorative blocks",
        "learned_from": "Added 3K tokens of comments that agents had to parse",
    },
    "full_workspace_scan": {
        "symptom": "Agent reads entire repo instead of navigating OKF index",
        "prevention": "Evals detect this as costly pattern, block + require index traversal",
        "learned_from": "74K token workspace scan when 2 index reads would suffice",
    },
    "premature_jira_posting": {
        "symptom": "Posting 'starting work on...' or partial results to JIRA",
        "prevention": "JIRA reporting ONLY on 200% confirmed completion with SRE metrics",
        "learned_from": "Stakeholders confused by 5 partial updates before actual deploy",
    },
}
