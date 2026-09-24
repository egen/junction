"""
config_builder.py — Data model and interactive prompts for platform.yml.

Provides:
  - PlatformConfig  dataclass (the canonical in-memory representation)
  - interactive_build()  — guides user through prompts and returns PlatformConfig
  - from_yaml()          — loads a pre-filled platform.yml into PlatformConfig
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

# ─── Risk tier ordering ──────────────────────────────────────────────────────

RISK_TIERS = ["LOW", "MEDIUM", "HIGH"]

# ─── Supported options ───────────────────────────────────────────────────────

CLOUD_PROVIDERS = ["aws", "gcp", "azure", "multi"]
IAC_TOOLS = ["terraform", "opentofu", "pulumi", "cdk", "cloudformation"]
COMPUTE_TYPES = ["ecs_fargate", "eks", "lambda", "ec2_asg", "gke", "aca"]
CICD_TYPES = ["codebuild", "github_actions", "gitlab_ci", "spacelift", "atlantis"]
AGENT_CHOICES = ["copilot", "cursor", "claude-code", "continue", "agnostic"]

MCP_BACKENDS = {
    "cloud_logs": {
        "label": "Cloud Logs",
        "backends": ["cloudwatch", "gcp_logging", "azure_monitor"],
        "default": "cloudwatch",
        "env_vars": {
            "cloudwatch": ["AWS_REGION", "AWS_PROFILE"],
            "gcp_logging": ["GOOGLE_CLOUD_PROJECT", "GOOGLE_APPLICATION_CREDENTIALS"],
            "azure_monitor": ["AZURE_SUBSCRIPTION_ID", "AZURE_TENANT_ID"],
        },
    },
    "issue_tracker": {
        "label": "Issue Tracker",
        "backends": ["jira", "linear", "github_issues", "azure_devops"],
        "default": "jira",
        "env_vars": {
            "jira": ["JIRA_URL", "JIRA_USERNAME", "ATLASSIAN_API_TOKEN"],
            "linear": ["LINEAR_API_KEY"],
            "github_issues": ["GITHUB_TOKEN", "GITHUB_REPO"],
            "azure_devops": ["AZURE_DEVOPS_TOKEN", "AZURE_DEVOPS_ORG"],
        },
    },
    "observability": {
        "label": "Observability / APM",
        "backends": ["newrelic", "datadog", "grafana", "xray"],
        "default": "newrelic",
        "env_vars": {
            "newrelic": ["NEW_RELIC_API_KEY", "NEW_RELIC_ACCOUNT_ID"],
            "datadog": ["DD_API_KEY", "DD_APP_KEY", "DD_SITE"],
            "grafana": ["GRAFANA_URL", "GRAFANA_TOKEN"],
            "xray": ["AWS_REGION", "AWS_PROFILE"],
        },
    },
    "log_aggregator": {
        "label": "Log Aggregator",
        "backends": ["opensearch", "elasticsearch", "loki", "none"],
        "default": "opensearch",
        "env_vars": {
            "opensearch": ["OPENSEARCH_ENDPOINT"],
            "elasticsearch": ["ELASTICSEARCH_URL", "ELASTICSEARCH_API_KEY"],
            "loki": ["LOKI_URL"],
            "none": [],
        },
    },
}

# ─── Data model ──────────────────────────────────────────────────────────────


@dataclass
class EnvironmentConfig:
    name: str
    branch: str
    account_id: str
    prefix: str
    risk_tier: str
    autonomous: bool
    profile: str
    tfvars: str

    @classmethod
    def from_dict(cls, d: dict) -> "EnvironmentConfig":
        return cls(
            name=d["name"],
            branch=d.get("branch", d["name"]),
            account_id=d.get("account_id", "000000000000"),
            prefix=d.get("prefix", d["name"][:2]),
            risk_tier=d.get("risk_tier", "LOW"),
            autonomous=d.get("autonomous", d.get("risk_tier", "LOW") == "LOW"),
            profile=d.get("profile", f"my-aws-{d['name']}"),
            tfvars=d.get("tfvars", f"tfvars/{d['name']}.tfvars"),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "branch": self.branch,
            "account_id": self.account_id,
            "prefix": self.prefix,
            "risk_tier": self.risk_tier,
            "autonomous": self.autonomous,
            "profile": self.profile,
            "tfvars": self.tfvars,
        }


@dataclass
class McpConfig:
    cloud_logs_backend: str = "cloudwatch"
    issue_tracker_backend: str = "jira"
    observability_backend: str = "newrelic"
    log_aggregator_backend: str = "opensearch"
    cloud_logs_enabled: bool = True
    issue_tracker_enabled: bool = True
    observability_enabled: bool = True
    log_aggregator_enabled: bool = True

    def enabled_servers(self) -> list[str]:
        result = []
        if self.cloud_logs_enabled:
            result.append("cloud-logs")
        if self.issue_tracker_enabled:
            result.append("issue-tracker")
        if self.observability_enabled:
            result.append("observability")
        if self.log_aggregator_enabled and self.log_aggregator_backend != "none":
            result.append("log-aggregator")
        return result

    def env_vars_for(self, server: str) -> list[str]:
        key = server.replace("-", "_")
        backend_attr = f"{key}_backend"
        backend = getattr(self, backend_attr, None)
        if backend is None:
            return []
        spec = MCP_BACKENDS.get(key, {})
        return spec.get("env_vars", {}).get(backend, [])


@dataclass
class PlatformConfig:
    # Core
    name: str = "My Infrastructure Platform"
    iac_tool: str = "terraform"
    cloud: str = "aws"
    repo_name: str = "my-infra-repo"
    description: str = "Infrastructure-as-Code repository managed by AI agents"

    # Agent
    agent: str = "copilot"

    # Environments (ordered low→high risk)
    environments: List[EnvironmentConfig] = field(default_factory=list)

    # Compute
    compute_type: str = "ecs_fargate"
    container_registry: str = "ecr"

    # CI/CD
    cicd_type: str = "codebuild"

    # Application
    application_name: str = "my-app"

    # MCP
    mcp: McpConfig = field(default_factory=McpConfig)

    @classmethod
    def from_dict(cls, d: dict, agent: str = "copilot") -> "PlatformConfig":
        """Build from a raw dict (e.g., loaded from platform.yml)."""
        platform = d.get("platform", {})
        envs = [EnvironmentConfig.from_dict(e) for e in d.get("environments", [])]

        compute = d.get("compute", {})
        cicd = d.get("cicd", {})
        naming = d.get("naming", {})
        mcp_raw = d.get("mcp_servers", {})

        mcp = McpConfig(
            cloud_logs_backend=mcp_raw.get("cloud_logs", {}).get("backend", "cloudwatch"),
            issue_tracker_backend=mcp_raw.get("issue_tracker", {}).get("backend", "jira"),
            observability_backend=mcp_raw.get("observability", {}).get("backend", "newrelic"),
            log_aggregator_backend=mcp_raw.get("log_aggregator", {}).get("backend", "opensearch"),
            cloud_logs_enabled=mcp_raw.get("cloud_logs", {}).get("enabled", True),
            issue_tracker_enabled=mcp_raw.get("issue_tracker", {}).get("enabled", True),
            observability_enabled=mcp_raw.get("observability", {}).get("enabled", True),
            log_aggregator_enabled=mcp_raw.get("log_aggregator", {}).get("enabled", True),
        )

        return cls(
            name=platform.get("name", "My Infrastructure Platform"),
            iac_tool=platform.get("iac_tool", "terraform"),
            cloud=platform.get("cloud", "aws"),
            repo_name=platform.get("repo_name", "my-infra-repo"),
            description=platform.get("description", "Infrastructure-as-Code managed by AI agents"),
            agent=agent,
            environments=envs,
            compute_type=compute.get("type", "ecs_fargate"),
            container_registry=compute.get("registry", {}).get("type", "ecr"),
            cicd_type=cicd.get("type", "codebuild"),
            application_name=naming.get("application", "my-app"),
            mcp=mcp,
        )

    @classmethod
    def from_yaml(cls, path: Path, agent: str = "copilot") -> "PlatformConfig":
        """Load from a pre-filled platform.yml file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data, agent=agent)

    @classmethod
    def from_answers(cls, answers: dict) -> "PlatformConfig":
        """Build from a flat answers dict (e.g., from SDK callers)."""
        envs = [
            EnvironmentConfig.from_dict(e) for e in answers.get("environments", [])
        ]
        mcp_answers = answers.get("mcp", {})
        mcp = McpConfig(
            cloud_logs_backend=mcp_answers.get("cloud_logs_backend", "cloudwatch"),
            issue_tracker_backend=mcp_answers.get("issue_tracker_backend", "jira"),
            observability_backend=mcp_answers.get("observability_backend", "newrelic"),
            log_aggregator_backend=mcp_answers.get("log_aggregator_backend", "opensearch"),
            cloud_logs_enabled=mcp_answers.get("cloud_logs_enabled", True),
            issue_tracker_enabled=mcp_answers.get("issue_tracker_enabled", True),
            observability_enabled=mcp_answers.get("observability_enabled", True),
            log_aggregator_enabled=mcp_answers.get("log_aggregator_enabled", True),
        )
        return cls(
            name=answers.get("name", "My Infrastructure Platform"),
            iac_tool=answers.get("iac_tool", "terraform"),
            cloud=answers.get("cloud", "aws"),
            repo_name=answers.get("repo_name", "my-infra-repo"),
            description=answers.get("description", "Infrastructure-as-Code managed by AI agents"),
            agent=answers.get("agent", "copilot"),
            environments=envs,
            compute_type=answers.get("compute_type", "ecs_fargate"),
            container_registry=answers.get("container_registry", "ecr"),
            cicd_type=answers.get("cicd_type", "codebuild"),
            application_name=answers.get("application_name", "my-app"),
            mcp=mcp,
        )

    # ── Convenience helpers ─────────────────────────────────────────

    def lowest_risk_env(self) -> Optional[EnvironmentConfig]:
        return self.environments[0] if self.environments else None

    def highest_risk_env(self) -> Optional[EnvironmentConfig]:
        return self.environments[-1] if self.environments else None

    def env_table_rows(self) -> list[dict]:
        return [e.to_dict() for e in self.environments]


# ─── Cloud defaults ──────────────────────────────────────────────────────────


def cloud_defaults(cloud: str) -> dict:
    """Compute, registry, CI/CD and MCP backend defaults for a cloud provider."""
    mcp = {
        "aws": McpConfig(cloud_logs_backend="cloudwatch", observability_backend="newrelic"),
        "gcp": McpConfig(cloud_logs_backend="gcp_logging", observability_backend="grafana"),
        "azure": McpConfig(cloud_logs_backend="azure_monitor", observability_backend="datadog"),
    }.get(cloud, McpConfig())
    return {
        "mcp": mcp,
        "compute_type": "ecs_fargate" if cloud == "aws" else "gke" if cloud == "gcp" else "aca",
        "container_registry": "ecr" if cloud == "aws" else "gcr" if cloud == "gcp" else "acr",
        "cicd_type": "codebuild" if cloud == "aws" else "github_actions",
    }


def default_risk_tier(index: int, count: int) -> str:
    """LOW for the first env, HIGH for the last, MEDIUM in between."""
    if index == 0:
        return "LOW"
    return "HIGH" if index == count - 1 else "MEDIUM"


# ─── Interactive prompts ──────────────────────────────────────────────────────


def interactive_build() -> PlatformConfig:
    """Walk the user through a series of prompts and return a PlatformConfig."""
    import click
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    console.print(Panel.fit(
        "[bold cyan]Junction — Bootstrap Wizard[/bold cyan]\n"
        "Answer a few questions to scaffold the framework into your repo.\n"
        "[dim]Press Enter to accept defaults shown in [brackets].[/dim]",
        border_style="cyan",
    ))

    # ── Platform basics ──────────────────────────────────────────────
    console.print("\n[bold]Platform basics[/bold]")
    name = click.prompt("Platform name", default="My Infrastructure Platform")
    repo_name = _slugify(click.prompt("Repo name (slug)", default="my-infra-repo"))
    description = click.prompt(
        "Short description",
        default="Infrastructure-as-Code repository managed by AI agents",
    )
    application_name = _slugify(
        click.prompt("Application name (used in resource naming)", default="my-app")
    )

    # ── Coding agent ─────────────────────────────────────────────────
    console.print("\n[bold]Coding agent[/bold]")
    console.print(f"  Options: {', '.join(AGENT_CHOICES)}")
    agent = click.prompt("Coding agent", default="copilot", type=click.Choice(AGENT_CHOICES, case_sensitive=False))

    # ── Cloud + IaC ──────────────────────────────────────────────────
    console.print("\n[bold]Cloud + IaC[/bold]")
    console.print(f"  Cloud options: {', '.join(CLOUD_PROVIDERS)}")
    cloud = click.prompt("Cloud provider", default="aws", type=click.Choice(CLOUD_PROVIDERS, case_sensitive=False))
    console.print(f"  IaC options: {', '.join(IAC_TOOLS)}")
    iac_tool = click.prompt("IaC tool", default="terraform", type=click.Choice(IAC_TOOLS, case_sensitive=False))

    # ── Compute + CI/CD ──────────────────────────────────────────────
    console.print("\n[bold]Compute + CI/CD[/bold]")
    console.print(f"  Compute options: {', '.join(COMPUTE_TYPES)}")
    compute_type = click.prompt("Compute type", default="ecs_fargate", type=click.Choice(COMPUTE_TYPES, case_sensitive=False))
    console.print(f"  CI/CD options: {', '.join(CICD_TYPES)}")
    cicd_type = click.prompt("CI/CD system", default="codebuild", type=click.Choice(CICD_TYPES, case_sensitive=False))

    registry_defaults = {"aws": "ecr", "gcp": "gcr", "azure": "acr", "multi": "ghcr"}
    container_registry = registry_defaults.get(cloud, "ecr")

    # ── Environments ─────────────────────────────────────────────────
    console.print("\n[bold]Environments[/bold] [dim](ordered low → high risk, e.g. dev → staging → prod)[/dim]")
    environments: list[EnvironmentConfig] = []
    env_index = 0
    risk_pool = list(RISK_TIERS)

    while True:
        default_names = ["dev", "staging", "prod"]
        default_name = default_names[env_index] if env_index < len(default_names) else ""
        env_name = click.prompt(
            f"  Environment {env_index + 1} name (or leave blank to finish)",
            default=default_name,
        ).strip()
        if not env_name:
            if not environments:
                console.print("[yellow]  At least one environment is required. Please add one.[/yellow]")
                continue
            break

        branch = click.prompt(f"  Branch for {env_name}", default=env_name)
        account_id = click.prompt(f"  Cloud account/project ID for {env_name}", default="000000000000")
        prefix = click.prompt(f"  Short prefix for {env_name} (e.g. d1, s1, p1)", default=env_name[:2])

        default_tier = risk_pool[min(env_index, len(risk_pool) - 1)]
        console.print(f"  Risk tiers: {', '.join(RISK_TIERS)}")
        risk_tier = click.prompt(
            f"  Risk tier for {env_name}",
            default=default_tier,
            type=click.Choice(RISK_TIERS, case_sensitive=False),
        )
        autonomous = risk_tier == "LOW"

        environments.append(EnvironmentConfig(
            name=env_name,
            branch=branch,
            account_id=account_id,
            prefix=prefix,
            risk_tier=risk_tier.upper(),
            autonomous=autonomous,
            profile=f"my-aws-{env_name}",
            tfvars=f"tfvars/{env_name}.tfvars",
        ))
        env_index += 1

    # ── MCP backends ─────────────────────────────────────────────────
    console.print("\n[bold]MCP server backends[/bold]")
    mcp_choices: dict[str, str] = {}
    for server_key, spec in MCP_BACKENDS.items():
        label = spec["label"]
        opts = ", ".join(spec["backends"])
        console.print(f"  {label} options: {opts}")
        chosen = click.prompt(
            f"  {label} backend",
            default=spec["default"],
            type=click.Choice(spec["backends"], case_sensitive=False),
        )
        mcp_choices[server_key] = chosen

    mcp = McpConfig(
        cloud_logs_backend=mcp_choices.get("cloud_logs", "cloudwatch"),
        issue_tracker_backend=mcp_choices.get("issue_tracker", "jira"),
        observability_backend=mcp_choices.get("observability", "newrelic"),
        log_aggregator_backend=mcp_choices.get("log_aggregator", "opensearch"),
        cloud_logs_enabled=True,
        issue_tracker_enabled=True,
        observability_enabled=True,
        log_aggregator_enabled=mcp_choices.get("log_aggregator", "opensearch") != "none",
    )

    return PlatformConfig(
        name=name,
        iac_tool=iac_tool,
        cloud=cloud,
        repo_name=repo_name,
        description=description,
        agent=agent,
        environments=environments,
        compute_type=compute_type,
        container_registry=container_registry,
        cicd_type=cicd_type,
        application_name=application_name,
        mcp=mcp,
    )


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _slugify(text: str) -> str:
    """Convert free text to a lowercase slug suitable for repo/app names."""
    return re.sub(r"[^a-z0-9-]", "-", text.lower()).strip("-")
