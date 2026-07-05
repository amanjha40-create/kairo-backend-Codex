# Amazon SQS integration

## Overview

| Layer | Role |
|-------|------|
| **`app/infrastructure/sqs/`** | Boto3 client, **`SqsJobEnvelope`**, **`send_json_message`** (async wrapper around sync boto3). |
| **`app/workers/`** | Long-poll consumer (`consumer.py`), **`register_handler`** registry, optional **`handlers/`** modules. |

Run the worker as a **separate process** from the API:

```bash
python -m app.workers.sqs_worker
```

Docker Compose includes an optional **`worker`** service (`--profile worker`). Set **`SQS_MAIN_QUEUE_URL`** (and credentials / **`AWS_ENDPOINT_URL`** for LocalStack) before enabling it.

## Configuration

| Variable | Purpose |
|----------|---------|
| **`AWS_REGION`** | Region for boto3 (also respects instance/task role env). |
| **`AWS_ENDPOINT_URL`** | LocalStack or custom endpoint (omit in real AWS). |
| **`SQS_MAIN_QUEUE_URL`** | Queue consumed by the worker; required for **`send_json_message`** when publishing from the API. |
| **`SQS_DLQ_URL`** | Document/monitor only — redrive policy is configured on the queue in AWS. |
| **`SQS_RECEIVE_WAIT_SECONDS`** | Long-poll wait (0–20, default **20**). |
| **`SQS_MAX_MESSAGES_PER_POLL`** | Batch size per **`ReceiveMessage`** (1–10, default **10**). |

Credentials use the **standard AWS chain** (env keys, `~/.aws/credentials`, IAM role).

## Message shape

Producers send JSON matching **`SqsJobEnvelope`**:

```json
{ "type": "noop", "data": { "example": true } }
```

- **`type`** must match a **`@register_handler("type")`** function.
- **`data`** is passed to the handler with a dedicated **`AsyncSession`** (one transaction per message; commit on success).

Unknown **`type`** or invalid JSON shape: the message is **not** deleted and will retry until your queue’s **maxReceiveCount** sends it to a configured DLQ.

## Handlers

Add a module under **`app/workers/handlers/`** and import it from **`app/workers/handlers/__init__.py`** so registration runs at worker startup:

```python
from sqlalchemy.ext.asyncio import AsyncSession
from app.workers.registry import register_handler

@register_handler("email.send")
async def send_email(data: dict, session: AsyncSession) -> None:
    ...
```

Keep handlers **idempotent** (natural keys, `UNIQUE` constraints, or explicit idempotency rows).

## API publishing

From an async route or service:

```python
from app.infrastructure.sqs import SqsJobEnvelope, send_json_message

await send_json_message(SqsJobEnvelope(type="email.send", data={"to": "a@b.com"}))
```

This uses **`asyncio.to_thread`** so boto3 does not block the event loop.

## Shutdown

The worker handles **SIGINT** / **SIGTERM** (Unix), finishes the current poll batch, then disposes the DB engine and closes the Redis pool.
