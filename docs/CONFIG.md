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

## Environment (`APP_ENV`)

| Value | Behaviour |
|-------|-----------|
| `development` | Default; relaxed JWT length beyond global minimum |
| `staging` | Same validation as development unless you extend `Settings` |
| `production` | **JWT_SECRET_KEY** must be **≥ 48 characters** |
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
