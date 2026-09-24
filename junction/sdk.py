"""
sdk.py — Public SDK for Junction.

Primary classes:
  Platform   — configuration data model (wraps PlatformConfig)
  Bootstrap  — scaffolding engine

Usage::

    from junction.sdk import Bootstrap, Platform

    platform = Platform.from_answers({
        "cloud": "aws",
        "iac_tool": "terraform",
        "agent": "cursor",
        "environments": [
            {"name": "dev", "branch": "dev", "account_id": "111111111111"},
            {"name": "prod", "branch": "prod", "account_id": "333333333333", "risk_tier": "HIGH"},
        ],
    })

    b = Bootstrap(platform=platform, target_dir="./my-infra-repo")
    conflicts = b.validate()        # returns list of conflicting paths
    files = b.dry_run()             # returns dict of {path: content}
    written = b.run()               # writes files, returns list of written paths
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from junction.config_builder import PlatformConfig


class Platform:
    """
    Thin wrapper around PlatformConfig that forms the SDK's public surface.

    All construction methods delegate to PlatformConfig.
    """

    def __init__(self, _config: PlatformConfig) -> None:
        self._config = _config

    # ── Construction ─────────────────────────────────────────────────

    @classmethod
    def from_answers(cls, answers: dict) -> "Platform":
        """
        Build from a flat answers dict.

        Minimum required keys: ``cloud``, ``iac_tool``, ``environments``.
        All other keys are optional with sensible defaults.

        Example::

            Platform.from_answers({
                "cloud": "aws",
                "iac_tool": "terraform",
                "agent": "copilot",
                "environments": [
                    {"name": "dev", "branch": "dev", "account_id": "111111111111"},
                ],
            })
        """
        return cls(PlatformConfig.from_answers(answers))

    @classmethod
    def from_yaml(cls, path: str | Path, agent: str = "copilot") -> "Platform":
        """Load from a pre-filled platform.yml file, skipping interactive prompts."""
        return cls(PlatformConfig.from_yaml(Path(path), agent=agent))

    # ── Accessors (expose key fields without leaking internals) ──────

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def iac_tool(self) -> str:
        return self._config.iac_tool

    @property
    def cloud(self) -> str:
        return self._config.cloud

    @property
    def agent(self) -> str:
        return self._config.agent

    @property
    def environments(self) -> list[dict]:
        return self._config.env_table_rows()

    def __repr__(self) -> str:
        return (
            f"Platform(name={self.name!r}, iac_tool={self.iac_tool!r}, "
            f"cloud={self.cloud!r}, agent={self.agent!r}, "
            f"envs={[e['name'] for e in self.environments]})"
        )


class Bootstrap:
    """
    Scaffolding engine.

    Parameters
    ----------
    platform:
        A :class:`Platform` instance describing the target configuration.
    target_dir:
        Path to the repository root where files will be written.
        Defaults to the current working directory.
    overwrite:
        If True, existing files in the target are silently replaced.
        Default is False — conflicting files raise :class:`FileExistsError`.
    graph:
        A validated agent graph (from :func:`generate_agent_graph`). When
        omitted, the default six-agent graph for ``platform`` is generated.
    answers:
        Discovery answers, written to ``.github/config/discovery-answers.yml``.
    generate_iac_with_agent:
        If True, skip the deterministic Terraform template generator (GCP
        only) and leave ``infra/`` for the scaffolded terraform-builder agent
        to generate itself post-bootstrap, e.g. via
        :func:`junction.agent_iac_generator.generate_iac_with_agent`.
    """

    def __init__(
        self,
        platform: "Platform",
        target_dir: str | Path = ".",
        overwrite: bool = False,
        graph: Optional[dict] = None,
        answers: Optional[dict] = None,
        generate_iac_with_agent: bool = False,
    ) -> None:
        from junction.agent_adapters._base import resolve_graph
        from junction.graph_schema import validate_agent_graph

        self._platform = platform._config
        self._target = Path(target_dir).resolve()
        self._overwrite = overwrite
        self._answers = answers
        self._generate_iac_with_agent = generate_iac_with_agent
        self._graph = resolve_graph(self._platform, graph)
        validate_agent_graph(self._graph)

    @classmethod
    def from_discovery(
        cls,
        answers: dict,
        target_dir: str | Path = ".",
        overwrite: bool = False,
        models: Optional[dict[str, str]] = None,
    ) -> "Bootstrap":
        """End-to-end: discovery answers → platform + agent graph → scaffolder.

        Missing answers take their defaults, so ``from_discovery({})`` works.
        """
        from junction.discovery import build_platform_config, default_answers
        from junction.graph_generator import generate_agent_graph

        full = {**default_answers(), **answers}
        graph = generate_agent_graph(full, models=models)
        platform = Platform(build_platform_config(full))
        return cls(platform, target_dir=target_dir, overwrite=overwrite, graph=graph, answers=full)

    # ── Core operations ──────────────────────────────────────────────

    def _collect(self) -> dict[str, str]:
        from junction.agent_adapters import get_adapter
        from junction.scaffold import collect_files

        all_files: dict[str, str] = {}
        all_files.update(
            collect_files(
                self._platform,
                graph=self._graph,
                answers=self._answers,
                skip_terraform_generation=self._generate_iac_with_agent,
            )
        )
        adapter = get_adapter(self._platform.agent)
        all_files.update(adapter.generate_files(self._platform, graph=self._graph))
        return all_files

    def validate(self) -> list[str]:
        """
        Check the target directory for file conflicts.

        Returns a list of relative paths that already exist and would be
        overwritten by :meth:`run`. An empty list means safe to proceed.
        """
        return [rel for rel in self._collect() if (self._target / rel).exists()]

    def dry_run(self) -> dict[str, str]:
        """
        Return all files that would be written, as a dict of
        ``{target-relative-path: file-content}``, without touching the filesystem.
        """
        return self._collect()

    def run(self) -> list[str]:
        """
        Write all scaffolded files into :attr:`target_dir`.

        Returns a list of relative paths that were written.
        Raises :class:`FileExistsError` if a conflict is found and
        ``overwrite=False``.
        """
        from junction.scaffold import append_gitignore, write_files

        all_files = self._collect()
        if not self._overwrite:
            conflicts = [rel for rel in all_files if (self._target / rel).exists()]
            if conflicts:
                raise FileExistsError(
                    f"{conflicts[0]} already exists in target (+{len(conflicts) - 1} more). "
                    "Use --overwrite to replace."
                )
        written = write_files(all_files, self._target, overwrite=self._overwrite)
        append_gitignore(self._target)
        return written

    # ── Properties ───────────────────────────────────────────────────

    @property
    def target_dir(self) -> Path:
        return self._target

    @property
    def graph(self) -> dict:
        return self._graph

    @property
    def answers(self) -> Optional[dict]:
        return self._answers

    @property
    def platform(self) -> "Platform":
        return Platform(self._platform)

    def __repr__(self) -> str:
        return (
            f"Bootstrap(platform={self._platform.name!r}, "
            f"agent={self._platform.agent!r}, "
            f"target={self._target})"
        )
