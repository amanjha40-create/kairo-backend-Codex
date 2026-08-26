# Production Secrets

This document lists the secrets required to run Kairo safely in production on the current FastAPI stack.

Do not commit real values to Git.
Store production secrets in a proper secret manager such as AWS Secrets Manager or SSM Parameter Store.

## Principles

- Use HTTPS-only public endpoints.
- Do not use raw IP addresses for production API or app URLs.
- Use distinct secrets for each environment.
- Rotate secrets on a schedule and immediately after any suspected leak.
- Grant the API and worker only the secrets they actually need.

## Required Secrets

### Core API

| Variable | Required | Used by | Notes |
|---|---|---|---|
| `DATABASE_HOST` | Yes | API, worker | Runtime database host for the canonical application credential. |
| `DATABASE_PORT` | Yes | API, worker | Runtime database port. |
| `DATABASE_NAME` | Yes | API, worker | Runtime database name. |
| `DATABASE_USER` | Yes | API, worker | Dedicated least-privileged runtime DB identity (preferred: `kairo_app` or equivalent). |
| `DATABASE_PASSWORD` | Yes | API, worker | Canonical runtime DB password. |
| `DATABASE_SSLMODE` | Recommended | API, worker | Use `require` or stricter in production. |
| `DATABASE_URL` | Transitional only | API, worker | Supported for controlled transition periods, but not preferred for the steady state. |
| `MIGRATION_DATABASE_HOST` | Recommended | deployment migration task | Separate migration DB host when using a privileged migration identity. |
| `MIGRATION_DATABASE_PORT` | Recommended | deployment migration task | Migration DB port. |
| `MIGRATION_DATABASE_NAME` | Recommended | deployment migration task | Migration DB name. |
| `MIGRATION_DATABASE_USER` | Recommended | deployment migration task | Privileged migration DB identity. |
| `MIGRATION_DATABASE_PASSWORD` | Recommended | deployment migration task | Migration DB password. |
| `MIGRATION_DATABASE_SSLMODE` | Recommended | deployment migration task | Use `require` or stricter in production. |
| `MIGRATION_DATABASE_URL` | Transitional only | deployment migration task | Optional DSN form for migration automation if structured fields are not yet wired. |
| `JWT_SECRET_KEY` | Yes | API | Use a long random value. Production should use at least 48 characters. |

### Redis

| Variable | Required | Used by | Notes |
|---|---|---|---|
| `REDIS_URL` | Yes | API, worker | Required for auth rate limits, OTP state, and worker idempotency. |

### Email / OTP

| Variable | Required | Used by | Notes |
|---|---|---|---|
| `EMAIL_BACKEND` | Yes | API, worker | Use the approved production provider (`brevo` currently). This is not secret. |
| `EMAIL_SEND_ENABLED` | Yes | API, worker | Must be `true` to permit external delivery. This is not secret. |
| `EMAIL_FROM` | Yes | API, worker | Existing sender setting; use `verify@kairoid.com`. This is not secret. |
| `EMAIL_REPLY_TO` | Yes | API, worker | Reply-to address; use `verify@kairoid.com`. This is not secret. |
| `BREVO_API_KEY` | When `EMAIL_BACKEND=brevo` | API, worker | Store only in the production Secrets Manager namespace. |
| `AWS_REGION` | Yes | API, worker | SES identity region; use `us-east-1`. This is not secret. |

SES does not require SMTP credentials. Grant the ECS API and worker task roles the minimum
`ses:SendEmail` permission for the verified sender identity. Use static AWS credentials only
outside AWS when an IAM role is unavailable, and store those credentials in Secrets Manager.

### Candidate phone OTP

Candidate signup requires both email and phone verification in production. Configure the
AWS SNS adapter; `console` and `staging_fixed` are not production-safe.

Required non-secret environment values:

| Variable | Value | Notes |
|---|---|---|
| `PHONE_OTP_ENABLED` | `true` | Do not disable Candidate phone verification. |
| `PHONE_OTP_BACKEND` | `sns` | Uses `sns:Publish` through the ECS task role. |
| `AWS_REGION` | `us-east-1` | SNS client region. |

No SMS credentials are stored in Secrets Manager for this adapter. The ECS task role must
have the least-privilege `sns:Publish` permission. Configure sender identity/origination
number, SMS spending limits, and any country-specific registration in AWS separately; this
application change does not create those resources automatically.

### AWS / Object Storage

These are required if document uploads are enabled in production.

| Variable | Required | Used by | Notes |
|---|---|---|---|
| `AWS_REGION` | Yes | API, worker | AWS region for S3 and SQS clients. |
| `AWS_ACCESS_KEY_ID` | Maybe | API, worker | Not needed if using an IAM role. |
| `AWS_SECRET_ACCESS_KEY` | Maybe | API, worker | Not needed if using an IAM role. |
| `S3_DOCUMENTS_BUCKET` | Yes | API | Private bucket for uploaded documents. |

### Queue / Worker

These are required if the worker runs in production, which it should for async workloads.

| Variable | Required | Used by | Notes |
|---|---|---|---|
| `SQS_MAIN_QUEUE_URL` | Yes | API, worker | Main queue for async jobs. |
| `SQS_DLQ_URL` | Recommended | Worker | Dead-letter queue for failed messages. |

### OAuth Providers

Set only the providers you actually enable.

| Variable | Required | Used by | Notes |
|---|---|---|---|
| `GOOGLE_CLIENT_ID` | If Google auth enabled | API | Must match production redirect URI. |
| `GOOGLE_CLIENT_SECRET` | If Google auth enabled | API | Keep secret. |
| `LINKEDIN_CLIENT_ID` | If LinkedIn enabled | API | Optional today. |
| `LINKEDIN_CLIENT_SECRET` | If LinkedIn enabled | API | Optional today. |
| `GITHUB_CLIENT_ID` | If GitHub enabled | API | Optional today. |
| `GITHUB_CLIENT_SECRET` | If GitHub enabled | API | Optional today. |

## Recommended Secret Handling

### Target database secret architecture

- Runtime application secret:
  - one canonical secret only
  - structured DB fields preferred over an opaque DSN
  - read by API and worker runtime only
- Migration secret:
  - separate privileged identity where practical
  - read only by deployment / migration automation
- RDS-managed master secret:
  - reserved for database administration and recovery
  - not duplicated into the runtime application secret
- Do not keep the runtime application password as an independently copied mirror of the RDS master password.

- Prefer IAM roles over static AWS credentials.
- Keep DB passwords, JWT secrets, static AWS credentials, and OAuth secrets out of `.env.example`.
- Restrict who can read production secrets.
- Audit access to secret stores.
- Scope ECS runtime secret access to the exact secret ARNs required by the service.

## Production-Safe Defaults to Pair With Secrets

These are not secrets, but they matter for safe production operation:

- `APP_ENV=production`
- `DOCS_ENABLED=false`
- `EMAIL_BACKEND=brevo`
- `EMAIL_SEND_ENABLED=true`
- `EMAIL_REPLY_TO=verify@kairoid.com`
- `AWS_REGION=us-east-1`
- `APP_PUBLIC_BASE_URL=https://api.kairoid.com`
- `INSTITUTION_PORTAL_BASE_URL=https://institution.kairoid.com`
- `ADMIN_PORTAL_BASE_URL=https://admin.kairoid.com`
- `CORS_ORIGINS` includes `https://admin.kairoid.com`
- `TRUSTED_HOSTS=api.kairoid.com`
- `PHONE_OTP_BACKEND=sns`
- `CONTROLLED_TESTING=false`
- `JOB_BACKEND=sqs`

Never inject `STAGING_PHONE_OTP_CODE` or any `kairo/staging/*` secret reference into a production task.

## Rotation Safety Notes

- Rotation is not complete when a secret value changes; it is complete only after:
  - a fresh connection with the new credential succeeds
  - a new ECS task revision starts with the new secret
  - `/api/v1/health/ready` passes
  - the new task reaches steady-state health behind the load balancer
- Database-related exception logs must redact passwords and credential-bearing DSNs before they reach CloudWatch.
- Runtime and migration identities should be rotated independently when they are separate principals.

## Minimum Deployment Requirement

Before serving production traffic:

1. Load secrets for the API container.
2. Load the same required infrastructure secrets for the worker container/process.
3. Run database migrations.
4. Start the API only after migrations succeed.
5. Start the worker so queued jobs do not accumulate unprocessed.
