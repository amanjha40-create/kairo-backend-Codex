# Production Clean-Slate Dry Run

Status: planning only. No Production deletion or mutation is authorized by this document.

Evidence date: 2026-10-25 (Asia/Kolkata)

Baseline:

- API56 / Worker20 / DB096
- Backend source `9e3812514fe296e2611f121319f2d97bb55433fe`
- Production census executed over TLS in `BEGIN READ ONLY`
- Census task exited 0 and its network attachment was released
- S3 inventory was read-only

## Non-Negotiable Safety Rules

1. Do not truncate, reinitialize, downgrade, or replace the database.
2. Preserve DB096, all schema and migration history, application/provider configuration,
   IAM/ECS/ALB configuration, and the sole active admin identity.
3. Do not execute a reset until distributed-build smoke testing is complete, a maintenance
   window is active, backups are proven restorable, and every organization has an explicit
   founder disposition.
4. Use opaque database IDs in the execution manifest. Do not select users by an email pattern.
5. Reuse the canonical account-deletion inventory, scrubbing, organization-resolution,
   session revocation, Passport revocation, and durable object-purge code. Do not replace it
   with ad-hoc table deletes.
6. Do not purge SQS queues. Let exact deletion requests complete and require queue/DLQ zero.
7. The documents bucket is unversioned. No S3 deletion may begin until a restorable backup or
   immutable object snapshot has been verified.
8. Any count, ownership, or storage mismatch is a stop condition.

## Read-Only Census

### Accounts And Authentication

| Category | Count |
| --- | ---: |
| Active admin users | 1 |
| Active non-admin users | 9 |
| Deleted non-admin tombstones | 11 |
| Total user rows | 21 |
| Password-configured users | 10 |
| Social-linked users | 1 |
| Refresh-token rows | 397 |
| Active refresh tokens | 15 |
| Pending-signup rows | 12 |
| Password-reset tokens | 4 |

The required admin is opaque identity `60457273fc8c`, role `admin`, active, email-verified,
and password-configured. It is also the sole active owner of both active organizations. There
are no separate service-account rows in the `users` table. AWS service roles and deployment
identities are external system configuration and must not be changed by the reset.

### Candidate Career, Resume, And Documents

| Category | Count |
| --- | ---: |
| Employments | 9 (8 active-user owned; 1 retained deleted-user record) |
| Educations | 13 |
| Internships | 2 |
| Freelance contracts | 0 |
| Gig-platform records | 0 |
| Portfolio items | 0 |
| Certifications | 15 |
| Projects | 7 |
| Skills | 21 |
| Resume documents/jobs/results | 15 / 15 / 15 |
| Resume review sessions/items | 15 / 508 |
| Resume import batches/results | 3 / 54 |
| Resume provenance rows | 54 |
| Employment/Education documents | 2 / 3 |
| Other user-document metadata | 0 |
| Trust-score snapshots | 31 |

All active Career, Resume, document, and trust-score rows are non-admin owned. The one
deleted-user employment row is already retained/scrubbed history and must follow the existing
audit-retention contract rather than being blindly deleted.

### Verification, Notifications, DigiLocker, And Passport

| Category | Count |
| --- | ---: |
| Verification requests | 3 (2 pending admin review; 1 rejected/unlinked) |
| Verification evidence / reviews | 7 / 1 |
| Verification request events / audit events | 17 / 19 |
| DigiLocker connections | 5 (4 active, 1 pending) |
| DigiLocker identity verifications | 7 (4 DL, 3 PAN) |
| Notifications / deliveries / events | 17 / 17 / 49 |
| Active Passport shares | 1 |
| Revoked or expired Passport shares | 2 |
| Passport views | 10 |
| Document share packs/items | 0 / 0 |

The two pending verification requests are active-user owned and purgeable under the existing
account-deletion policy. The rejected request is already unlinked and is retained/scrubbed
verification history. Ten notifications are linked to non-admin users, two to the admin, and
five are unlinked; the unlinked set requires retention review before reset.

### Organizations

| Organization | Type | State | Active members | People | Classification |
| --- | --- | --- | ---: | ---: | --- |
| Kairo | employer | active | 1 admin owner | 1 | Manual review: possible operational/internal organization |
| KairoID Institution QA | other | active | 1 admin owner | 100 | Test/QA indicated, but explicit approval and canonical closure required |
| Kairo | university | closed/suspended | 0 | 0 | Retained closure/audit history |
| Futures First | gig platform | closed/suspended | 0 | 0 | Manual retention review; real-looking external name |
| Kairo Technologies Pvt Ltd | employer | closed/suspended | 0 | 0 | Manual retention review; real-looking company history |

No organization named Goddres was present in this census. That does not make the remaining
organizations disposable. The three closed organizations are linked to deletion history and
must remain closed audit records unless retention counsel explicitly authorizes physical purge.

### Deletion And Operational State

| Category | Count |
| --- | ---: |
| Completed account-deletion requests | 11 |
| Completed account-deletion items | 212 |
| Pending/review deletion items | 0 |
| Overdue deletion requests | 0 |
| Organization deletion resolutions | 3 |

These ledgers are evidence that previous deletions completed and are not clean-slate user data.
Preserve them under the existing retention contract.

### Storage

Production documents bucket current objects: 17 objects, 5,193,104 bytes.

| Canonical class | Objects | Bytes |
| --- | ---: | ---: |
| Resume uploads | 7 | 885,653 |
| User avatars | 4 | 597,814 |
| Employment documents | 2 | 1,001,819 |
| Education documents | 3 | 2,687,986 |
| Certification documents | 1 | 19,832 |

The bucket has versioning disabled, zero delete markers, AES-256 default encryption, and one
enabled 30-day lifecycle rule for organization-roster source objects. Current DB references
match the four non-Resume object classes. Fifteen Resume rows exist but only seven current
Resume objects remain, so execution must reconcile each key and treat already-absent objects
as the canonical idempotent outcome. Do not delete bucket configuration, lifecycle rules,
branding/static assets, or the bucket itself.

### Reference And System State

- `alembic_version`: one row, revision 096.
- Institution catalogue: 43,119 records, version `india-he-v1`, file SHA-256
  `f6c7cbcf98ff9002a8b3d115cea43e88d27f6ccd7e70a42acfb1affcc3858345`.
- Verification connectors: one configured connector.
- Trust registry: one record and one domain; organization/master-data disposition requires
  manual review, while capability definitions are system data.
- Permanent-address geocode budget: one operational counter row.

## Classification

### DELETE_FOR_CLEAN_SLATE

Delete only rows owned by the approved nine active non-admin user IDs, through the canonical
deletion workflow:

- Candidate profile payload embedded in `users` (soft-delete/scrub; retain tombstone).
- `profile_languages`, `profile_links`, owner-side `profile_views`.
- `refresh_tokens`, `password_reset_tokens`, `candidate_activation_tokens`, and
  `user_social_accounts` for target users.
- Candidate notification state: `notification_preferences`, target-user `notifications`, and
  their cascading `notification_deliveries` / `notification_events`.
- `digilocker_connections`, `digilocker_identity_verifications`, and expiring Redis
  transaction state.
- Active Candidate Career rows: `employments`, `educations`, `internships`,
  `freelance_contracts`, `gig_platforms`, `portfolio_items`, `certifications`, `projects`,
  `skills`, and their private document rows, except records retained and scrubbed by the
  verification-audit policy.
- Entire target-user Resume graph: `resume_documents`, `resume_processing_jobs`,
  `resume_parsed_results`, `resume_review_sessions`, `resume_review_items`,
  `resume_import_batches`, `resume_import_results`, and `resume_record_provenance`.
- `trust_score_snapshots`, `user_documents`, permanent-address versions/sessions/reviews,
  target-user Passport shares/views, and document share packs/items.
- Pending-signup rows tied to target email/phone/user, plus separately approved expired,
  incomplete pending signups.
- The 17 current S3 objects only after their ownership is proven in the exact manifest.

Expected clean-slate target for every category above is zero active/private rows or objects.

### PRESERVE_SYSTEM_DATA

- DB096, `alembic_version`, schema, constraints, indexes, and all migration files.
- Institution catalogue application data and provenance.
- `verification_connectors` and connector configuration.
- Static trust-registry capability definitions.
- Permanent-address geocode budgets and other system counters unless their own runbook says
  otherwise.
- Production secrets/provider configuration, Redis/SQS/ECS/ALB/IAM/CloudWatch configuration,
  bucket configuration, encryption, and lifecycle rules.
- The active admin identity and its operational access.
- Application/static/branding assets outside proven user-owned storage scopes.

### PRESERVE_REQUIRED_AUDIT_RETENTION

Preserve and scrub according to the existing deletion policy:

- `account_deletions`, `account_deletion_items`, and `organization_deletion_resolutions`.
- Closed organization rows and their non-content closure/audit evidence.
- Non-purgeable verification requests and dependent audit/events/reviews after private payload
  removal; preserve the existing rejected request unless retention review says otherwise.
- `verification_audit_events`, `user_account_events`, admin access audit, organization activity
  events, roster audit events, and security/investigation/incident records.
- Delivery/operational logs only for the approved retention period and only after required PII
  scrubbing.
- Deleted user tombstones (`Deleted Candidate` contract), not live profiles.

### MANUAL_REVIEW_REQUIRED

- Both active admin-owned organizations and all organization-dependent records.
- The three closed organizations, especially real-looking external/company records.
- The 100-person Institution QA roster and its import/audit history.
- Five unlinked notifications and any unlinked delivery logs.
- The one trust-registry record/domain and its relationship to active/closed organizations.
- Any verification request that is non-purgeable under the canonical policy.
- Pending-signup rows not matched to the approved target-user manifest.
- Any S3 key not proven to belong to an approved target account or approved organization.

## Recommended Mechanism

Use a bounded administrative clean-slate orchestrator that reuses the certified account-
deletion engine. Do not use raw SQL, table truncation, or password resets. The current public
self-service endpoint requires each user's confirmation/password and is therefore unsuitable
as the operator interface, but its inventory, scrubbing, organization-resolution, durable
ledger, and exact-prefix purge semantics are the correct implementation primitives.

The administrative operation must:

1. Accept an immutable allowlist of opaque target user IDs and explicit organization decisions.
2. Deny the admin ID and every protected identity before any write.
3. Generate and persist a dry-run manifest with expected row/object counts and hashes.
4. Create exactly one deletion request per target user and call the same internal deletion
   transaction without weakening the public self-service endpoint.
5. Process users sequentially or in a very small bounded batch; wait for each exact deletion ID.
6. Preserve existing verification/audit retention semantics and idempotency.
7. Emit an operator audit event and a completion manifest.
8. Stop on any unexpected ownership, FK, organization, object, or count difference.

No such bulk operator entry point was proven in the current source. It must be implemented and
Staging-certified before Production reset execution, or every target user must self-delete.

## Dependency-Safe Execution Order

1. **Change freeze and maintenance window**: finish distributed-build smoke; block new signup,
   upload, share, invitation, and verification writes without changing provider credentials.
2. **Backups**: create a manual RDS snapshot and verify PITR; record DB096; capture an immutable
   row-count/ID-hash manifest; create a restorable copy/snapshot of all 17 S3 objects because
   bucket versioning is disabled; record S3 configuration and checksums.
3. **Re-run census**: require exact expected deltas from this document or obtain new approval.
4. **Founder gates**: approve the nine user IDs, every pending-signup disposition, Kairo,
   KairoID Institution QA, all closed organizations, the trust-registry record, and retention
   handling for verification/delivery/audit rows.
5. **Public-access revocation**: revoke target-user Passport/document shares and invitations in
   the same canonical deletion transaction; verify links fail closed.
6. **Organization resolution**: for target users, atomically transfer/close organizations using
   the certified ownership workflow. Do not touch the admin-owned organizations without their
   explicit disposition. If an approved admin-owned test organization must close while the
   admin survives, use a separately tested canonical administrative organization-closure path.
7. **Candidate deletion transactions**: one exact approved user at a time. Purge private rows,
   scrub retained evidence, invalidate auth/social/DigiLocker state, soft-delete the user, and
   create exactly one durable deletion ledger.
8. **Durable object cleanup**: wait at least the maximum presigned-PUT TTL (currently at least
   15 minutes), then run exact deletion-ID sweeps. Require every item complete, no review state,
   and already-absent objects treated idempotently.
9. **Residual signup/notification cleanup**: delete only approved expired/unclaimed signups and
   approved unlinked user-facing notifications; never infer ownership from free text.
10. **Global session boundary**: revoke/remove all refresh and password-reset tokens, including
    admin sessions, then require fresh admin authentication. Preserve the admin identity itself.
11. **Storage reconciliation**: compare the final bucket inventory to the approved manifest.
    Expected user-object count is zero; do not remove the bucket/configuration.
12. **Health and data postflight**: run the checks below. Keep maintenance mode until all pass.

## Predicted Post-Reset State

Assuming all nine active non-admin users are approved and both active organizations are
preserved pending separate decisions:

| Category | Before | Expected after |
| --- | ---: | ---: |
| Active admin users | 1 | 1 |
| Active non-admin users | 9 | 0 |
| Deleted user tombstones | 11 | 20 |
| Total user rows | 21 | 21 |
| Active sessions | 15 | 0 after global session boundary |
| Social identities | 1 | 0 |
| Pending signups | 12 | 0 only after all 12 are explicitly matched/approved |
| Active-user employments | 8 | 0 |
| Retained deleted-user employment | 1 | 1 scrubbed audit record |
| Educations / internships | 13 / 2 | 0 / 0 |
| Certifications / projects / skills | 15 / 7 / 21 | 0 / 0 / 0 |
| Resume documents/jobs/results | 15 / 15 / 15 | 0 / 0 / 0 |
| Resume review sessions/items | 15 / 508 | 0 / 0 |
| DigiLocker connections/verifications | 5 / 7 | 0 / 0 |
| Passport shares/views | 3 / 10 | 0 / 0 |
| Pending verification requests | 2 | 0 |
| Retained rejected verification request | 1 | 1 scrubbed audit record |
| Current S3 user objects | 17 | 0 |
| Completed deletion requests | 11 | 20 |
| Completed deletion items | 212 | `212 + exact new manifest`; must be computed before execution |
| Active organizations | 2 | 2 unless separately approved for canonical closure |
| Closed organization tombstones | 3 | 3 retained |
| Institution catalogue records | 43,119 | 43,119 |
| Alembic revision rows / revision | 1 / 096 | 1 / 096 |

Notification/delivery and organization-dependent after-counts are deliberately not guessed;
they remain manual gates. A future execution must calculate exact per-owner counts before write.

## Post-Reset Validation

### System

- API and Worker desired/running/pending counts healthy.
- `/api/v1/health/live` and `/api/v1/health/ready` return 200 without redirects.
- DB revision remains 096.
- 16/16 Production alarms are `OK`.
- Resume queue and DLQ are empty; deletion/reconciliation queue state is healthy.
- Fresh Overdue metric is zero and observed target 5xx is zero.
- No migration, task-definition drift, secret rotation, provider change, or schedule change.

### Data

- Active non-admin users = 0; active admin = 1; admin can reauthenticate.
- No approved pending signups, active non-admin sessions, social identities, or reset tokens.
- No active old Passport/document shares; every old public URL fails closed.
- Candidate Career/Resume/DigiLocker/private-document rows match the predicted state.
- All exact deletion requests and items are complete; pending/review/overdue = 0.
- User-generated S3 object count = 0 and no unapproved key was touched.
- Institution catalogue remains 43,119 records with the recorded file hash.
- Organizations match the founder-approved disposition; no active organization is ownerless.
- Audit/tombstone rows remain present and scrubbed.

## Fresh-Account Launch Smoke

After the reset and postflight pass, create one new founder-controlled account that has never
appeared in Production. Run each action once unless a retry is explicitly approved:

1. Signup/login and one OTP/authentication flow.
2. Minimum onboarding and canonical DOB/Profile save, refetch, and relaunch.
3. One small synthetic Career record.
4. One synthetic Resume upload through parse and Review; no unrelated import.
5. Institution catalogue selection plus one manual-fallback display check.
6. DigiLocker connection/verification only if provider testing is separately approved.
7. Passport generation.
8. One scope-limited public Passport share and branded PDF; verify excluded sections, expiry,
   revocation, and fail-closed behavior.
9. One in-app notification and unread/read behavior without external delivery unless approved.
10. Logout/login and session persistence.
11. Delete the smoke account through the normal self-service endpoint; verify ledger completion,
    storage cleanup, link revocation, sessions invalidated, queues empty, and Overdue zero.

Minimal HR-to-Candidate smoke is optional and requires a founder-approved synthetic HR
organization. Create one synthetic invitation/request, accept/decline through the normal flow,
verify recipient isolation and status projection, then canonically close or retain the fixture
according to its approved disposition. Do not use a real company/pilot organization.

## Stop Conditions

Stop before the first mutation if any of the following is true:

- No restorable RDS and S3 backup evidence.
- DB is not 096 or deployment/health gates are not green.
- Admin identity cannot be excluded deterministically.
- Any target user or organization is not explicitly approved.
- Any organization may be a real customer/pilot or has an unresolved owner/member.
- Any non-purgeable verification/audit record lacks a retention decision.
- Manifest counts, object hashes, or FK ownership differ from the approved dry run.
- Queue/DLQ is non-empty before execution or a competing deletion is active.
- Canonical organization closure for an approved admin-owned test organization is unavailable.
- Any deletion item reaches review/operator-review or any object falls outside its owned prefix.

## Information Required Before Execution

1. Founder disposition for Kairo and KairoID Institution QA.
2. Retention approval for the three closed organizations and real-looking historical names.
3. Retention decision for unlinked notifications/delivery logs and the rejected verification.
4. Exact approved list of nine active non-admin user IDs and all 12 pending-signup rows.
5. A Staging-certified administrative orchestrator that reuses the canonical deletion engine,
   or confirmation that every target user will self-delete.
6. A canonical admin-preserving organization closure path if either active organization is to
   be removed.
7. RDS snapshot/PITR and S3 restorable-backup evidence.
8. Final distributed Android/iOS smoke completion and an approved maintenance window.

## Administrative Orchestrator Interface

The bounded operator entry point is `python -m app.ops.clean_slate`. It accepts one strict JSON
artifact containing only schema version 1, the exact environment, explicit user, pending-signup,
organization, storage-object fingerprint and protected-identity lists, plus Production backup
evidence. The SHA-256 of the raw artifact is supplied separately; unknown keys, duplicate IDs,
environment drift, DB revision drift, unlisted dependencies, unknown storage ownership and
protected identities fail closed.

Dry run is the default and starts a read-only transaction:

```bash
python -m app.ops.clean_slate \
  --allowlist /secure/path/production-clean-slate-v1.json \
  --allowlist-sha256 '<approved-sha256>'
```

Future Production execution requires all founder gates in this document, the exact dry-run
artifact with its discovered storage fingerprints, a verified AVAILABLE RDS snapshot and
restorable S3 backup, a durable S3 progress location, API/Worker/queue/Overdue health inputs,
and both explicit Production flags:

```bash
python -m app.ops.clean_slate \
  --allowlist /secure/path/production-clean-slate-v1.json \
  --allowlist-sha256 '<approved-sha256>' \
  --execute \
  --confirm-environment production \
  --confirm-production-clean-slate \
  --progress-file /secure/path/production-clean-slate-progress.json \
  --progress-s3-uri 's3://<approved-backup-bucket>/<approved-progress-key>' \
  --ecs-cluster '<production-cluster>' \
  --api-service '<production-api-service>' \
  --worker-service '<production-worker-service>' \
  --live-url 'https://api.kairoid.com/api/v1/health/live' \
  --ready-url 'https://api.kairoid.com/api/v1/health/ready' \
  --overdue-alarm '<production-account-deletion-overdue-alarm>'
```

This command is documentation only. It must not be run until a separately approved maintenance
window and final allowlists/backups exist. The tool calls the canonical per-user deletion
transaction sequentially; durable deletion sweeps remain responsible for due-time physical S3
cleanup and must be certified complete before maintenance mode ends.

