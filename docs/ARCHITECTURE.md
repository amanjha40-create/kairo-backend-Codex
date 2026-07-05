# Architecture — Kairo Backend

This document explains **why** the codebase is structured the way it is: layers, async boundaries, auth, data, messaging, and operational posture.

---

## 1. Layered (“clean”) architecture

### Layers

| Layer | Responsibility |
|-------|------------------|
| **`app/api`** | HTTP concerns only: routing, status codes, dependency injection, request/response schemas. No SQL. |
| **`app/services`** | Use cases: orchestration, **transaction intent**, authorization checks that need domain context. |
| **`app/repositories`** | Persistence: queries, filters, pagination primitives. No HTTP concepts. |
| **`app/infrastructure`** | External systems: Redis, SQS publishers, third-party HTTP clients. |
| **`app/models`** | SQLAlchemy ORM — persistence shape; not the public API contract. |
| **`app/schemas`** | Pydantic DTOs — API contracts (`Create`, `Public`, etc.). |

### Tradeoffs

- **Pros:** Testability (mock repositories), clear boundaries, fewer regressions when swapping infra (e.g. Redis vendor).
- **Cons:** More files than a tutorial app; small features touch multiple folders — acceptable at scale.

---

## 2. Async-first I/O

### Decision

All FastAPI handlers and DB/Redis access paths use **`async`/`await`**.

### Tradeoffs

- **Pros:** Efficient concurrency under load for I/O-bound APIs.
- **Cons:** Blocking calls (sync boto3, CPU-heavy parsing on event loop) stall all requests — mitigate with thread pools or dedicated workers (SQS).

---

## 3. Database & migrations

### Decision

- **Runtime:** `postgresql+asyncpg://` with SQLAlchemy **`AsyncSession`**.
- **Migrations:** Alembic uses synchronous **`postgresql+psycopg://`** — DDL drivers differ from async runtime drivers.

### Tradeoffs

- **Pros:** Industry-standard migrations; async runtime stays optimal for OLTP.
- **Cons:** Two drivers in dependencies — justified.

### Pooling

`pool_pre_ping`, bounded pool size — recycle dead connections and avoid fork bombs.

---

## 4. Authentication & authorization

Code lives in **`app/auth/`** (passwords, JWT helpers, **`AuthService`**, FastAPI **`deps`**: **`get_current_user`**, **`require_roles`**). Legacy imports **`app.core.security`** and **`app.api.dependencies.auth`** re-export the same API.

### Access tokens (JWT)

- Short-lived **JWT** with `sub`, `role`, `type=access`.
- **HS256** symmetric signing — simple for a single API service.

**Tradeoff:** Shared secret rotation requires coordinated deploys; multi-service meshes often move to **RS256 + JWKS**.

### Refresh tokens (opaque + DB)

- **Opaque** random tokens; only **SHA-256 hash** stored.
- **Rotation:** each refresh revokes the previous row and mints a new hash-bound row within the same **`family_id`**.
- **Reuse detection:** presenting a **revoked** refresh token revokes the entire family — mitigates token theft replay.

**Tradeoff:** DB round-trip on refresh vs pure stateless JWT refresh — we chose **revocable** sessions over marginal latency.

### RBAC

- Roles stored on `users.role`; **`require_roles(...)`** dependency for route guards.
- Critical mutations should still re-check resource ownership / tenant scope (future).

---

## 5. Centralized errors & logging

### Errors

- Domain exceptions subclass **`AppException`** with stable **`code`** fields.
- Handlers map to HTTP status without leaking stack traces or SQL details.

### Logging

- JSON-capable structured logs (`python-json-logger`) — ingest-ready for Datadog/ELK/CloudWatch.
- Request correlation via **`X-Request-ID`** middleware.

---

## 6. Redis

Implementation lives under **`app/infrastructure/redis/`** (async pool, `Depends(get_redis)`, namespaced keys, JSON cache helpers). See **`docs/REDIS.md`**.

Used for:

- Rate limiting keys (future middleware),
- ephemeral coordination,
- optional refresh-token hot revocation lists.

**Tradeoff:** Adds infra dependency — disable or stub in minimal dev by pointing `REDIS_URL` at local Compose Redis. Set **`REDIS_REQUIRED_FOR_READY=true`** when Redis must gate readiness checks.

---

## 7. SQS workers

- **`app/infrastructure/sqs/`** — boto3 client factory, **`SqsJobEnvelope`**, async-safe **`send_json_message`** for the API.
- **`app/workers/consumer.py`** — long-polling **`ReceiveMessage`** loop, handler dispatch, **`DeleteMessage`** after successful commit.
- **`app/workers/registry.py`** — **`@register_handler("type")`**; implement jobs under **`app/workers/handlers/`**.
- **CLI:** `python -m app.workers.sqs_worker` — same image as the API, different command.

See **`docs/SQS.md`**. Production expectations: idempotent handlers, DLQ + visibility timeouts on the queue, scale workers independently from the web tier.

API processes **enqueue** via **`send_json_message`**; heavy work never blocks request latency.

---

## 8. Security posture (summary)

| Risk | Mitigation |
|------|------------|
| SQL injection | SQLAlchemy bound parameters only |
| Weak passwords | Argon2id via argon2-cffi; legacy bcrypt verified on login and rehashed; minimum length in schema |
| Token leakage | Short access TTL; refresh rotation + reuse detection |
| IDOR | Always scope queries by authenticated principal (expand per endpoint) |
| Enumeration | Generic auth error messages |

---

## 9. Scaling playbook

1. **Horizontal:** Stateless API containers behind a load balancer.
2. **DB:** Read replicas + tune pools; avoid N+1 via eager loading where measured.
3. **Writes:** Push to SQS for heavy processing.
4. **Hot reads:** Redis caching with TTL + explicit invalidation.

---

## 10. Observability hooks

- Structured logs,
- Request IDs,
- Health **live** vs **ready** split (DB probe),
- Metrics: expose Prometheus-compatible `/metrics` later behind auth/network policy.

---

*Maintainers: keep this document updated when changing auth, tenancy model, or messaging topology.*
