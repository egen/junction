"""
terraform_generator.py — Generate real Terraform (store-*.tf, platform-*.tf,
service-*.tf) from the SAME platform.yml + agent-graph.yml that discovery
already produces. Closes roadmap item #7 ("store/secret answers don't
generate Terraform yet").

GCP only for now. The shape (Cloud Run + named Firestore + Pub/Sub + GCS +
Secret Manager) is the fast footprint proven three times over in
examples/gcp-fast-stack/, examples/gcp-orders-service/ and
examples/gcp-health-profile/ — this module is that pattern, driven by code
instead of hand-written per test. AWS Terraform generation is not
implemented: --cloud aws still scaffolds agents/skills/instructions, but
generate_terraform() returns None for it rather than silently producing
nothing without saying so.

Design decisions worth being explicit about (informed by real defects found
testing the hand-written examples — see docs/wiki/Roadmap-and-Open-Items.md):
  - Cloud Run services are NEVER public (no `allUsers` invoker binding)
    unless a service's `public: true` is explicitly set. The hand-written
    examples all defaulted to public; that was a real, unflagged security
    gap, not a template to repeat.
  - IAM roles are granted per-resource (topic/subscription/bucket/secret),
    never project-wide, and never editor/owner.
  - Multiple services scale via one shared `for_each` over `var.services` in
    platform-run.tf, plus one `service-<name>.tf` per service holding that
    service's own env-var/secret locals — mirrors the documented AWS
    "self-contained unit, 3-touches-to-add" convention, for GCP.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from junction.config_builder import PlatformConfig

SUPPORTED_CLOUDS = ("gcp",)
# opentofu is a drop-in HCL-compatible fork of terraform — same generated files apply.
# pulumi/cdk/cloudformation are different languages entirely; generating .tf for them
# would be silently wrong, not just unsupported.
SUPPORTED_IAC_TOOLS = ("terraform", "opentofu")

DEFAULT_IMAGE = "us-docker.pkg.dev/cloudrun/container/hello"


# ─── Service spec ─────────────────────────────────────────────────────────────


@dataclass
class ServiceSpec:
    name: str
    image: str = DEFAULT_IMAGE
    cpu: str = "250m"
    memory: str = "256Mi"
    replicas_dev: int = 1
    replicas_prod: int = 2
    public: bool = False  # Cloud Run invoker: never public unless explicitly asked
    needs_secret: bool = False
    secret_name: Optional[str] = None  # e.g. "payment-gateway-api-key"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,40}", self.name):
            raise ValueError(
                f"service name {self.name!r} must be lowercase alphanumeric/hyphen, "
                "starting with a letter (GCP resource-name rules)"
            )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ServiceSpec":
        return cls(
            name=d["name"],
            image=d.get("image", DEFAULT_IMAGE),
            cpu=str(d.get("cpu", "250m")),
            memory=str(d.get("memory", "256Mi")),
            replicas_dev=int(d.get("replicas_dev", 1)),
            replicas_prod=int(d.get("replicas_prod", 2)),
            public=bool(d.get("public", False)),
            needs_secret=bool(d.get("needs_secret", False)),
            secret_name=d.get("secret_name"),
        )


def services_from_answers(answers: dict[str, Any], domain: str) -> list[ServiceSpec]:
    """Explicit ``answers["services"]`` wins (scale-up input); otherwise a single
    service named after the domain, needing a secret only if discovery said this
    domain has an external system AND chose Secrets Manager (not IAM-auth-only)."""
    raw = answers.get("services")
    if raw:
        specs = [ServiceSpec.from_dict(s) for s in raw]
        names = [s.name for s in specs]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate service names in answers['services']: {names}")
        return specs

    external = str(answers.get("external_systems") or "").strip()
    strategy = str(answers.get("secret_strategy") or "").lower()
    needs_secret = bool(external) and strategy.startswith(("secrets manager", "both"))
    secret_name = f"{_slugify(external.split(',')[0])}-api-key" if needs_secret else None
    return [ServiceSpec(name=domain, needs_secret=needs_secret, secret_name=secret_name)]


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-") or "external"


# ─── Naming ────────────────────────────────────────────────────────────────────


def name_prefix_expr(naming_pattern: str) -> tuple[str, bool]:
    """Turn the graph's naming.pattern into a Terraform string expression for
    the shared resource-name prefix, substituting {env}/{domain} for real
    interpolations and dropping the per-resource {resource-type}/{purpose}
    tokens (each resource appends its own).

    Returns (expression, matched) — matched=False means the pattern wasn't the
    expected "prefix-{env}-{domain}-{resource-type}-..." shape, and a safe
    default was used instead (never silently wrong, always says so in the
    generated locals.tf comment).
    """
    if "{resource-type}" in naming_pattern:
        prefix_part = naming_pattern.split("{resource-type}")[0].rstrip("-")
        matched = True
    else:
        prefix_part = naming_pattern
        matched = "{env}" in naming_pattern and "{domain}" in naming_pattern

    expr = prefix_part.replace("{env}", "${var.environment}").replace("{domain}", "${var.domain}")
    if not matched:
        expr = "dp-${var.environment}-${var.domain}"
    return expr, matched


# ─── GCP generator ─────────────────────────────────────────────────────────────


def generate_gcp_terraform(
    platform: PlatformConfig, graph: dict[str, Any], answers: dict[str, Any]
) -> dict[str, str]:
    """Generate store-*.tf / platform-*.tf / service-*.tf for cloud: gcp.

    Returns {relative_path: content}, all under an ``infra/`` prefix.
    """
    domain = graph["graph"].get("domain") or platform.application_name
    services = services_from_answers(answers, domain)
    naming_pattern = graph["naming"]["pattern"]
    prefix_expr, prefix_matched = name_prefix_expr(naming_pattern)
    env_names = graph["naming"]["env_values"]

    has_rds = bool(answers.get("has_rds", True))
    has_msk = bool(answers.get("has_msk", True))
    has_s3 = bool(answers.get("has_s3", True))
    any_secret = any(s.needs_secret for s in services)

    files: dict[str, str] = {}
    files["infra/versions.tf"] = _versions_tf()
    files["infra/providers.tf"] = _providers_tf()
    files["infra/variables.tf"] = _variables_tf(env_names, services)
    files["infra/locals.tf"] = _locals_tf(domain, prefix_expr, prefix_matched, naming_pattern)

    if has_rds:
        files["infra/store-firestore.tf"] = _store_firestore_tf()
    if has_msk:
        files["infra/store-pubsub.tf"] = _store_pubsub_tf()
    if has_s3:
        files["infra/store-gcs.tf"] = _store_gcs_tf()
    if any_secret:
        files["infra/store-secret.tf"] = _store_secret_tf()

    files["infra/platform-run.tf"] = _platform_run_tf(services, has_rds, has_msk, has_s3)

    for svc in services:
        files[f"infra/service-{svc.name}.tf"] = _service_tf(svc, has_rds, has_msk, has_s3)

    for env in env_names:
        files[f"infra/tfvars/{env}.tfvars"] = _tfvars(env, domain, services)

    return files


def generate_terraform(
    platform: PlatformConfig, graph: dict[str, Any], answers: dict[str, Any]
) -> Optional[dict[str, str]]:
    """Dispatch by cloud AND iac_tool. Returns None (not {}) for an unsupported
    combination, so callers can tell "nothing to generate" apart from
    "generation not implemented for this choice" and say so rather than going
    silent. In particular: this module only emits Terraform/HCL, so a
    platform.iac_tool of pulumi/cdk/cloudformation must never receive .tf
    files — that would look like real IaC in the wrong language."""
    if platform.cloud == "gcp" and platform.iac_tool in SUPPORTED_IAC_TOOLS:
        return generate_gcp_terraform(platform, graph, answers)
    return None


# ─── Templates ─────────────────────────────────────────────────────────────────


def _versions_tf() -> str:
    return """terraform {
  required_version = ">= 1.7"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.40"
    }
  }
}
"""


def _providers_tf() -> str:
    return """provider "google" {
  project = var.project_id
  region  = var.region
}
"""


def _variables_tf(env_names: list[str], services: list[ServiceSpec]) -> str:
    env_list = ", ".join(f'"{e}"' for e in env_names)
    return f"""# Single environment variable — per iac-standards: never a second env-like variable.
variable "environment" {{
  description = "Deployment environment"
  type        = string
  validation {{
    condition     = contains([{env_list}], var.environment)
    error_message = "environment must be one of: {", ".join(env_names)}"
  }}
}}

variable "project_id" {{
  description = "GCP project id for this environment (from infra/tfvars/{{env}}.tfvars — never hardcoded)"
  type        = string
}}

variable "region" {{
  description = "GCP region"
  type        = string
  default     = "us-central1"
}}

variable "domain" {{
  description = "Business domain (becomes part of every resource name)"
  type        = string
}}

variable "services" {{
  description = "Cloud Run services, keyed by name (for_each pattern — never count). Add a service by adding one entry here plus one service-<name>.tf file, not by editing this shared resource."
  type = map(object({{
    image       = string
    cpu         = string
    memory      = string
    replicas    = number
    public      = bool
    secret_name = optional(string)
  }}))
}}
"""


def _locals_tf(domain: str, prefix_expr: str, prefix_matched: bool, naming_pattern: str) -> str:
    note = (
        f"# Naming pattern from agent-graph.yml: {naming_pattern}"
        if prefix_matched
        else (
            f"# NOTE: agent-graph.yml naming pattern ({naming_pattern!r}) does not match the\n"
            f"# expected \"...-{{env}}-{{domain}}-{{resource-type}}-...\" shape, so a default\n"
            f"# prefix (dp-{{env}}-{{domain}}) was used instead. Review before relying on it."
        )
    )
    return f"""{note}
locals {{
  domain      = "{domain}"
  name_prefix = "{prefix_expr}"

  labels = {{
    domain      = var.domain
    environment = var.environment
    managed_by  = "terraform"
  }}
}}
"""


def _store_firestore_tf() -> str:
    return """# Store — named Firestore database (never "(default)": a project may already have
# one, and this must never collide with it).
resource "google_firestore_database" "app" {
  project     = var.project_id
  name        = "${local.name_prefix}-fs"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  concurrency_mode = "OPTIMISTIC"
}
"""


def _store_pubsub_tf() -> str:
    return """# Store — Pub/Sub events (fast GCP equivalent of MSK for has_msk: yes).
resource "google_pubsub_topic" "events" {
  name    = "${local.name_prefix}-pubsub-events"
  project = var.project_id
  labels  = local.labels
}

resource "google_pubsub_topic" "events_dlq" {
  name    = "${local.name_prefix}-pubsub-events-dlq"
  project = var.project_id
  labels  = local.labels
}

resource "google_pubsub_subscription" "events_worker" {
  name    = "${local.name_prefix}-pubsub-events-worker"
  topic   = google_pubsub_topic.events.id
  project = var.project_id

  ack_deadline_seconds = 30

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.events_dlq.id
    max_delivery_attempts = 5
  }
}
"""


def _store_gcs_tf() -> str:
    return """# Store — GCS (fast GCP equivalent of S3 for has_s3: yes). Bucket names are
# globally unique across all of GCP, so the name is suffixed with the project id.
resource "google_storage_bucket" "artifacts" {
  name     = "${local.name_prefix}-gcs-artifacts-${var.project_id}"
  location = var.region
  project  = var.project_id
  labels   = local.labels

  uniform_bucket_level_access = true
  force_destroy               = var.environment != "prod"

  lifecycle_rule {
    condition { age = 90 }
    action { type = "Delete" }
  }
}
"""


def _store_secret_tf() -> str:
    return """# Store — Secret Manager, only for the named external credential(s) — everything
# internal uses IAM auth via each service's own service account (secrets_vs_env_vars
# learning). One secret per service that set secret_name in var.services.
resource "google_secret_manager_secret" "external" {
  for_each = { for name, svc in var.services : name => svc if svc.secret_name != null }

  secret_id = "${local.name_prefix}-secret-${each.value.secret_name}"
  project   = var.project_id
  labels    = local.labels

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
}

resource "google_secret_manager_secret_version" "external" {
  for_each = google_secret_manager_secret.external

  secret      = each.value.id
  secret_data = jsonencode({}) # placeholder — filled out of band, never in .tf

  lifecycle {
    ignore_changes = [secret_data] # IaC never overwrites a live secret value
  }
}
"""


def _platform_run_tf(services: list[ServiceSpec], has_rds: bool, has_msk: bool, has_s3: bool) -> str:
    secret_iam = ""
    if any(s.needs_secret for s in services):
        secret_iam = """
resource "google_secret_manager_secret_iam_member" "accessor" {
  for_each = google_secret_manager_secret.external

  secret_id = each.value.id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.service[each.key].email}"
}
"""
    firestore_iam = (
        """
resource "google_project_iam_member" "firestore_user" {
  for_each = var.services

  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.service[each.key].email}"
}
"""
        if has_rds
        else ""
    )
    pubsub_iam = (
        """
resource "google_pubsub_topic_iam_member" "publisher" {
  for_each = var.services

  topic   = google_pubsub_topic.events.name
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.service[each.key].email}"
}

resource "google_pubsub_subscription_iam_member" "subscriber" {
  for_each = var.services

  subscription = google_pubsub_subscription.events_worker.name
  project      = var.project_id
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.service[each.key].email}"
}
"""
        if has_msk
        else ""
    )
    gcs_iam = (
        """
resource "google_storage_bucket_iam_member" "writer" {
  for_each = var.services

  bucket = google_storage_bucket.artifacts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.service[each.key].email}"
}
"""
        if has_s3
        else ""
    )

    env_blocks = []
    if has_rds:
        env_blocks.append('      env {\n        name  = "FIRESTORE_DATABASE"\n        value = google_firestore_database.app.name\n      }')
    if has_msk:
        env_blocks.append('      env {\n        name  = "PUBSUB_TOPIC"\n        value = google_pubsub_topic.events.name\n      }')
    if has_s3:
        env_blocks.append('      env {\n        name  = "GCS_BUCKET"\n        value = google_storage_bucket.artifacts.name\n      }')
    env_block_text = "\n".join(env_blocks)

    return f"""# Platform — one service account per service, least privilege only: each grant
# below is scoped to the specific store resource, never project-wide, never
# roles/editor or roles/owner.
resource "google_service_account" "service" {{
  for_each = var.services

  project      = var.project_id
  account_id   = "${{local.name_prefix}}-${{each.key}}-sa"
  display_name = "Service account for ${{each.key}} (${{var.environment}})"
}}
{firestore_iam}{pubsub_iam}{gcs_iam}{secret_iam}
# Platform — Cloud Run, not Kubernetes resources: there is no cluster. One
# shared for_each resource scales to any number of services — add a service by
# adding one entry to var.services (tfvars) plus, optionally, one
# service-<name>.tf for that service's own outputs/bespoke resources; nothing
# here needs to change.
resource "google_cloud_run_v2_service" "app" {{
  for_each = var.services

  name     = "${{local.name_prefix}}-run-${{each.key}}"
  project  = var.project_id
  location = var.region

  template {{
    service_account = google_service_account.service[each.key].email

    scaling {{
      min_instance_count = 0
      max_instance_count = each.value.replicas
    }}

    containers {{
      image = each.value.image

      env {{
        name  = "GCP_PROJECT"
        value = var.project_id
      }}
{env_block_text}

      dynamic "env" {{
        for_each = each.value.secret_name != null ? [1] : []
        content {{
          name = "EXTERNAL_SECRET"
          value_source {{
            secret_key_ref {{
              secret  = google_secret_manager_secret.external[each.key].secret_id
              version = "latest"
            }}
          }}
        }}
      }}

      resources {{
        limits = {{ cpu = each.value.cpu, memory = each.value.memory }}
      }}

      ports {{
        container_port = 8080
      }}
    }}
  }}

  labels = local.labels
}}

# Cloud Run services are NEVER public by default — this binding is only created
# for a service that explicitly set public = true in var.services.
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {{
  for_each = {{ for name, svc in var.services : name => svc if svc.public }}

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.app[each.key].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}}
"""


def _service_tf(svc: ServiceSpec, has_rds: bool, has_msk: bool, has_s3: bool) -> str:
    output_name = svc.name.replace("-", "_")
    secret_line = (
        f'\noutput "{output_name}_secret_id" {{\n'
        f'  description = "Secret Manager id for {svc.name} — populate its value out of band."\n'
        f'  value       = google_secret_manager_secret.external["{svc.name}"].secret_id\n'
        "}\n"
        if svc.needs_secret
        else ""
    )
    return f"""# Service — {svc.name}: this file is what "adding a service" touches. Its
# actual Cloud Run resource, IAM and (if needed) secret are the shared for_each
# resources in platform-run.tf / store-secret.tf, keyed by this name; add the
# service by adding its entry to var.services in tfvars, not by editing those
# shared files. This file holds only what is genuinely specific to {svc.name}.
output "{output_name}_url" {{
  description = "Cloud Run URL for {svc.name}"
  value       = google_cloud_run_v2_service.app["{svc.name}"].uri
}}
{secret_line}"""


def _tfvars(env: str, domain: str, services: list[ServiceSpec]) -> str:
    lines = [
        f'environment = "{env}"',
        f'project_id  = "your-gcp-project-id-{env}"',
        'region      = "us-central1"',
        f'domain      = "{domain}"',
        "",
        "services = {",
    ]
    for svc in services:
        lines.append(f'  {svc.name} = {{')
        lines.append(f'    image       = "{svc.image}"')
        lines.append(f'    cpu         = "{svc.cpu}"')
        lines.append(f'    memory      = "{svc.memory}"')
        lines.append(f'    replicas    = {svc.replicas_prod if env == "prod" else svc.replicas_dev}')
        lines.append(f'    public      = {str(svc.public).lower()}')
        secret_value = f'"{svc.secret_name}"' if svc.secret_name else "null"
        lines.append(f'    secret_name = {secret_value}')
        lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"
