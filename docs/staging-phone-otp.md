# Staging Fixed Phone OTP

`staging_fixed` is an internal-testing phone OTP transport. It preserves the existing
Redis-backed OTP challenge lifecycle while replacing the random phone challenge with a
secret fixed value for explicitly allowlisted testers.

It is valid only when `APP_ENV=staging`. Application startup rejects it in production.

## Required staging configuration

```env
APP_ENV=staging
PHONE_OTP_ENABLED=true
PHONE_OTP_BACKEND=staging_fixed
EMAIL_BACKEND=ses
EMAIL_SEND_ENABLED=true
EMAIL_FROM=verify@kairoid.com
SES_FROM_EMAIL=verify@kairoid.com
EMAIL_REPLY_TO=support@kairoid.com
AWS_REGION=us-east-1
```

Inject these values as ECS secrets from AWS Secrets Manager:

- `STAGING_PHONE_OTP_CODE`: exactly six digits
- `STAGING_PHONE_OTP_ALLOWED_NUMBERS`: comma-separated normalized E.164 numbers
- `DATABASE_URL`: staging database only
- `JWT_SECRET_KEY`: staging-specific signing secret

Never place real values in Git, Docker build arguments, frontend environment files, APKs,
task-definition plain-text environment entries, logs, or API responses.

## Security behavior

- Non-allowlisted numbers receive the same generic send response but are assigned an undisclosed
  random challenge, so the staging fixed code cannot verify them and allowlist membership is hidden.
- Only the hash is stored in Redis, scoped to the signup session and phone channel.
- Existing expiry, resend throttling, attempt limits, and atomic consume behavior apply.
- The provider logs its activation and masked delivery metadata, never the code or full allowlist.
- Production continues to require a real SMS provider.
