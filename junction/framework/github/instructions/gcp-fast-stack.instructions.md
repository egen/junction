---
description: "Use when: cloud is gcp and the task calls for a service that must provision in minutes, not stand up a full production platform (e.g. a live demo, a spike, a hackathon idea). Covers the fixed fast-provisioning GCP footprint, how it maps the AWS-flavored discovery answers, and the application-code contract (client init, health checks) that goes with it."
applyTo: "**/*.tf,**/*.tfvars,**/main.py,**/app.py"
---

# GCP Fast Stack

For `cloud: gcp` work where the store/compute discovery answers (`has_rds`,
`has_msk`, `has_s3`, `compute.type`) were answered against the AWS-shaped
question set, use this fixed, fast-provisioning footprint instead of the
AWS-native instructions in `compute-patterns.instructions.md` and
`iac-standards.instructions.md`, which are ECS/RDS/MSK-specific and do not
apply on GCP.

## The footprint

| AWS-flavored answer | GCP resource | Why this one |
|---|---|---|
| `compute.type: gke` / ECS Fargate | `google_cloud_run_v2_service` | Provisions in seconds; GKE Autopilot takes 5–10+ minutes — too slow for a live run |
| `has_rds: yes` | `google_firestore_database` (named, native mode) | Instant; Cloud SQL instance creation takes 5–10+ minutes |
| `has_msk: yes` | `google_pubsub_topic` + subscription (+ DLQ) | Provisions in seconds, same pub/sub shape as MSK |
| `has_s3: yes` | `google_storage_bucket` | Provisions in seconds |
| `secret_strategy: Secrets Manager` | `google_secret_manager_secret` | Only for the one external credential named in `external_systems` — everything internal uses IAM auth via the Cloud Run service's own service account, same as the `secrets_vs_env_vars` learning |
| `kms_strategy` | Google-managed encryption (no custom `google_kms_crypto_key`) | A custom KMS key ring adds one more resource with no speed cost, but skip it here unless asked — one fewer moving part live |

## Rules

1. **Named Firestore database, never `(default)`.** A GCP project can already
   have a `(default)` Firestore database provisioned outside this repo's
   Terraform. Always create a **named** database
   (`google_firestore_database` with `name = "${local.name_prefix}-fs"`, not
   `"(default)"`) so `terraform apply` never collides with pre-existing
   project state. Firestore in Datastore mode is not this pattern — use
   Native mode (`type = "FIRESTORE_NATIVE"`).
2. **GCS bucket names are globally unique across all of GCP**, not just this
   project — unlike S3. Always suffix the bucket name with the project id:
   `"${local.name_prefix}-gcs-<purpose>-${var.project_id}"`.
3. **One service account per service**, granted only the roles the service
   actually calls: `roles/datastore.user`, `roles/pubsub.publisher` and/or
   `roles/pubsub.subscriber` on the specific topic/subscription (not
   project-wide), `roles/storage.objectAdmin` on the specific bucket, and
   `roles/secretmanager.secretAccessor` on the specific secret — never
   `roles/editor` or `roles/owner`.
4. **Cloud Run, not Kubernetes resources.** Do not declare
   `kubernetes_deployment`/`kubernetes_service` for this footprint — there is
   no cluster. `google_cloud_run_v2_service` takes the container image,
   env vars, and the service account directly.
5. **Naming, single env var, `for_each`, no decorative comments, secrets
   `ignore_changes`** — every other rule in `iac-standards.instructions.md`
   and `compute-patterns.instructions.md` still applies. Only the resource
   choices above are GCP-specific overrides.
6. **Keep it to one service per idea** unless asked for more — a live demo
   needs one thing that works, not a platform.
7. **Construct GCP clients lazily, never at module import time.** `firestore.Client(...)`,
   `pubsub_v1.PublisherClient()` and `storage.Client(...)` all call
   `google.auth.default()` immediately when instantiated. If that happens as a
   top-level statement in `main.py`, the whole module fails to import — and
   therefore the app never starts — on any ADC hiccup, and the app becomes
   impossible to smoke-test locally without real credentials. Wrap each
   client in an `@lru_cache`-decorated getter function and call the getter
   only from inside the request handler that needs it:
   ```python
   @lru_cache
   def _firestore() -> firestore.Client:
       return firestore.Client(project=GCP_PROJECT, database=FIRESTORE_DATABASE)
   ```
8. **`GET /healthz` must never touch a GCP client.** Cloud Run's own startup
   probe hits this endpoint before the container is marked healthy; it must
   return `200` the instant the process is up, independent of whether
   Firestore/Pub/Sub/GCS are reachable yet. Return a plain static/local check
   only (process alive, config present) — never call a lazy getter from
   `/healthz`.

## Reference

A full, `terraform validate`-clean worked example following this exact
pattern is in [`examples/gcp-fast-stack/`](../../examples/gcp-fast-stack/README.md).
