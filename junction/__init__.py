"""
Junction — Python SDK and package.

End-to-end flow (``junction --discover``):
  - discovery.py: junction questions → answers + phased plan
  - graph_generator.py: answers → validated six-agent graph (agent-graph.yml)
  - graph_schema.py: JSON Schema + safety invariants for the graph
  - agent_specs.py / agent_adapters/: one agent file per graph node, per coding agent
  - scaffold.py / sdk.py: write everything into the target repo
"""

__version__ = "0.1.0"

from junction.discovery import DiscoveryResult, print_implementation_plan, run_discovery  # noqa: E402
from junction.graph_generator import generate_agent_graph, write_agent_graph  # noqa: E402
from junction.graph_schema import AgentGraphValidationError, validate_agent_graph  # noqa: E402
from junction.models import DEFAULT_MODELS  # noqa: E402
from junction.sdk import Bootstrap, Platform  # noqa: E402

__all__ = [
    "__version__",
    "Bootstrap",
    "Platform",
    "DiscoveryResult",
    "run_discovery",
    "print_implementation_plan",
    "generate_agent_graph",
    "write_agent_graph",
    "validate_agent_graph",
    "AgentGraphValidationError",
    "DEFAULT_MODELS",
]
