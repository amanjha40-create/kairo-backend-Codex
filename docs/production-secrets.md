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
| `DATABASE_URL` | Yes | API, worker | Production Postgres DSN using `postgresql+asyncpg://` |
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
| `EMAIL_REPLY_TO` | Yes | API, worker | Support reply address; use `support@kairoid.com`. This is not secret. |
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

- Prefer IAM roles over static AWS credentials.
- Keep `DATABASE_URL`, `JWT_SECRET_KEY`, static AWS credentials, and OAuth secrets out of `.env.example`.
- Restrict who can read production secrets.
- Audit access to secret stores.

## Production-Safe Defaults to Pair With Secrets

These are not secrets, but they matter for safe production operation:

- `APP_ENV=production`
- `DOCS_ENABLED=false`
- `EMAIL_BACKEND=brevo`
- `EMAIL_SEND_ENABLED=true`
- `EMAIL_REPLY_TO=support@kairoid.com`
- `AWS_REGION=us-east-1`
- `APP_PUBLIC_BASE_URL=https://api.kairoid.com`
- `ADMIN_PORTAL_BASE_URL=https://admin.kairoid.com`
- `CORS_ORIGINS` includes `https://admin.kairoid.com`
- `TRUSTED_HOSTS=api.kairoid.com`
- `PHONE_OTP_BACKEND=sns`
- `CONTROLLED_TESTING=false`
- `JOB_BACKEND=sqs`

Never inject `STAGING_PHONE_OTP_CODE` or any `kairo/staging/*` secret reference into a production task.

## Minimum Deployment Requirement

Before serving production traffic:

1. Load secrets for the API container.
2. Load the same required infrastructure secrets for the worker container/process.
3. Run database migrations.
4. Start the API only after migrations succeed.
5. Start the worker so queued jobs do not accumulate unprocessed.
