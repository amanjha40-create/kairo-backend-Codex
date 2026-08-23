# Kairo Admin v1.0.0 Production Release Runbook

This runbook is the controlled procedure for releasing the shared backend and standalone Admin
frontend. It does not authorize a release. Production work requires an explicit ADMIN-PROD approval,
a named release operator, and a second approver.

## Release Identity

Resolve release inputs from immutable annotated tags. Never deploy an uncommitted checkout, branch
name, mutable image tag, or local-only artifact.

| Component | Tag | Canonical branch | Repository |
|---|---|---|---|
| Backend | `admin-v1.0.0-backend` | `codex/kairo-v1-staging-consolidated` | `git@github.com:amanjha40-create/kairo-backend-Codex.git` |
| Admin frontend | `admin-v1.0.0-frontend` | `codex/admin-verification-operations` | `git@github.com:amanjha40-create/kairo-admin-portal.git` |
| Database | Alembic `070` | Backend tag | Shared production PostgreSQL |

At launch, record the full SHAs resolved by `git rev-list -n 1 <tag>`, prove each with
`git cat-file -e <sha>^{commit}`, and record the backend image digest returned by ECR.

## Required Approvals

- Product owner approval for ADMIN-PROD.
- Backend release operator and independent reviewer.
- Database migration and recovery checkpoint approval.
- Infrastructure approval for task definition, secrets, security headers, Amplify, domain and DNS.
- Approved Admin account owner for the non-destructive production smoke.

## Configuration Manifest

Never put values from Secrets Manager, passwords, tokens, DSNs or provider keys in this file,
terminal transcripts, tickets or Git. Record only variable names, source references and rotation
versions in the private release record.

### Required Backend Values

| Variable | Source | Release requirement | 2026-08-23 task `kairo-backend:16` audit |
|---|---|---|---|
| `APP_ENV` | ECS environment | `production` | Present |
| `DATABASE_URL` | Production Secrets Manager | Async Postgres, non-loopback, TLS required | Present; TLS mode must be verified privately |
| `REDIS_URL` | Production secret or ECS environment | Production `rediss://` endpoint | Present |
| `JWT_SECRET_KEY` | Production Secrets Manager | Dedicated production secret, at least 48 characters | Present |
| `APP_PUBLIC_BASE_URL` | ECS environment | `https://api.kairoid.com` | Blocked: HTTP ALB URL |
| `ADMIN_PORTAL_BASE_URL` | ECS environment | `https://admin.kairoid.com` | Missing |
| `EMPLOYER_PORTAL_BASE_URL` | ECS environment | Approved production verifier frontend | Investigate before release |
| `CORS_ORIGINS` | ECS environment | Explicit HTTPS origins including Admin; no wildcard/paths/localhost | Admin present |
| `CORS_ALLOW_CREDENTIALS` | ECS environment | Explicit approved value | Missing; defaults false |
| `TRUSTED_HOSTS` | ECS environment | Includes `api.kairoid.com` | Missing |
| `DOCS_ENABLED` | ECS environment | `false` | Blocked: true |
| `DATABASE_ECHO_SQL` | ECS environment | `false` | Optional/absent; safe default |
| `LOG_LEVEL` | ECS environment | Not `DEBUG` | Present |
| `LOG_JSON` / `LOG_ACCESS_ENABLED` | ECS environment | `true` | Present |
| `APP_GIT_SHA` | Immutable build/deploy metadata | Full release commit SHA | Missing |
| `APP_BUILD_ID` | Immutable build/deploy metadata | Release build identifier | Missing |
| `APP_DEPLOYED_AT` | Deploy metadata | ISO-8601 UTC timestamp | Missing |
| `AWS_REGION` | ECS environment | Production AWS region | Present |
| `AWS_ENDPOINT_URL` | Must be absent | No LocalStack/custom override | Absent |
| `S3_DOCUMENTS_BUCKET` | ECS environment | Private production bucket | Present |
| `JOB_BACKEND` | ECS environment | `sqs` | Blocked: inline |
| `SQS_MAIN_QUEUE_URL` | ECS environment | Production main queue | Missing |
| `SQS_DLQ_URL` | ECS environment | Production dead-letter queue | Missing |
| `EMAIL_BACKEND` | ECS environment | Approved production provider | Present: Brevo |
| `BREVO_API_KEY` | Production Secrets Manager | Production namespace only | Present |
| `EMAIL_SEND_ENABLED` | ECS environment | Approved production value | Present |
| `EMAIL_FROM` / `EMAIL_REPLY_TO` | ECS environment | Approved Kairo addresses | Present |
| `PHONE_OTP_ENABLED` | ECS environment | `true` for Candidate signup | Default true; make explicit |
| `PHONE_OTP_BACKEND` | ECS environment | `sns` | Blocked: staging_fixed |
| `CONTROLLED_TESTING` | ECS environment | `false` | Blocked: true |
| `STAGING_PHONE_OTP_CODE` | Must be absent | Staging-only secret | Blocked: staging secret reference |
| `RESUME_PROCESSING_ENABLED` | ECS environment | Explicit product decision | Unknown/investigate |
| `BEDROCK_MODEL_ID` | ECS environment | Required only if resume processing enabled | Conditional |
| OAuth client IDs/secrets and redirect URIs | ECS + production secret store | Required only for enabled providers; HTTPS callbacks | Conditional/investigate |

### Required Frontend Build Values

| Variable | Required value | Source |
|---|---|---|
| `VITE_APP_ENV` | `production` | Amplify app environment |
| `VITE_ADMIN_DEMO_MODE` | `false` | Amplify app environment |
| `VITE_API_BASE_URL` | `https://api.kairoid.com` | Amplify app environment |
| `NITRO_PRESET` | `aws_amplify` | Branch environment or build default |

The production branch currently inherits the three correct public `VITE_*` values from the Amplify
app. Do not add credentials or private configuration to any `VITE_*` variable.

## Pre-Flight

1. Confirm both annotated tags exist on the exact GitHub remotes and resolve to reviewed commits.
2. Confirm both canonical branches and release checkouts are clean and at origin parity `0/0`.
3. Re-run backend tests, migration rehearsal, frontend tests and both production/staging builds.
4. Capture current production ECS service/task/image digest and current Amplify main job.
5. Query the production Alembic revision read-only and record it. Do not infer it from task revision.
6. Confirm every required configuration item above and remove every staging-only reference.
7. Confirm production RDS automated backups are current and create an explicitly approved pre-release
   manual snapshot. Record snapshot ID and successful restore-check ownership.
8. Confirm production RDS deletion protection and ECS deployment circuit breaker decisions. Both were
   disabled during the 2026-08-23 audit and require explicit infrastructure approval.
9. Confirm Redis, S3, SQS, Brevo/SNS IAM and connectivity prerequisites.
10. Confirm a rollback decision owner, monitoring owner and approved smoke-test Admin actor are present.

Any failed or unknown pre-flight item is a release stop.

## Backend Build And Release

1. Check out the backend annotated tag in a clean release worktree.
2. Resolve the full release SHA and prove it is a Git commit.
3. Build the default `runtime` Docker stage for `linux/arm64`, passing `APP_GIT_SHA` and
   `APP_BUILD_ID` as the full SHA and setting the OCI revision label.
4. Scan the image filesystem, history and labels. It must not contain `.env`, Git/SSH credentials,
   tests, QA scripts, local databases, recovery archives or development dependencies.
5. Push one immutable full-SHA tag to ECR and record its registry digest. Production task definitions
   should pin the digest, not a mutable tag.
6. Register a new production task definition from an approved, secret-free JSON template. Inject
   secrets only by Secrets Manager/SSM references and set the exact provenance variables.
7. Do not update the service yet.

## Database Migration

1. Start an isolated one-off migration task using the exact release image, production network and
   production secret references. Override its command to `alembic upgrade 070`.
2. Run it before the new API service rollout and wait for a successful exit.
3. Query the revision read-only and require exactly `070`.
4. Stop immediately on any migration failure. Do not update the ECS service.

Migrations `057–070` are additive or relax nullability except for bounded backfills and enum changes.
Risk classification:

- Medium: `057` (column/default/check/index), `062` (foreign keys/indexes), `063` (PostgreSQL enums),
  `065` (enum plus data backfill), `067` (users backfill plus tables/indexes), `068` (multiple tables/indexes).
- Low: `058–061`, `064`, `066`, `069`, `070`.

Schedule migration work with enough time for locks on populated tables. Measure the production row
counts before launch. Migration `065` changes canonical verification truth; after it runs, forward
recovery is preferred. Do not automatically downgrade PostgreSQL enum changes, and do not roll the
application back to an image that cannot read `verified`, `unable_to_verify`, or Admin quality-review
states.

## Backend ECS Rollout

1. Update `kairo-backend` to the approved digest-pinned task definition.
2. Wait for ECS stability and ALB target health while retaining the prior task definition.
3. Require `/api/v1/health/live` and `/api/v1/health/ready` to return `200` through
   `https://api.kairoid.com`.
4. Verify System Operations reports Git SHA/build ID equal to the release and migration `070`.
5. Inspect CloudWatch for ERROR, Traceback, HTTP 500, DB, Redis, serialization and auth failures.

## Frontend Release

1. Check out the frontend annotated tag in a clean release worktree.
2. Build with the four required production values and run the artifact scanner.
3. Verify `.amplify-hosting` contains compute, static assets and the catch-all manifest.
4. Deploy the exact tagged commit to the approved production Amplify branch.
5. Keep the existing `admin.kairoid.com` association attached to that branch; do not change DNS during
   the application rollout unless the recorded CNAME target has changed.
6. Verify managed TLS, security headers, CSP, no-store HTML, deep links and API origin before login.

## Production Smoke

The initial smoke is read-only except for login/logout:

1. `https://admin.kairoid.com/admin/login` loads with valid TLS.
2. Approved Admin login succeeds and session restoration works.
3. Overview, Verifications, Registry, Users, Communications, Notifications, Trust & Safety, System
   Operations and Settings load.
4. Direct deep links and hard refresh work.
5. API live/ready return `200`; runtime SHA/build and migration are exact.
6. Browser console has no uncaught errors, CSP violations or missing assets.
7. CloudWatch has no unexpected 5xx or backend exceptions.
8. Logout clears the session and protected-route revisit redirects to login.

Extended acceptance remains read-only. Any production mutation requires separate approval and a named
test entity; never repeat destructive staging acceptance against real production data.

## Release Stop And Rollback Thresholds

Stop or rollback immediately for migration failure, readiness failure, SHA/build mismatch, wrong API
origin, Admin authentication/session failure, critical route outage, secret exposure, unexpected
widespread 5xx, data-truth regression, or CSP/header breakage that makes the portal unusable.

### Before Migration

Rollback is straightforward: do not run the migration, keep the current ECS task and Amplify job, and
discard the candidate task definition.

### After Migration

Prefer forward recovery. Roll back backend code only after confirming the prior image accepts the new
schema and enum values. Never automatically downgrade migrations `063` or `065`; their enum labels are
intentionally retained. If compatibility is uncertain, keep the release image, disable frontend
promotion, and deploy a reviewed forward fix.

### ECS Mechanics

Record the current and previous task definition ARNs and image digests before release. A compatible
rollback uses `aws ecs update-service` with the recorded prior task definition followed by the ECS
stability waiter and full health checks. The 2026-08-23 audit found the deployment circuit breaker
disabled, so automatic rollback must not be assumed.

### Amplify Mechanics

Record the current main job/commit before release. Restore the previous known-good commit by reverting
or creating a release branch at that commit and starting a new Amplify job. Do not force-update Git
history or detach the custom domain. Verify the job source commit before accepting the rollback.

## Monitoring Window

For at least the agreed release observation window, assign an operator to watch ECS/ALB health,
CloudWatch ERROR/Traceback/500 counts, Admin login and request failures, PostgreSQL/Redis connectivity,
SQS backlog/DLQ, and Brevo/SNS delivery errors. System Operations is the application-level source for
dependency state, runtime provenance, migration revision and retryable failures.

## Domain And TLS

`admin.kairoid.com` is already associated with Amplify `main` and resolves through the recorded
CloudFront CNAME. The domain uses an Amplify-managed certificate. DNS is externally hosted on the
`registrar-servers.com` nameservers; changes require manual external approval. Preserve the ACM
validation CNAME. Amplify redirects/serves over HTTPS; the repository supplies HSTS and browser
security headers through `customHttp.yml` plus an environment-specific SSR CSP.

## Invitation And Support URLs

With `ADMIN_PORTAL_BASE_URL=https://admin.kairoid.com`, Admin invitation email CTA generation must
produce `https://admin.kairoid.com/admin/accept-invitation#token=...`. The raw token remains only in the
URL fragment and email body; it must not appear in API lists, audit payloads or logs. Rehearse rendering
with a fake sender and do not send a production email. The intentional support contact is
`support@kairoid.com`; legal-link ownership remains a compliance approval item rather than a launch-time
code invention.

## Infrastructure Change Inventory

| Change | Classification |
|---|---|
| Build/push immutable backend image | Automatable after approval |
| Replace production task configuration and secret references | Manual approval required |
| Run migration to `070` | Manual approval required |
| ECS service rollout and health waiter | Automatable after approval |
| Amplify tagged frontend deployment | Manual approval required |
| Preserve/verify Admin custom domain and certificate | Manual approval required |
| External DNS changes, if the recorded CNAME changes | Manual external action |
| RDS manual snapshot and recovery checkpoint | Manual approval required |
| Security-header verification | Automatable validation |

## Final Go/No-Go Record

Record `PASS`, `BLOCKED`, or `MANUAL AT RELEASE` for source, tests, migration, backup, backend config,
frontend config, CORS, security headers, image, ECS, Amplify, domain, DNS, TLS, login, health,
provenance, rollback, runbook, monitoring and approval. A `BLOCKED` item means no production action.
