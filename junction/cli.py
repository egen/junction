"""
cli.py — Click-based entry point for junction.

Usage (interactive):
    python -m junction.cli
    junction                        # after pip install

Usage (flag-driven / CI):
    junction \\
        --agent copilot \\
        --cloud aws \\
        --iac terraform \\
        --target ./my-infra-repo

Usage (from pre-filled platform.yml):
    junction \\
        --config my-platform.yml \\
        --agent cursor \\
        --target ./my-infra-repo

Usage (end-to-end discovery → six-agent graph → scaffold):
    junction --discover --target ./my-infra-repo           # interactive
    junction --discover --defaults --agent claude-code \\
        --domain payments --target ./my-infra-repo --yes                # no prompts
    junction --answers discovery-answers.yml --target ./x  # replay
    junction --discover-with-agent --target ./my-infra-repo # agent proposes answers first

Validate a graph file:
    junction --validate-graph .github/config/agent-graph.yml
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from junction import __version__
from junction.config_builder import (
    AGENT_CHOICES,
    CICD_TYPES,
    CLOUD_PROVIDERS,
    COMPUTE_TYPES,
    IAC_TOOLS,
    MCP_BACKENDS,
    PlatformConfig,
    interactive_build,
)
from junction.discovery import build_platform_config, load_answers, print_implementation_plan, run_discovery
from junction.graph_generator import answers_from_platform, generate_agent_graph
from junction.graph_schema import AgentGraphValidationError, validate_agent_graph_file
from junction.models import parse_model_overrides
from junction.sdk import Bootstrap, Platform

console = Console()


# ─── Main command ─────────────────────────────────────────────────────────────


@click.command(name="junction")
@click.option(
    "--agent",
    type=click.Choice(AGENT_CHOICES, case_sensitive=False),
    default=None,
    help="Coding agent to configure for. Skip to enter interactive mode.",
)
@click.option(
    "--cloud",
    type=click.Choice(CLOUD_PROVIDERS, case_sensitive=False),
    default=None,
    help="Cloud provider (aws | gcp | azure | multi).",
)
@click.option(
    "--iac",
    "iac_tool",
    type=click.Choice(IAC_TOOLS, case_sensitive=False),
    default=None,
    help="IaC tool (terraform | opentofu | pulumi | cdk | cloudformation).",
)
@click.option(
    "--config",
    "config_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to a pre-filled platform.yml. Skips interactive prompts.",
)
@click.option(
    "--target",
    "target_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Target repository root to scaffold into.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Overwrite existing files without prompting.",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    default=False,
    help="Print files that would be written without touching the filesystem.",
)
@click.option(
    "--discover",
    is_flag=True,
    default=False,
    help="Run the discovery engine (junction questions) end to end: answers → agent graph → scaffold.",
)
@click.option(
    "--answers",
    "answers_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="YAML/JSON discovery answers to preset (implies --discover). Unanswered questions are asked.",
)
@click.option(
    "--defaults",
    "use_defaults",
    is_flag=True,
    default=False,
    help="Accept the default for every question not preset (implies --discover). Fully non-interactive.",
)
@click.option(
    "--domain",
    default=None,
    help="Business domain for resource names, e.g. payments (presets the domain_name question).",
)
@click.option(
    "--services",
    "services_arg",
    default=None,
    help="Comma-separated service names to generate Terraform for, e.g. api,worker (default: one service named after --domain). GCP only.",
)
@click.option(
    "--model",
    "model_overrides",
    multiple=True,
    metavar="TIER=MODEL",
    help="Override a model tier (planner, builder, validator, observer, curator). Repeatable.",
)
@click.option(
    "--validate-graph",
    "graph_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Validate an agent-graph.yml against the v2.0 schema and exit.",
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    default=False,
    help="Don't prompt to create the target directory. Existing files still need --overwrite.",
)
@click.option(
    "--discover-with-agent",
    "discover_with_agent",
    is_flag=True,
    default=False,
    help=(
        "EXPERIMENTAL, opt-in: before asking the junction questions, have your local "
        "coding-agent CLI (claude, headless, read-only — no Write/Edit/Bash tools) inspect "
        "the --target repo and propose answers for as many questions as it can infer, so "
        "there's less to answer by hand. Independent of --agent (the scaffold output "
        "format); works the same whichever one you pick. Requires the `claude` binary on "
        "PATH, real API usage, and an existing --target repo to inspect. Implies --discover."
    ),
)
@click.option(
    "--generate-iac-with-agent",
    "generate_iac_with_agent",
    is_flag=True,
    default=False,
    help=(
        "EXPERIMENTAL, opt-in: after scaffolding, drive the scaffolded terraform-builder "
        "subagent (via the `claude` CLI in headless mode) to generate infra/ itself, "
        "grounded in this repo's platform.yml/instructions/knowledge, instead of the "
        "deterministic Python template. Requires --agent claude-code, the `claude` and "
        "`terraform` binaries on PATH, and real API usage. Costs money and is non-deterministic."
    ),
)
@click.version_option(version=__version__, prog_name="junction")
def main(
    agent: Optional[str],
    cloud: Optional[str],
    iac_tool: Optional[str],
    config_file: Optional[Path],
    target_dir: Path,
    overwrite: bool,
    dry_run: bool,
    discover: bool,
    answers_file: Optional[Path],
    use_defaults: bool,
    domain: Optional[str],
    services_arg: Optional[str],
    model_overrides: tuple[str, ...],
    graph_file: Optional[Path],
    assume_yes: bool,
    discover_with_agent: bool,
    generate_iac_with_agent: bool,
) -> None:
    """
    Bootstrap Junction into a repository.

    Every run writes the six-agent graph (.github/config/agent-graph.yml) and
    one agent file per graph node for the chosen coding agent. Use --discover
    to shape the graph with the junction questions, or pass flags for CI use.
    """
    if graph_file:
        _validate_graph_command(graph_file)
        return

    _print_banner()

    try:
        models = parse_model_overrides(model_overrides)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--model") from None

    graph = None
    answers = None
    discover = discover or answers_file is not None or use_defaults or discover_with_agent

    # ── Build PlatformConfig ─────────────────────────────────────────
    if discover:
        platform_cfg, graph, answers = _discovery_build(
            answers_file, use_defaults, agent, cloud, iac_tool, domain, services_arg, models, config_file,
            target_dir=target_dir, discover_with_agent=discover_with_agent,
        )
    elif config_file:
        # Flag-driven: load from pre-filled platform.yml
        agent = agent or "copilot"
        console.print(f"[dim]Loading platform config from {config_file}[/dim]")
        platform_cfg = PlatformConfig.from_yaml(config_file, agent=agent)
        # Allow flag overrides on top of file
        if cloud:
            platform_cfg.cloud = cloud
        if iac_tool:
            platform_cfg.iac_tool = iac_tool
        if agent:
            platform_cfg.agent = agent
    elif _all_flags_provided(agent, cloud, iac_tool):
        # Minimal flag-driven: need at least one environment via prompts
        console.print("[yellow]Minimal flags provided — collecting environment details interactively.[/yellow]")
        platform_cfg = _flag_driven_build(agent, cloud, iac_tool)
    else:
        # Interactive wizard
        platform_cfg = interactive_build()

    if generate_iac_with_agent and platform_cfg.agent != "claude-code":
        raise click.BadParameter(
            f"--generate-iac-with-agent only supports --agent claude-code today (got {platform_cfg.agent!r}).",
            param_hint="--generate-iac-with-agent",
        )

    if graph is None:
        graph = generate_agent_graph(answers_from_platform(platform_cfg), models=models)
    platform = Platform(platform_cfg)
    _print_graph(graph)
    if (
        not generate_iac_with_agent
        and platform_cfg.cloud == "gcp"
        and platform_cfg.iac_tool not in ("terraform", "opentofu")
    ):
        console.print(
            f"[yellow]Note:[/yellow] Terraform generation only supports terraform/opentofu today; "
            f"no infra/ will be generated for --iac {platform_cfg.iac_tool}. "
            "The terraform-builder agent's own instructions still apply if you generate IaC by hand."
        )

    # ── Resolve target ────────────────────────────────────────────────
    target = target_dir.resolve()
    if not target.exists():
        if not dry_run:
            if assume_yes or click.confirm(f"\nTarget directory {target} does not exist. Create it?", default=True):
                target.mkdir(parents=True)
            else:
                console.print("[red]Aborted.[/red]")
                sys.exit(1)

    # ── Bootstrap ─────────────────────────────────────────────────────
    bootstrapper = Bootstrap(
        platform=platform, target_dir=target, overwrite=overwrite, graph=graph, answers=answers,
        generate_iac_with_agent=generate_iac_with_agent,
    )

    if dry_run:
        _print_dry_run(bootstrapper)
        return

    # Check for conflicts first
    conflicts = bootstrapper.validate()
    if conflicts and not overwrite:
        console.print("\n[yellow]⚠  The following files already exist in the target:[/yellow]")
        for path in conflicts:
            console.print(f"  [dim]{path}[/dim]")
        if assume_yes:
            console.print("[red]Aborted:[/red] pass --overwrite to replace existing files.")
            sys.exit(1)
        if not click.confirm("\nOverwrite all conflicting files?", default=False):
            console.print("[red]Aborted.[/red]")
            sys.exit(1)
        bootstrapper._overwrite = True

    console.print(f"\n[bold]Scaffolding into[/bold] [cyan]{target}[/cyan] …\n")
    try:
        written = bootstrapper.run()
    except FileExistsError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    _print_summary(written, platform_cfg, target)

    if generate_iac_with_agent:
        from junction.agent_iac_generator import generate_iac_with_agent as run_agent_iac

        console.print(
            "\n[bold]Driving terraform-builder to generate infra/ live[/bold] "
            "(this calls the real `claude` CLI, costs API usage, and can take a few minutes) …"
        )
        result = run_agent_iac(target, platform_cfg)
        if result.success:
            console.print(f"[green]✓[/green] {result.message}")
        else:
            console.print(f"[red]✗[/red] {result.message}")
            if result.last_validate_errors:
                console.print(f"[dim]{result.last_validate_errors}[/dim]")
            sys.exit(1)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _discovery_build(
    answers_file: Optional[Path],
    use_defaults: bool,
    agent: Optional[str],
    cloud: Optional[str],
    iac_tool: Optional[str],
    domain: Optional[str],
    services_arg: Optional[str],
    models: dict[str, str],
    config_file: Optional[Path],
    target_dir: Path = Path("."),
    discover_with_agent: bool = False,
) -> tuple[PlatformConfig, dict, dict]:
    """Discovery answers → (PlatformConfig, validated agent graph, answers)."""
    prefilled: dict = {}
    if answers_file:
        try:
            prefilled = load_answers(answers_file)
        except (ValueError, yaml.YAMLError) as exc:
            raise click.BadParameter(str(exc), param_hint="--answers") from None
        console.print(f"[dim]Loaded {len(prefilled)} preset answers from {answers_file}[/dim]")
    for key, value in (("agent", agent), ("cloud", cloud), ("iac_tool", iac_tool), ("domain_name", domain)):
        if value:
            prefilled[key] = value
    if services_arg:
        names = [n.strip() for n in services_arg.split(",") if n.strip()]
        if len(names) != len(set(names)):
            raise click.BadParameter(f"duplicate service names: {names}", param_hint="--services")
        prefilled["services"] = [{"name": n} for n in names]
    if config_file:
        base = PlatformConfig.from_yaml(config_file, agent=agent or prefilled.get("agent", "copilot"))
        prefilled.setdefault("agent", base.agent)
        prefilled.setdefault("cloud", base.cloud)
        prefilled.setdefault("iac_tool", base.iac_tool)
        prefilled.setdefault("env_names", ",".join(e.name for e in base.environments))

    agent_answer_keys: set = set()
    if discover_with_agent:
        agent_answer_keys = _run_discover_with_agent(target_dir.resolve(), prefilled)

    result = run_discovery(
        prefilled=prefilled, use_defaults=use_defaults, out=console, agent_answer_keys=agent_answer_keys,
    )
    answers = result.answers
    try:
        graph = generate_agent_graph(answers, models=models)
    except AgentGraphValidationError as exc:
        console.print(f"[red]Generated graph failed validation:[/red]\n{exc}")
        sys.exit(1)
    print_implementation_plan(result, out=console)

    if config_file:
        platform_cfg = PlatformConfig.from_yaml(config_file, agent=answers["agent"])
    else:
        platform_cfg = build_platform_config(answers)
    return platform_cfg, graph, answers


def _run_discover_with_agent(target: Path, prefilled: dict) -> set:
    """Have the local claude CLI inspect ``target`` and fill gaps in
    ``prefilled`` (mutated in place) with what it can infer. Explicit flags
    and an --answers file always win — the agent only fills what neither
    already set. Returns the set of keys the agent actually contributed, for
    the "(agent)" tag in the printed decision log."""
    from junction.agent_discovery import propose_answers_with_agent

    if not target.is_dir():
        console.print(
            f"[red]--discover-with-agent needs an existing --target repo to inspect "
            f"(got {target}, which does not exist).[/red]"
        )
        sys.exit(1)

    console.print(
        f"\n[bold]Asking your local coding agent to look at {target} …[/bold] "
        "[dim](read-only: Read/Glob/Grep, no writes; calls the real `claude` CLI)[/dim]"
    )
    result = propose_answers_with_agent(target)
    if not result.success:
        console.print(f"[yellow]⚠ {result.message} — falling back to asking every question.[/yellow]")
        return set()

    console.print(f"[green]✓[/green] {result.message}")
    for warning in result.warnings:
        console.print(f"  [dim yellow]- {warning}[/dim yellow]")

    agent_keys = set()
    for key, value in result.answers.items():
        if key not in prefilled:
            prefilled[key] = value
            agent_keys.add(key)
    return agent_keys


def _validate_graph_command(graph_file: Path) -> None:
    try:
        graph = validate_agent_graph_file(graph_file)
    except AgentGraphValidationError as exc:
        console.print(f"[red]✗ {graph_file} is invalid[/red]")
        for err in exc.errors:
            console.print(f"  [red]-[/red] {err}")
        sys.exit(1)
    except yaml.YAMLError as exc:
        console.print(f"[red]✗ {graph_file} is not valid YAML:[/red] {exc}")
        sys.exit(1)
    console.print(
        f"[green]✓ {graph_file} is a valid agent graph[/green] "
        f"(v{graph['graph']['version']}, {len(graph['nodes'])} nodes, {len(graph['edges'])} edges)"
    )


def _print_graph(graph: dict) -> None:
    from junction.agent_specs import build_agent_specs

    table = Table(title="Agent graph · schema v2.0 ✓", show_header=True, header_style="bold")
    table.add_column("Agent", style="cyan")
    table.add_column("Role")
    table.add_column("Access")
    table.add_column("Risk gate")
    table.add_column("Model")
    for spec in build_agent_specs(graph):
        table.add_row(
            spec.name, spec.role, "read-only" if spec.read_only else "read-write",
            spec.risk_gate, f"{spec.model} [dim]({spec.tier})[/dim]",
        )
    console.print()
    console.print(table)
    console.print(f"[dim]{len(graph['edges'])} edges · ticket gate "
                  f"{'on' if graph['governance']['jira_gate']['enabled'] else 'off'} · "
                  f"naming {graph['naming']['pattern']}[/dim]")


def _all_flags_provided(*args: Optional[str]) -> bool:
    return all(a is not None for a in args)


def _flag_driven_build(agent: str, cloud: str, iac_tool: str) -> PlatformConfig:
    """Collect only the missing pieces (environments) interactively."""
    from junction.config_builder import RISK_TIERS, EnvironmentConfig

    console.print("\n[bold]Environments[/bold] [dim](ordered low → high risk)[/dim]")
    environments = []
    env_index = 0
    default_names = ["dev", "staging", "prod"]
    default_tiers = ["LOW", "MEDIUM", "HIGH"]

    while True:
        default_name = default_names[env_index] if env_index < len(default_names) else ""
        env_name = click.prompt(
            f"  Environment {env_index + 1} name (blank to finish)",
            default=default_name,
        ).strip()
        if not env_name:
            if not environments:
                console.print("[yellow]  At least one environment is required.[/yellow]")
                continue
            break
        branch = click.prompt(f"  Branch for {env_name}", default=env_name)
        account_id = click.prompt(f"  Account ID for {env_name}", default="000000000000")
        prefix = click.prompt(f"  Prefix for {env_name}", default=env_name[:2])
        default_tier = default_tiers[min(env_index, 2)]
        risk_tier = click.prompt(
            f"  Risk tier ({', '.join(RISK_TIERS)})",
            default=default_tier,
            type=click.Choice(RISK_TIERS, case_sensitive=False),
        ).upper()
        environments.append(EnvironmentConfig(
            name=env_name,
            branch=branch,
            account_id=account_id,
            prefix=prefix,
            risk_tier=risk_tier,
            autonomous=(risk_tier == "LOW"),
            profile=f"my-{cloud}-{env_name}",
            tfvars=f"tfvars/{env_name}.tfvars",
        ))
        env_index += 1

    from junction.config_builder import cloud_defaults

    defaults = cloud_defaults(cloud)
    return PlatformConfig(
        name=f"My {cloud.upper()} Platform",
        iac_tool=iac_tool,
        cloud=cloud,
        repo_name="my-infra-repo",
        description=f"Infrastructure-as-Code managed by AI agents ({iac_tool} / {cloud})",
        agent=agent,
        environments=environments,
        compute_type=defaults["compute_type"],
        container_registry=defaults["container_registry"],
        cicd_type=defaults["cicd_type"],
        application_name="my-app",
        mcp=defaults["mcp"],
    )


def _print_banner() -> None:
    console.print(Panel.fit(
        f"[bold cyan]junction[/bold cyan] [dim]v{__version__}[/dim]\n"
        "Scaffold Junction into your repo.",
        border_style="cyan",
    ))


def _print_dry_run(bootstrapper: Bootstrap) -> None:
    files = bootstrapper.dry_run()
    console.print(f"\n[bold]Dry run — {len(files)} files would be written:[/bold]\n")
    for path in sorted(files.keys()):
        console.print(f"  [green]+[/green] {path}")
    console.print(
        f"\n[dim]Run without --dry-run to write these files into {bootstrapper.target_dir}[/dim]"
    )


def _print_summary(written: list[str], platform: PlatformConfig, target: Path) -> None:
    console.print(f"\n[bold green]✓ Scaffolded {len(written)} files[/bold green]\n")

    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("Written", style="green")
    for path in sorted(written):
        table.add_row(f"  {path}")
    console.print(table)

    # Next steps
    env_cmds = []
    for e in platform.environments:
        env_cmds.append(f"# {e.name}: {e.account_id}")

    mcp_setup = "   [dim]" + ", ".join(platform.mcp.enabled_servers()) + " — interface contracts in .github/mcp-servers/README.md[/dim]"

    agent_note = {
        "copilot": "Open VS Code Copilot Chat and pick the [bold]orchestrator[/bold] agent — it hands off to the other five.",
        "cursor": "Open Cursor — the orchestrator rule is always on; specialist rules load from .cursor/rules/.",
        "claude-code": "Open the repo in Claude Code — CLAUDE.md makes the main session the orchestrator; run /agents to see all six.",
        "continue": "Open VS Code with Continue — agent rules load from .continue/rules/, slash commands are registered.",
        "agnostic": "Start from AGENTS.md; each agent's brief is in .agents/.",
    }.get(platform.agent, "")

    console.print(Panel(
        f"""[bold]Next steps[/bold]

[cyan]1.[/cyan] Fill in your platform config:
   [dim]{target}/.github/config/platform.yml[/dim]

[cyan]2.[/cyan] Configure MCP server environment variables:
   [dim]cp {target}/.github/.env-private.example {target}/.github/.env-private[/dim]
   [dim]# Then fill in your credentials[/dim]

[cyan]3.[/cyan] Point the MCP servers in .vscode/mcp.json at your backends:
{mcp_setup}

[cyan]4.[/cyan] Fill in your service registry:
   [dim]{target}/.github/knowledge/service-registry.md[/dim]

[cyan]5.[/cyan] {agent_note}

[cyan]6.[/cyan] Re-validate the graph after editing it:
   [dim]junction --validate-graph {target}/.github/config/agent-graph.yml[/dim]

[dim]See README.md for full documentation.[/dim]""",
        title="[bold]Bootstrap complete[/bold]",
        border_style="green",
    ))


if __name__ == "__main__":
    main()
