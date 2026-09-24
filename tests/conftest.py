import pytest

from junction.config_builder import EnvironmentConfig, PlatformConfig
from junction.graph_generator import generate_agent_graph


@pytest.fixture
def platform():
    envs = [
        EnvironmentConfig.from_dict({"name": n, "risk_tier": t, "account_id": a})
        for n, t, a in [("dv", "LOW", "111111111111"), ("qc", "MEDIUM", "222222222222"), ("pr", "HIGH", "333333333333")]
    ]
    return PlatformConfig(name="Test Platform", application_name="payments", environments=envs)


@pytest.fixture
def graph():
    return generate_agent_graph({"domain_name": "payments"})
