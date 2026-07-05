# Logging system

Production logging uses the standard library **`logging`** package with:

- **Structured JSON** to stdout (`LOG_JSON=true`) for ingestion by Datadog, ELK, CloudWatch Logs Insights, Loki, etc.
- **Plain text** when `LOG_JSON=false` (local debugging).

## Components

| Module | Role |
|--------|------|
| `app/logging/setup.py` | `configure_logging()` — root handler, filters, library logger levels |
| `app/logging/context.py` | `contextvars` for `request_id`, `correlation_id`, `user_id` |
| `app/logging/filters.py` | Injects service metadata + request context into every log record |
| `app/middleware/request_context.py` | Sets context from headers; emits **`http.access`** structured access logs |

## Correlation headers

| Header | Meaning |
|--------|---------|
| `X-Request-ID` | Generated if absent; echoed on the response |
| `X-Correlation-ID` | Optional upstream trace id; defaults to request id |

Downstream services should propagate these headers on outgoing calls.

## Fields on every JSON log line

Typical keys (subset):

- `timestamp`, `level`, `name`, `message`
- `service`, `environment` (from settings)
- `request_id`, `correlation_id`, `user_id` (when in request scope / authenticated)
- `source_path`, `source_line` (caller location)

Authenticated routes call `bind_user_context(user_id)` so application logs during the request include **`user_id`**.

## HTTP access logs

Logger: **`http.access`**, message: **`request_completed`**, with extras:

- `event=http_access`
- `http_method`, `http_path`, `http_route`, `status_code`, `duration_ms`, `client_host`

Enable/disable with **`LOG_ACCESS_ENABLED`**. When enabled, **`uvicorn.access`** is raised to **WARNING** to avoid duplicate access lines.

## Application logging pattern

```python
from app.logging import get_logger

logger = get_logger(__name__)

logger.info("user_created", extra={"user_id": str(user.id)})
```

Never log secrets, passwords, OTPs, or raw `Authorization` headers.

## API

Import from **`app.logging`** (preferred) or legacy **`app.core.logging`** (`setup_logging`, `get_logger`, `log_extra`).

- `configure_logging()` / `setup_logging()` — call once from FastAPI lifespan (already wired in `app/main.py`).
- `bind_user_context(user_id)` — optional; used in auth dependency after resolving the user.
- `reset_request_context()` — called by middleware after each request; do not call from handlers.

## Environment variables

See **`.env.example`** — `LOG_LEVEL`, `LOG_JSON`, `LOG_ACCESS_ENABLED`.
