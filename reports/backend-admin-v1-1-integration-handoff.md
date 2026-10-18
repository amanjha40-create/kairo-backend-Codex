# Backend Admin V1.1 integration handoff

## Source lineage

- **HR backend parent SHA:** `5b6edb13c4b09c64a146d9759046fc182afeff3b`
- **HR parent branch:** `codex/backend-hr-v2-contracts`
- **HR schema:** `092`
- **Admin backend branch:** `codex/backend-admin-v1-1-contracts`
- **Admin backend final SHA:** the immutable pushed branch-tip SHA recorded in the delivery
  certification response. A Git commit cannot embed its own eventual hash in its contents.
- **Admin schema:** `093`
- **Separate Backend V1.1 hardening SHA to integrate later:**
  `43c4683795a7ee961a84a7c545da68e90d8f58e1`
- **Hardening integration status:** deliberately not merged here.

The Admin branch was created from the exact certified HR SHA, not Production schema 091, not
`473811f...`, and not the separate hardening commit. Migration `093` has the single
`down_revision="092"` edge.

## Implemented contract set

1. Admin-managed Candidate creation with explicit `admin_created_unclaimed` →
   `activation_pending` → `claimed` state.
2. Hashed, expiring, versioned, revocable, single-use Candidate activation with Candidate-selected
   password and no Admin credential exposure.
3. Existing Resume parser/review/import reuse with distinct CV/Admin confirmation provenance.
4. Field-level append-only assisted-profile provenance, Candidate confirmation, and lower-confidence
   overwrite protection.
5. Admin organization provisioning without implicit owner/member or completed setup.
6. First-HR owner bootstrap through the certified Team Invitation rotation, delivery, and
   acceptance lifecycle.
7. Private evidence reuse and structured Court result/finalization persistence.
8. Automatic Court projection into the certified HR V2 Verification Report.
9. Policy-limited in-person identity/document observations that never mutate canonical verification
   or Permanent Address progress.
10. Seven separated Admin permissions plus Candidate/public claim surfaces.

The exact API shapes and frontend invalidation rules are in
`reports/admin-v1-1-backend-contract-handoff.md`.

## Migration certification

- One Alembic head: `093`.
- PostgreSQL 16.15 ARM64: explicit `091 → 092 → 093` passed.
- PostgreSQL 18.3 ARM64: explicit `091 → 092 → 093` passed.
- Separate `092 → 093` rehearsal passed on PostgreSQL 16.15.
- Migration is additive: new nullable/default-safe columns, new tables, checks, foreign keys,
  indexes, and unique idempotency constraints. No Production migration or data rewrite occurred.

## Test certification

- Focused Admin Operations tests: `7 passed`.
- HR V2 focused regression: `38 passed`.
- Full PostgreSQL 16.15 suite: `2736 passed`.
- Full PostgreSQL 18.3 suite: `2736 passed`.
- Both full runs used the ARM64 development image with real isolated Postgres/Redis and no real
  email, SMS, provider, AWS, or Production service call.
- New-file Ruff suite, Python compile, OpenAPI generation, and `git diff --check` are required final
  gates and are recorded in the delivery response.

## Likely overlap with later Backend V1.1 hardening integration

Resolve these deliberately when integrating `43c4683795a7ee961a84a7c545da68e90d8f58e1`:

- `app/models/user.py`: account lifecycle/security columns and deletion/contact behavior.
- `app/models/organization.py` and `app/models/organization_invitation.py`: provisioning,
  invitation token state, and first-owner metadata.
- `app/models/resume_record_provenance.py` and `app/services/resume_review_service.py`: CV import
  provenance and verified-record protection.
- `app/services/organization_service.py` and `app/services/workspace_service.py`: Team Invitation
  rotation/delivery/acceptance. Keep the HR V2 secure token lifecycle as the single implementation.
- `app/services/hr_v2_service.py` and `app/schemas/hr_v2.py`: Verification Report projection.
  Preserve the Court structured fields and truthful no-match language.
- `app/core/permissions.py`, `app/auth/deps.py`, and Admin route guards: merge permission catalogs
  without replacing separated Admin Operations capabilities with role-only checks.
- `app/api/dependencies/services.py`, `app/api/v1/router.py`, `app/services/__init__.py`, and
  `app/models/__init__.py`: registration/aggregation files likely to conflict mechanically.
- `app/integrations/email/renderer.py`, `app/integrations/email/templates/__init__.py`, and
  `app/schemas/email_delivery.py`: preserve Candidate activation audit redaction and Team Invitation
  delivery reuse.
- Alembic migrations and tests that assert the single expected head. The integrated graph must be
  rebased/renumbered linearly if the hardening branch adds a competing successor to 091/092.
- Repository head assertions in `tests/test_digilocker_identity.py`,
  `tests/test_digilocker_migration.py`, and `tests/test_repository_hygiene.py`.

## Integration invariants

- Preserve `093` as an additive successor to `092`, or renumber it only as part of a deliberate
  linear integration migration. Never create two heads.
- Existing users default to `claim_status=claimed`; do not reinterpret historical accounts as
  unclaimed.
- Candidate claim state must remain independent from email/phone verification fields.
- Never add an Admin password input/response for Candidate or HR provisioning.
- Never persist or log raw activation/invitation tokens.
- `admin_entered`, `cv_extracted`, `candidate_confirmed`, and `source_verified` must remain distinct.
- Court `no_match_found` is scoped source output, not criminal clearance or police verification.
- In-person observations must continue to report `changes_canonical_verification_status=false` and
  `permanent_address_check_credit=0`.
- Permanent Address approved-document + three separate server-day checks remains unchanged.

## Boundary attestation

- No Production backend worktree was modified.
- No certified HR backend worktree was modified.
- No separate Backend V1.1 hardening worktree was modified.
- No Production DB or AWS account was accessed or mutated.
- No deployment, ECR publication, real activation/team email, SMS/OTP, DigiLocker/e-Aadhaar,
  Amazon Location, or GPS action occurred.
