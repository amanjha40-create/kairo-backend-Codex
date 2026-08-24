# Configuration management

Runtime configuration follows **twelve-factor**: one canonical `Settings` object loaded from **environment variables** (and optionally `.env` in development only).

## Entry points

| Import | Purpose |
|--------|---------|
| `from app.config import get_settings, Settings, reload_settings` | Preferred |
| `from app.core.config import ...` | Backward-compatible shim |

`get_settings()` is cached (`functools.lru_cache`). After changing environment variables in tests, call **`reload_settings()`** before the next `get_settings()` call.

## Resolution order

`pydantic-settings` loads:

1. Environment variables (highest precedence for conflicts)
2. `.env` file (when present and `env_file` enabled in `SettingsConfigDict`)

Variable names are **case-insensitive** and map to fields via **`validation_alias`** (e.g. `DATABASE_URL` → `database_url`).

## Database credential resolution

Runtime and migration DB settings now support two mutually exclusive styles:

1. A single DSN:
   - `DATABASE_URL`
   - optional `MIGRATION_DATABASE_URL`
2. Structured secret fields:
   - `DATABASE_HOST`
   - `DATABASE_PORT`
   - `DATABASE_NAME`
   - `DATABASE_USER`
   - `DATABASE_PASSWORD`
   - optional `DATABASE_SSLMODE`
   - optional migration equivalents prefixed with `MIGRATION_`

Rules:

- Runtime must use exactly one style.
- Migration must use exactly one style when explicitly configured.
- Mixed URL + structured fields fail closed at startup.
- Incomplete structured DB fields fail closed at startup.
- When migration settings are omitted, Alembic falls back to the resolved runtime DB settings.

Preferred production direction:

- runtime uses a dedicated least-privileged application identity from one canonical structured secret
- migration tooling uses a separate privileged migration identity
- URL-based credentials remain supported for local development and controlled transition periods

## Environment (`APP_ENV`)

| Value | Behaviour |
|-------|-----------|
| `development` | Default; relaxed JWT length beyond global minimum |
| `staging` | Same validation as development unless you extend `Settings` |
| `production` | Fails closed unless DB/Redis TLS, HTTPS origins, explicit CORS/trusted hosts, immutable provenance, SQS jobs, production OTP, and disabled development surfaces are configured |
| `test` | Used by pytest (`tests/conftest.py`) |

## Observability

- **`LOG_LEVEL`** — Root logger level (e.g. `INFO`, `DEBUG`).
- **`LOG_JSON`** — Emit JSON lines to stdout vs plain text.
- **`LOG_ACCESS_ENABLED`** — Structured `http.access` logs per request; suppresses duplicate **uvicorn.access** lines.

Details: **`docs/LOGGING.md`**.

## Redis

`REDIS_URL` and related pool/timeout options are defined on **`Settings`**. Full reference: **`docs/REDIS.md`**.

## Security-related flags

- **`DOCS_ENABLED`** — When `false`, `/docs`, `/redoc`, and `/openapi.json` are disabled (recommended when the API is exposed publicly without an API gateway).
- **`TRUSTED_HOSTS`** — Non-empty list enables `TrustedHostMiddleware` (set to your public hostname(s) behind NGINX/ALB).
- **`CORS_ORIGINS`** — Comma-separated or JSON array. **`CORS_ALLOW_CREDENTIALS`** is forced **off** when origins are empty or wildcard-like, because browsers disallow cookies with `*` origins.

## AWS / workers

Optional URLs and credentials for async processing:

- **`AWS_REGION`**, **`AWS_ENDPOINT_URL`** (LocalStack / custom endpoint)
- **`SQS_MAIN_QUEUE_URL`**, **`SQS_DLQ_URL`**
- **`SQS_RECEIVE_WAIT_SECONDS`** (0–20), **`SQS_MAX_MESSAGES_PER_POLL`** (1–10)

See **`docs/SQS.md`** for the worker process, envelope schema, and publishing from the API.

Wire **`send_json_message`** / **`python -m app.workers.sqs_worker`** in your deployment; settings load even when queues are unset.

## Adding a new setting

1. Add a typed field to **`app/config/settings.py`** with `Field(..., validation_alias=AliasChoices("MY_NEW_VAR"))`.
2. Document it in **`.env.example`** and this file.
3. If tests patch env vars, call **`reload_settings()`** in the fixture after updating `os.environ`.

## Secret-safe error handling

Database and unhandled exception logging must preserve enough context to debug startup and readiness failures without emitting credential-bearing values.

Current guarantees:

- DSNs in tracebacks are redacted before logging.
- password-like key/value pairs are redacted before logging.
- production validation still reports actionable categories such as missing TLS, loopback hosts, or mixed DB config styles.

See **`docs/LOGGING.md`** and **`DB_CREDENTIAL_ROTATION_RUNBOOK.md`** for operational guidance.
