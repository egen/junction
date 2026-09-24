"""
LEARNINGS.py — Drift-prevention patterns behind the discovery questions.

Cloud- and stack-agnostic by design: these are the reasons a given junction
question exists and when it has to be asked, not concrete AWS/GCP/Azure
resource examples. Reference material only — nothing in junction imports
this module, so it's safe to extend with your own org's patterns without
touching behavior.

Use these to:
1. Explain why discovery asks a question at a particular phase, not another
2. Detect anti-patterns early (before they become tech debt)
3. Generate correct-by-default agent graph configurations
"""

# Patterns that PREVENT drift when asked at the right time
DRIFT_PREVENTION_PATTERNS = {
    "single_env_variable": {
        "pattern": "One var.environment, one set of values — never a second variable carrying the same information under a different name",
        "anti_pattern": "Having both var.environment and a second var.env_label with a different value per environment",
        "when_to_ask": "Phase 0 — before any IaC file is created",
        "cost_of_deferral": "Every file ends up touching both variables, and validators can't catch the leak",
    },
    "naming_with_resource_type": {
        "pattern": "{domain}-{env}-{resource-type}-{purpose} — a resource-type token in every name",
        "anti_pattern": "{domain}-{env}-{purpose} (missing resource type token)",
        "when_to_ask": "Phase 0 — naming standard must be locked before locals.tf",
        "cost_of_deferral": "All resource names need a bulk rename later, and name-based rules (SGs, IAM conditions) break",
    },
    "for_each_over_count": {
        "pattern": "Use for_each over a services map, never count",
        "anti_pattern": "count = length(var.services) — removing one service shifts every index after it",
        "when_to_ask": "Phase 1 — when defining the compute orchestration pattern",
        "cost_of_deferral": "Adding or removing a service destroys and recreates unrelated resources",
    },
    "secrets_vs_env_vars": {
        "pattern": "A secrets manager (or IAM/managed-identity auth) for credentials and external connection strings; plain env vars for everything else",
        "anti_pattern": "Putting deterministic, non-secret values in the secrets manager just because they're config",
        "when_to_ask": "Phase 4 — when wiring service env vars",
        "cost_of_deferral": "Secrets need manual rotation forever; identity-based auth doesn't",
    },
    "knowledge_is_platform_only": {
        "pattern": "Curated knowledge = platform-durable facts (services, architecture, runbooks)",
        "anti_pattern": "Putting ticket state or migration progress into the knowledge base",
        "when_to_ask": "Phase 1 — when creating the knowledge structure",
        "cost_of_deferral": "Knowledge goes stale, and agents have to navigate irrelevant state to find durable facts",
    },
    "ticket_gate_before_work": {
        "pattern": "Every task must link to a ticket before the orchestrator routes it, if jira_required is on",
        "anti_pattern": "Agent starts work, then posts partial updates to the tracker as it goes",
        "when_to_ask": "Phase 1 — when defining orchestrator behavior",
        "cost_of_deferral": "Untracked changes and partial ticket updates confuse stakeholders",
    },
    "module_interface_validation": {
        "pattern": "Resolve module/provider outputs before referencing them, don't guess from docs",
        "anti_pattern": "Guessing a module's output names from documentation that may be stale",
        "when_to_ask": "Phase 3 — before writing module calls",
        "cost_of_deferral": "terraform plan fails on 'output not found', with the agent debugging blind",
    },
    "error_decontamination": {
        "pattern": "On failure, reload knowledge fresh. Never carry stale context into a retry.",
        "anti_pattern": "Retrying with the same context that caused the failure",
        "when_to_ask": "Phase 1 — when defining error handling in agent-graph.yml",
        "cost_of_deferral": "Errors cascade, and all 3 retries fail the same way",
    },
}

# Questions that eliminate most post-scaffold fixes
HIGH_VALUE_JUNCTION_QUESTIONS = [
    "Do you have an existing repo you're migrating FROM? (triggers env var extraction)",
    "How do services authenticate to the database — identity-based or password? (avoids secret sprawl)",
    "Must every task link to a ticket? (determines orchestrator gate behavior)",
    "What naming standard should generated resources follow? (must be locked before ANY IaC file)",
    "Which external systems need credentials? (only THOSE get a secret bundle)",
]

# Anti-patterns detected in production that the framework prevents
DETECTED_ANTI_PATTERNS = {
    "legacy_naming_leak": {
        "symptom": "Old naming tokens or abbreviations from a prior platform leaking into a new repo",
        "prevention": "The IaC Validator agent scans for stale/legacy naming patterns pre-push",
        "learned_from": "A V1→V2 migration where dozens of stale references survived into the first draft",
    },
    "decorative_comments": {
        "symptom": "Decorative block comments (banners, separator lines) in generated IaC files",
        "prevention": "Governance layer rule: no decorative blocks — agents pay tokens for every line",
        "learned_from": "Thousands of tokens of pure decoration that agents had to parse on every read",
    },
    "full_workspace_scan": {
        "symptom": "Agent reads the entire repo instead of navigating the knowledge index",
        "prevention": "Evals detect this as a costly pattern and require index traversal instead",
        "learned_from": "A single task cost a full-repo scan when two index reads would have sufficed",
    },
    "premature_ticket_updates": {
        "symptom": "Posting 'starting work on...' or partial results to the issue tracker",
        "prevention": "Ticket reporting only on confirmed completion with real health/SRE evidence",
        "learned_from": "Stakeholders confused by several partial updates before the actual deploy",
    },
}
