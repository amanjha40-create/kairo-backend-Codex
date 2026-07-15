# Production Environment

This document describes the non-secret production environment shape for the current FastAPI backend.

Use it together with [production-secrets.md](/Users/Aman/Documents/New%20project/kiaro-backend-main/docs/production-secrets.md).

## Production Rules

- Public traffic must terminate over HTTPS.
- Do not expose the API to users through a raw IP address.
- Do not run with `DOCS_ENABLED=true` in production.
- Run database migrations before serving traffic.
- Run the SQS worker in production if async jobs are enabled.

## Recommended Production Variables

These values are examples and are intentionally placeholders.

```env
APP_ENV=production
APP_NAME=kairo-backend
APP_VERSION=0.1.0
API_V1_PREFIX=/api/v1
HOST=0.0.0.0
PORT=8000

LOG_LEVEL=INFO
LOG_JSON=true
LOG_ACCESS_ENABLED=true

EMAIL_BACKEND=ses
EMAIL_SEND_ENABLED=true
EMAIL_FROM=verify@kairoid.com
SES_FROM_EMAIL=verify@kairoid.com
AWS_REGION=us-east-1

DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=20
DATABASE_POOL_TIMEOUT=30

REDIS_MAX_CONNECTIONS=100
REDIS_SOCKET_CONNECT_TIMEOUT=5
REDIS_SOCKET_TIMEOUT=5
REDIS_HEALTH_CHECK_INTERVAL=30
REDIS_REQUIRED_FOR_READY=true

JWT_ALGORITHM=HS256
JWT_ACCESS_TTL_MINUTES=15
JWT_REFRESH_TTL_DAYS=7

SIGNUP_OTP_TTL_SECONDS=600
SIGNUP_OTP_RESEND_COOLDOWN_SECONDS=30
SIGNUP_OTP_MAX_VERIFY_ATTEMPTS=5
SIGNUP_OTP_MAX_SENDS_PER_HOUR=5
SIGNUP_PENDING_TTL_HOURS=24

APP_PUBLIC_BASE_URL=https://api.kairo.example
EMPLOYER_PORTAL_BASE_URL=https://app.kairo.example
EMPLOYER_VERIFICATION_TOKEN_TTL_HOURS=168

S3_PRESIGNED_PUT_TTL_SECONDS=600
S3_DOCUMENT_KEY_PREFIX=employment-verification
S3_ALLOWED_UPLOAD_CONTENT_TYPES=application/pdf,image/jpeg,image/png,image/webp
EMPLOYMENT_MAX_UPLOAD_BYTES=15000000

SQS_RECEIVE_WAIT_SECONDS=20
SQS_MAX_MESSAGES_PER_POLL=10

CORS_ORIGINS=https://app.kairo.example
CORS_ALLOW_CREDENTIALS=false
DOCS_ENABLED=false
TRUSTED_HOSTS=api.kairo.example
```

## Variables That Must Point to HTTPS Hosts

- `APP_PUBLIC_BASE_URL`
- `EMPLOYER_PORTAL_BASE_URL`
- any production web app origin included in `CORS_ORIGINS`
- any production OAuth redirect targets

Do not use:

- `http://...`
- public raw IPs such as `http://1.2.3.4:8000`

## Variables Shared By API and Worker

The worker should receive the same infrastructure connectivity configuration as the API where relevant:

- `APP_ENV`
- `DATABASE_URL`
- `REDIS_URL`
- `AWS_REGION`
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` or IAM role
- `AWS_ENDPOINT_URL` only if intentionally using a custom endpoint
- `SQS_MAIN_QUEUE_URL`
- `SQS_DLQ_URL`
- `LOG_LEVEL`
- `LOG_JSON`

## Variables Intended for API Only

- `HOST`
- `PORT`
- `CORS_ORIGINS`
- `CORS_ALLOW_CREDENTIALS`
- `DOCS_ENABLED`
- `TRUSTED_HOSTS`
- OAuth redirect URIs

## Production Preflight Checklist

Before promoting a release:

1. Confirm the frontend points to an HTTPS API hostname.
2. Confirm `DOCS_ENABLED=false`.
3. Confirm `APP_PUBLIC_BASE_URL` is an HTTPS hostname, not a raw IP.
4. Confirm `TRUSTED_HOSTS` contains the production API hostname.
5. Confirm the API and worker IAM roles can call SES and `EMAIL_BACKEND=ses`.
6. Confirm `SES_FROM_EMAIL=verify@kairoid.com` and the SES identity is verified in `AWS_REGION`.
7. Confirm `S3_DOCUMENTS_BUCKET` is private and available.
8. Confirm `SQS_MAIN_QUEUE_URL` is set if the worker is expected to process jobs.
9. Run `alembic upgrade head` before serving traffic.

## Short-Term Token Strategy

Week 1 decision only, no implementation here:

- keep the existing FastAPI auth stack
- keep short-lived access tokens
- keep refresh-token rotation and reuse detection
- plan to move web refresh tokens to `HttpOnly` secure cookies and keep access tokens out of persistent browser storage as the safest short-term direction

That token change belongs to a later implementation step, not this documentation-only hardening step.
