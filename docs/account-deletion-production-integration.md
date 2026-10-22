# Production Source Reconciliation

## Provenance

- Production API46 baseline: `3248363d574bf1f7a2ceb59742372712ec2e45d5`.
- Certified ownership-deletion and migration harness: `abb61389cf0279ae05e706e6b114a8b7cb8609c8`, a direct descendant of that baseline.
- Worker15 source label: `65cf7d342def37229e9e3acf6dae7231631cf660`. This Git object was unavailable locally and from the configured remote; the authoritative comparison used its pinned runtime image, `sha256:59d5bf27869fefa1b9242bee2f1f68c356797eca9db64454b87ca0d7b25fbfef`, locally with networking disabled.
- Integration branch starts from API46 and fast-forwards only the three certified feature/harness commits before adding the reconciled worker delta.

## Semantic Reconciliation

| File / function | Resolution |
| --- | --- |
| `app/workers/consumer.py`, `_process_message`, `_defer_message` | Preserve Worker15 visibility deferral, transaction rollback, idempotency release before visibility change, no acknowledgement of deferred work, and ordinary duplicate acknowledgement. |
| `app/workers/defer.py`, `DeferMessage` | Restore the bounded 1-43,200 second deferral signal. |
| `app/workers/handlers/account_deletion.py`, `purge_account`, `_defer_seconds` | Preserve Worker15 due-time/concurrent-claim deferral around the integrated canonical purge service. Missing, complete and operator-review requests are not deferred. |
| `app/services/account_deletion_service.py` | Preserve certified atomic ownership resolution before personal deletion commit. |
| `app/services/account_deletion_policy.py` | Preserve certified activation/reference cleanup; do not replace it with the older worker image's copy. |
| `app/services/account_deletion_purge.py`, `permitted_scope`, `sweep_deletions` | Preserve certified closed-organization namespace ownership guards and normal durable cleanup/review transitions. |

The three restored worker modules, recurring sweeper, recovery service, inventory and telemetry match the pinned Worker15 image at syntax-tree level (normalizing import-name ordering). Recovery's due-time and operator-review guards are unchanged.

API46 Passport public URL, DigiLocker return/document classification, Vault explicit-null and Employment evidence-policy implementations remain unchanged. No unrelated differences from the older Worker15 image were imported.

## Validation

- Focused regression: **456 passed**, including 19 new worker durability cases, ownership/rollback/idempotency, recovery/telemetry, migration configuration/094 SQL generation, Passport, DigiLocker, Vault-null and Employment policy.
- One broader backend run: **3,045 passed**, 36 deprecation warnings, on isolated local PostgreSQL.
- New/edited worker files and new tests: Ruff passes. `git diff --check` passes.
- Wider lint scan of integration-affected files: 42 inherited findings, versus 45 in the certified snapshot; zero new findings. This is not a claim of repository-wide lint cleanliness.
- Migration 094 and certified ownership-deletion implementations remain unchanged. Local metadata/head/SQL tests pass; no remote migration or new migration round-trip was run here.

## Boundary

No AWS operations, schedule changes, deployment, Production migration, or deletion canary occurred during this reconciliation task. No mobile changes were made. Deployment, Production IAM/configuration preflight and the separately approved canary remain separate gates. The Staging logo permission grant covers one synthetic organization only and is not evidence of Production cleanup-role readiness.
