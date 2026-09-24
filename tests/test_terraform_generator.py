import re

import pytest

from junction.config_builder import PlatformConfig
from junction.graph_generator import generate_agent_graph
from junction.terraform_generator import (
    ServiceSpec,
    generate_terraform,
    name_prefix_expr,
    services_from_answers,
)


@pytest.fixture
def gcp_platform():
    return PlatformConfig(cloud="gcp", application_name="orders")


@pytest.fixture
def graph():
    return generate_agent_graph({"domain_name": "orders"})


def test_unsupported_cloud_returns_none_not_empty_dict(graph):
    """None means "not implemented"; {} would look like "nothing to generate" — a
    real, different thing. Silently returning {} would hide that AWS generation
    doesn't exist yet."""
    aws_platform = PlatformConfig(cloud="aws", application_name="orders")
    assert generate_terraform(aws_platform, graph, {}) is None


def test_unsupported_iac_tool_returns_none_even_on_gcp(graph):
    """This module only emits Terraform/HCL. A gcp + pulumi (or cdk, or
    cloudformation) platform must never receive .tf files — that would look
    like real IaC in the wrong language, not a helpful default."""
    for tool in ("pulumi", "cdk", "cloudformation"):
        pulumi_platform = PlatformConfig(cloud="gcp", iac_tool=tool, application_name="orders")
        assert generate_terraform(pulumi_platform, graph, {}) is None


def test_opentofu_is_supported_as_hcl_compatible(gcp_platform, graph):
    """opentofu is a drop-in HCL fork of terraform — same generated files apply."""
    gcp_platform.iac_tool = "opentofu"
    assert generate_terraform(gcp_platform, graph, {}) is not None


def test_default_service_is_one_named_after_the_domain():
    services = services_from_answers({}, domain="orders")
    assert len(services) == 1
    assert services[0].name == "orders"
    assert services[0].public is False  # never public by default
    assert services[0].needs_secret is False


def test_default_service_needs_secret_only_with_external_system_and_secrets_manager():
    answers = {"external_systems": "Payment Gateway", "secret_strategy": "Secrets Manager (JSON bundle per service)"}
    services = services_from_answers(answers, domain="orders")
    assert services[0].needs_secret is True
    assert services[0].secret_name == "payment-gateway-api-key"

    iam_auth_answers = {"external_systems": "Payment Gateway", "secret_strategy": "IAM auth (no passwords, token-based)"}
    assert services_from_answers(iam_auth_answers, domain="orders")[0].needs_secret is False


def test_explicit_services_scale_up():
    answers = {"services": [
        {"name": "api", "public": True},
        {"name": "worker", "needs_secret": True, "secret_name": "x-api-key"},
    ]}
    services = services_from_answers(answers, domain="orders")
    assert [s.name for s in services] == ["api", "worker"]
    assert services[0].public is True
    assert services[1].needs_secret is True


def test_duplicate_service_names_rejected():
    answers = {"services": [{"name": "api"}, {"name": "api"}]}
    with pytest.raises(ValueError, match="duplicate"):
        services_from_answers(answers, domain="orders")


def test_invalid_service_name_rejected():
    with pytest.raises(ValueError, match="lowercase alphanumeric"):
        ServiceSpec(name="Not_Valid!")


def test_name_prefix_expr_cpe_pattern():
    expr, matched = name_prefix_expr("dp-{env}-{domain}-{resource-type}-{purpose}")
    assert matched is True
    assert expr == "dp-${var.environment}-${var.domain}"


def test_name_prefix_expr_unrecognized_pattern_falls_back_and_says_so():
    expr, matched = name_prefix_expr("{app}-{env}-{service}")
    assert matched is False
    assert expr == "dp-${var.environment}-${var.domain}"


class TestGeneratedTerraform:
    """Structural checks on the actual generated HCL text — these are the
    governance rules the iac-validator persona claims to enforce; verify the
    generator itself actually follows them, not just that terraform validate
    is happy (syntax-clean isn't the same as correct — see the allUsers and
    IAM-scoping checks below, which validate would never catch)."""

    @pytest.fixture
    def files(self, gcp_platform, graph):
        answers = {
            "has_rds": True, "has_msk": True, "has_s3": True,
            "external_systems": "Payment Gateway", "secret_strategy": "Secrets Manager (JSON bundle per service)",
            "services": [
                {"name": "api", "public": True},
                {"name": "worker", "public": False, "needs_secret": True, "secret_name": "payment-gateway-api-key"},
            ],
        }
        return generate_terraform(gcp_platform, graph, answers)

    def test_expected_files_present(self, files):
        expected = {
            "infra/versions.tf", "infra/providers.tf", "infra/variables.tf", "infra/locals.tf",
            "infra/store-firestore.tf", "infra/store-pubsub.tf", "infra/store-gcs.tf", "infra/store-secret.tf",
            "infra/platform-run.tf", "infra/service-api.tf", "infra/service-worker.tf",
            "infra/tfvars/dv.tfvars", "infra/tfvars/qc.tfvars", "infra/tfvars/pr.tfvars",
        }
        assert expected <= set(files)

    def test_single_var_environment_no_dual_env_var(self, files):
        assert 'variable "environment"' in files["infra/variables.tf"]
        for path, content in files.items():
            if path.endswith(".tf"):
                assert "variable \"env_label\"" not in content
                assert "variable \"environment2\"" not in content

    def test_for_each_used_never_count(self, files):
        assert "for_each = var.services" in files["infra/platform-run.tf"]
        # the `count` META-ARGUMENT, not any identifier merely containing the word
        # (min_instance_count, service_account, etc. are fine and expected).
        assert not re.search(r"^\s*count\s*=", files["infra/platform-run.tf"], re.MULTILINE)

    def test_public_invoker_gated_by_public_field_never_unconditional(self, files):
        run_tf = files["infra/platform-run.tf"]
        assert "allUsers" in run_tf
        assert 'for_each = { for name, svc in var.services : name => svc if svc.public }' in run_tf
        # every google_cloud_run_v2_service_iam_member is inside that gated for_each —
        # there is no second, unconditional allUsers binding anywhere in the file.
        assert run_tf.count("allUsers") == 1

    def test_iam_roles_scoped_never_project_wide_editor_or_owner(self, files):
        run_tf = files["infra/platform-run.tf"]
        # check actual role assignments (role = "roles/..."), not the guardrail
        # comment that names editor/owner as what NOT to use.
        granted_roles = re.findall(r'role\s*=\s*"([^"]+)"', run_tf)
        assert granted_roles, "expected at least one role assignment"
        assert "roles/editor" not in granted_roles
        assert "roles/owner" not in granted_roles
        # pubsub/storage/secret grants reference the specific resource, not the bare project
        assert 'topic   = google_pubsub_topic.events.name' in run_tf
        assert 'bucket = google_storage_bucket.artifacts.name' in run_tf

    def test_secret_ignore_changes_present(self, files):
        assert "ignore_changes = [secret_data]" in files["infra/store-secret.tf"]

    def test_gcs_bucket_name_suffixed_with_project_id(self, files):
        assert '${var.project_id}' in files["infra/store-gcs.tf"]

    def test_firestore_is_named_not_default(self, files):
        fs = files["infra/store-firestore.tf"]
        assert 'name        = "${local.name_prefix}-fs"' in fs
        # the actual `name =` attribute value, not the guardrail comment that
        # names "(default)" as what NOT to use.
        name_values = re.findall(r'^\s*name\s*=\s*"([^"]*)"', fs, re.MULTILINE)
        assert name_values and all(v != "(default)" for v in name_values)

    def test_no_decorative_comment_blocks(self, files):
        for path, content in files.items():
            if path.endswith(".tf"):
                assert "═" not in content, path
                assert "───" not in content, path

    def test_worker_secret_env_wired_but_api_has_none(self, files):
        run_tf = files["infra/platform-run.tf"]
        assert 'secret  = google_secret_manager_secret.external[each.key].secret_id' in run_tf

    def test_service_files_reference_correct_output_names(self, files):
        assert 'output "api_url"' in files["infra/service-api.tf"]
        assert 'output "worker_url"' in files["infra/service-worker.tf"]
        assert 'worker_secret_id' in files["infra/service-worker.tf"]
        assert "secret_id" not in files["infra/service-api.tf"]

    def test_no_stores_selected_omits_those_files(self, gcp_platform, graph):
        files = generate_terraform(gcp_platform, graph, {"has_rds": False, "has_msk": False, "has_s3": False})
        assert "infra/store-firestore.tf" not in files
        assert "infra/store-pubsub.tf" not in files
        assert "infra/store-gcs.tf" not in files
        assert "infra/store-secret.tf" not in files
        assert "infra/platform-run.tf" in files  # still generated — service accounts + Cloud Run always exist
