# AI Project Guidelines — Production FastAPI Backend

This document defines **mandatory conventions** for AI-assisted and human-authored code in our FastAPI services. Following it keeps architecture consistent, security strong, and operations predictable.

**Target stack:** Python 3.12 · FastAPI · PostgreSQL · SQLAlchemy **async** · Alembic · Redis · SQS · Docker  

**Audience:** Engineers and AI tools generating application code, migrations, workers, and infrastructure glue.

---

## 1. Project overview

### Purpose

We build **API-first** backends that:

- Expose versioned HTTP APIs with predictable contracts.
- Persist durable state in **PostgreSQL** via **async** SQLAlchemy.
- Use **Redis** for ephemeral state (cache, locks, rate limits, OTP staging).
- Use **Amazon SQS** for reliable asynchronous work (notifications, parsing, webhooks).
- Run in **containers** with twelve-factor configuration.

### Non-goals

- Business logic inside route handlers beyond orchestration.
- Raw SQL string concatenation from user input.
- Shared mutable global state for request-scoped data outside FastAPI `Request` / context vars.

### Success criteria

Generated code should be **reviewable by a senior engineer** without rework: clear layering, typed interfaces, explicit transactions, structured logs, and security defaults.

---

## 2. Architecture philosophy

### Principles

| Principle | Meaning |
|-------------|---------|
| **Separation of concerns** | HTTP layer ≠ persistence ≠ domain rules ≠ integration glue. |
| **Ports and adapters** | External systems (email, S3, LLM) sit behind interfaces; swap implementations in tests. |
| **Explicit boundaries** | Each module exposes a small public surface; internals are private. |
| **Async-first I/O** | DB, Redis, HTTP clients use async APIs; avoid blocking the event loop. |
| **Fail closed** | Authorization defaults to deny; errors default to generic client messages. |

### Layered flow

```
Client → API (FastAPI routes) → Services (use cases) → Repositories (data access) → DB
                         ↘ Integrations (SQS, Redis, HTTP clients)
```

**Reasoning:** Thin routes keep HTTP concerns (status codes, headers) separate from domain logic, enabling unit tests without HTTP and integration tests without UI.

### Do / Don’t

| Do | Don’t |
|----|--------|
| Keep routes under ~30 lines; delegate to services | Put SQL or complex `if` trees in routes |
| Inject dependencies via FastAPI `Depends` | Import singleton DB sessions at module top for requests |
| Use **one `AsyncSession` per request** | Share sessions across concurrent tasks |
| Return DTOs/schemas from services where helpful | Return ORM models directly to clients |

---

## 3. Folder structure standards

Use a **feature-first** layout inside a bounded context; shared kernel stays minimal.

### Recommended layout

```
app/
  main.py                 # App factory, lifespan, middleware
  api/
    deps.py               # Shared Depends (db session, current user)
    v1/
      router.py           # Aggregates v1 routers
      users.py            # Route modules per resource
      health.py
  core/
    config.py             # Pydantic Settings
    security.py           # Password hashing, JWT helpers (thin)
  domain/                 # Optional: pure domain types / rules (no FastAPI)
  db/
    base.py               # Declarative base
    session.py            # Async engine, session factory
  models/                 # SQLAlchemy ORM models
  repositories/         # Data access (async)
  schemas/                # Pydantic request/response models
  services/               # Application / use-case layer
  integrations/         # SQS, Redis, external HTTP, email
  workers/
    sqs_consumer.py       # Long-running worker entrypoints
alembic/
tests/
  unit/
  integration/
docs/
```

### Rules

- **`api/`** — Only routing, dependency wiring, and HTTP-specific validation (e.g. pagination query params).
- **`services/`** — Orchestration, authorization checks that need domain context, transaction boundaries.
- **`repositories/`** — Queries and persistence; no business rules that belong in domain/service.
- **`integrations/`** — Third-party SDKs and message producers/consumers.

### Do / Don’t

| Do | Don’t |
|----|--------|
| Mirror domain vocabulary in folder names (`verification`, `resume`) | Dump unrelated endpoints in `routes.py` |
| Keep `main.py` small; register routers in `api/v1/router.py` | Register dozens of routers directly in `main.py` |

---

## 4. API design standards

### REST and versioning

- Prefix public APIs: **`/api/v1/...`**. Breaking changes require **`v2`** (new prefix), not silent edits.
- Use **nouns** for resources: `/users`, `/users/{user_id}`.
- Use **verbs** only for actions that don’t map cleanly: `/users/{id}/verify-email`.

### HTTP methods

| Method | Use |
|--------|-----|
| GET | Safe, idempotent reads |
| POST | Create or non-idempotent actions |
| PUT/PATCH | Full/partial replace |
| DELETE | Delete |

### Status codes

| Code | When |
|------|------|
| 200 | OK with body |
| 201 | Created; include `Location` when useful |
| 204 | Success, no body |
| 400 | Validation error (client fixable) |
| 401 | Not authenticated |
| 403 | Authenticated but not allowed |
| 404 | Resource not found (avoid leaking existence of sensitive resources — use 403 when needed) |
| 409 | Conflict (duplicate, state mismatch) |
| 422 | FastAPI validation (often acceptable for body/query errors) |
| 429 | Rate limited |
| 500 | Unexpected server error (no internals in body) |

### Example (route shape)

```python
@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    svc: UserService = Depends(get_user_service),
) -> UserPublic:
    return await svc.create_user(payload)
```

### Do / Don’t

| Do | Don’t |
|----|--------|
| Document OpenAPI via summaries and response_model | Expose internal field names that leak implementation |
| Use consistent pluralization | Mix `/user` and `/users` |

---

## 5. Repository pattern guidelines

### Responsibility

Repositories encapsulate **database access** for one aggregate or table group: CRUD, queries, joins needed for that aggregate.

### Interface

- Accept **`AsyncSession`** as first argument **or** be a class initialized with session (per-request instance via dependency).

### Example

```python
class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        stmt = select(User).where(User.id == user_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        await self._session.refresh(user)
        return user
```

### Transactions

- **Services** own transaction boundaries (`session.commit()` / `rollback()`), not repositories — unless you adopt a Unit of Work pattern explicitly.

### Do / Don’t

| Do | Don’t |
|----|--------|
| Return models or narrow DTOs from repos | Return raw SQL strings |
| Use `select()` with bound parameters | Build SQL with f-strings from user input |
| Keep queries readable; extract complex filters to private methods | Put authorization rules only in repo (belongs in service) |

---

## 6. Service layer guidelines

### Responsibility

Services implement **use cases**: validate business rules, call repositories and integrations, enforce authorization, coordinate transactions.

### Patterns

- **`async def`** methods.
- Raise **domain-specific exceptions** mapped to HTTP in exception handlers (or map to `HTTPException` in a controlled layer).
- Accept **primitive IDs or schema objects**, not ORM graphs from routes.

### Example

```python
class UserService:
    def __init__(
        self,
        session: AsyncSession,
        users: UserRepository,
        redis: RedisClient,
    ) -> None:
        self._session = session
        self._users = users
        self._redis = redis

    async def create_user(self, data: UserCreate) -> UserPublic:
        if await self._users.email_exists(data.email):
            raise ConflictError("Email already registered")
        user = User(email=data.email, ...)
        await self._users.create(user)
        await self._session.commit()
        return UserPublic.model_validate(user)
```

### Do / Don’t

| Do | Don’t |
|----|--------|
| One service per bounded context slice | One “God service” for entire app |
| Commit/rollback at service boundaries | Scatter commits across repositories randomly |
| Pass clocks/time as injectable for tests | Use `datetime.utcnow()` hidden everywhere |

---

## 7. Database design standards

### Naming

- **snake_case** tables and columns.
- **Plural** table names (`users`, `oauth_accounts`) — pick one convention and stick to it.
- Primary keys: **`uuid`** or **`bigint`** generated; prefer UUID for public-facing IDs.

### Constraints

- **`NOT NULL`** where logically required; defaults explicit.
- **Foreign keys** with `ON DELETE` behavior defined (RESTRICT/CASCADE as appropriate).
- **Unique** constraints for natural keys (`users.email`, `(provider, provider_subject)`).

### Indexing

- Index **foreign keys** used in joins and filters.
- Composite indexes match **query patterns** (filter order matters for Postgres).

### Migrations

- **Alembic** only for schema changes; never manual drift.
- Migrations are **backward-compatible** when possible (expand → migrate data → contract).

### Do / Don’t

| Do | Don’t |
|----|--------|
| Store money in minor units as **bigint** or use **decimal** with precision | Float for currency |
| Use **timestamptz** (`DateTime(timezone=True)`) | Naive datetimes for audit trails |
| Soft-delete with `deleted_at` if needed | Hard delete audit-sensitive rows without policy |

---

## 8. SQLAlchemy async standards

### Engine and session

- Use **`create_async_engine`** with PostgreSQL async driver (**asyncpg**).
- **`async_sessionmaker`** with `expire_on_commit=False` when returning ORM objects for serialization after commit (understand tradeoffs).

### Session lifecycle

- **One session per request** (dependency yield); never global session for concurrent requests.

```python
async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

Adjust commit policy if you prefer explicit commits only in services (both are valid; pick one **team-wide**).

### Queries

- Prefer **`select()`** API (2.0 style).
- Use **`await session.execute(stmt)`** then scalars.
- Avoid N+1: use **`selectinload`** / **`joinedload`** intentionally.

### Do / Don’t

| Do | Don’t |
|----|--------|
| Use bound parameters via SQLAlchemy expressions | String interpolation into SQL |
| `await` all DB IO | Call sync DB code inside async routes |
| Profile slow queries | Put logic requiring sync drivers in async path |

---

## 9. Pydantic schema standards

### Layers

- **`XCreate` / `XUpdate` / `XPublic`** naming for clarity.
- **`model_config = ConfigDict(from_attributes=True)`** for ORM-derived public models.
- **Separate** internal vs external schemas — never expose ORM internals accidentally.

### Validation

- Use **field validators** for constraints (length, regex).
- Prefer **`EmailStr`** where applicable.

### Example

```python
class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    display_name: str | None
    created_at: datetime
```

### Do / Don’t

| Do | Don’t |
|----|--------|
| Version schemas when breaking clients | Rename fields silently |
| Default to least privilege in response models | Return full ORM model with relations |

---

## 10. Error handling strategy

### Hierarchy

- **HTTP layer**: Maps known exceptions to status codes and stable error bodies.
- **Services**: Raise typed exceptions (`NotFoundError`, `ForbiddenError`, `ConflictError`).

### Example mapping

```python
@app.exception_handler(NotFoundError)
async def not_found_handler(_, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": str(exc)}})
```

### Client-facing messages

- **Generic** for 401/403/500; **specific** for validation (422) and conflict (409) when safe.

### Do / Don’t

| Do | Don’t |
|----|--------|
| Log full exception server-side | Return stack traces to clients |
| Use stable `error.code` for programmatic handling | Change error shapes per endpoint |

---

## 11. Logging standards

### Format

- **Structured JSON** in production: timestamp, level, logger name, message, `request_id`, `user_id` (if authenticated), key context.

### Levels

| Level | Use |
|-------|-----|
| DEBUG | Development only |
| INFO | Lifecycle, successful operations |
| WARNING | Recoverable anomalies |
| ERROR | Failures needing attention |

### PII and secrets

- **Never** log passwords, tokens, full OTP, raw Authorization headers, or national IDs.

### Do / Don’t

| Do | Don’t |
|----|--------|
| Correlate with **request ID middleware** | Log entire request bodies by default |

---

## 12. Security best practices

### OWASP-aligned defaults

- **Parameterized queries** only (ORM or bound SQL).
- **Input validation** on every mutating endpoint.
- **Output encoding** when rendering HTML (typically N/A for JSON APIs).
- **TLS** termination at load balancer / ingress; HTTP redirects to HTTPS.
- **Security headers** at reverse proxy (where applicable): `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Strict-Transport-Security`, `Referrer-Policy`.
- **Rate limiting** sensitive endpoints (login, OTP, password reset).

### Secrets

- Load from **environment** or secret manager; never commit secrets.

### Do / Don’t

| Do | Don’t |
|----|--------|
| Hash passwords with **Argon2** or **bcrypt** | Store plaintext passwords |
| Validate redirect URIs for OAuth | Open redirects |
| Principle of least privilege for IAM | Long-lived keys on developer laptops for prod |

---

## 13. Authentication and authorization standards

### Authentication

- **JWT access tokens** (short TTL) + **refresh** stored server-side or rotation strategy.
- Password flows: rate limit + generic errors.

### Authorization

- **RBAC** or **ABAC** expressed as dependencies:

```python
async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Forbidden")
    return user
```

- **Resource checks**: always verify **ownership or org scope** before returning/updating entities (IDOR prevention).

### Do / Don’t

| Do | Don’t |
|----|--------|
| Authorize in services for domain rules | Trust client-sent `role` |
| Check org/tenant on every relevant query | Scope only at UI |

---

## 14. Async programming standards

### Rules

- **Async def** for route handlers and async IO.
- **No blocking calls** in async context (`time.sleep`, sync boto without executor — avoid).
- Use **`asyncio.gather`** with care; sessions must not be shared across concurrent tasks unless designed for it.

### CPU-bound work

- Offload to **process pool** or dedicated worker (SQS), not the API event loop.

### Do / Don’t

| Do | Don’t |
|----|--------|
| Use async Redis clients | Sync Redis in async routes |
| Timeouts on external HTTP (`httpx.AsyncClient(timeout=...)`) | Unbounded awaits |

---

## 15. Redis usage guidelines

### Appropriate uses

- **Cache** of read-heavy, TTL-friendly data (invalidate on writes).
- **Rate limiting** counters.
- **Distributed locks** (carefully; short TTL; token validation).
- **OTP / session staging** with expiry.

### Key naming

- **`{service}:{env}:{domain}:{id}`** e.g. `kairo:prod:otp:user:{uuid}`.

### Serialization

- **JSON** for values; explicit schemas for stored blobs.

### Do / Don’t

| Do | Don’t |
|----|--------|
| Set TTL on ephemeral keys | Store sole copy of critical durable state |
| Treat cache as optional | Assume cache always warm |

---

## 16. SQS worker guidelines

### Pattern

- API **enqueues** a message (payload minimal + IDs).
- Worker **polls** SQS, processes with **idempotency** keys, **acks** on success, **visibility timeout** tuned to processing time.

### Idempotency

- Store processed **`message_id`** or business idempotency key in DB before side effects.

### Retries

- **Dead-letter queue** after N failures; alert on DLQ depth.

### Do / Don’t

| Do | Don’t |
|----|--------|
| Keep workers stateless | Assume ordering unless using FIFO with care |
| Separate queues by workload (priority, latency) | One queue for everything without tuning |

---

## 17. Docker standards

### Images

- **Multi-stage builds** when compiling extensions; for pure Python, single stage is OK if slim.
- Run as **non-root** user.
- Pin **base image digest** in production CI.

### Process

- API: **uvicorn/gunicorn + uvicorn workers** as already adopted per environment.
- Workers: separate image or same image different **CMD**.

### Do / Don’t

| Do | Don’t |
|----|--------|
| `.dockerignore` large contexts | Copy `.env` into image |
| Healthcheck hitting `/health/live` | Bake secrets at build time |

---

## 18. Environment configuration standards

### Pydantic Settings

- Single **`Settings`** class; load from env with **`model_config = SettingsConfigDict(env_file=".env", extra="ignore")`** in dev only.

### Naming

- **SCREAMING_SNAKE** for env vars: `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET_KEY`.

### Twelve-factor

- **Config in environment**; no secret files in repo.

### Do / Don’t

| Do | Don’t |
|----|--------|
| Fail fast on missing required vars | Default JWT secrets in code |
| Separate dev/staging/prod values | One mega `.env` committed |

---

## 19. Testing strategy

### Layers

| Type | Scope |
|------|--------|
| Unit | Services with mocked repos/clients |
| Integration | Repositories against real Postgres (Testcontainers or CI service) |
| API | httpx AsyncClient against TestClient / ASGITransport |

### Rules

- Tests **must not** hit production services.
- Seed **minimal fixtures**; avoid sharing mutable global DB state across parallel tests without isolation.

### Do / Don’t

| Do | Don’t |
|----|--------|
| Assert stable error codes | Sleep/wait for eventual consistency without bounds |

---

## 20. Performance optimization guidelines

- Measure before optimizing; use **APM** and Postgres **`EXPLAIN (ANALYZE)`**.
- Add **indexes** for proven slow queries.
- Use **pagination** on all list endpoints.
- Cache **hot reads** with TTL and invalidation strategy.
- Batch external calls where possible.

### Do / Don’t

| Do | Don’t |
|----|--------|
| Pool DB connections via SQLAlchemy | Open new engine per request |
| Stream large downloads | Load multi-GB files into memory |

---

## 21. Scalability guidelines

- **Stateless API** instances behind load balancer.
- **Horizontal scale** API workers; scale workers separately from web.
- **Database** first bottleneck — avoid chatty APIs and N+1.
- **Partition** high-write paths via queues (SQS) and async processing.

### Do / Don’t

| Do | Don’t |
|----|--------|
| Design idempotent consumers | Rely on sticky sessions for correctness |

---

## 22. Code review checklist

- [ ] Authorization enforced for every mutating and sensitive read path  
- [ ] No SQL/interpolation from raw user strings  
- [ ] Pydantic validates all inputs; outputs use response models  
- [ ] Async IO only; no blocking in async routes  
- [ ] Transactions explicit and bounded  
- [ ] Logs contain no secrets/PII beyond policy  
- [ ] Alembic migration for schema changes  
- [ ] Tests cover happy path + one failure mode  
- [ ] OpenAPI reflects reality  

---

## 23. Naming conventions

| Kind | Convention | Example |
|------|----------------|---------|
| Modules | `snake_case` | `user_service.py` |
| Classes | `PascalCase` | `UserService` |
| Functions | `snake_case` | `get_user_by_id` |
| Constants | `SCREAMING_SNAKE` | `DEFAULT_PAGE_SIZE` |
| DB tables | `snake_case` plural | `job_applications` |
| API paths | `kebab-case` or `snake_case` **one chosen** | `/job-applications` |

---

## 24. Dependency injection standards

- Prefer **FastAPI `Depends`** factories returning **per-request** sessions and services.

```python
def get_user_repo(session: AsyncSession = Depends(get_db)) -> UserRepository:
    return UserRepository(session)

def get_user_service(
    session: AsyncSession = Depends(get_db),
    repo: UserRepository = Depends(get_user_repo),
) -> UserService:
    return UserService(session, repo)
```

- Avoid **global** database engines beyond singleton engine factory.

### Do / Don’t

| Do | Don’t |
|----|--------|
| Construct long-lived clients once (engine, redis pool) | Create new HTTP client per request |

---

## 25. API response format standards

### Success

_wrapper optional; if used, be consistent:_

```json
{
  "data": { ... },
  "meta": { "request_id": "..." }
}
```

### Error

```json
{
  "error": {
    "code": "validation_error",
    "message": "Human-readable summary",
    "details": [ ... ]
  }
}
```

### Do / Don’t

| Do | Don’t |
|----|--------|
| Same envelope for all errors | Different shapes per endpoint |

---

## 26. Pagination / filtering standards

- **Cursor pagination** for large/unstable datasets; **offset/limit** acceptable for small admin lists.
- Query params: `limit` (max capped, e.g. 100), `cursor` opaque token.
- Document defaults in OpenAPI.

### Filter

- Allowlist filter fields; map query params to explicit repository filters.

### Do / Don’t

| Do | Don’t |
|----|--------|
| Cap `limit` | Unbounded `limit` |

---

## 27. Health check standards

- **`GET /health/live`**: process up (no DB).
- **`GET /health/ready`**: DB + critical dependencies (Redis optional toggle).

Kubernetes: **liveness** → live; **readiness** → ready.

### Do / Don’t

| Do | Don’t |
|----|--------|
| Fast fail dependency checks | Heavy work in hot path every second |

---

## 28. Observability guidelines

- **Metrics**: request count, latency histograms, error rates, queue depth, DB pool usage.
- **Tracing**: OpenTelemetry trace IDs propagated to logs.
- **Dashboards + alerts** on SLOs (p95 latency, 5xx rate, DLQ growth).

### Do / Don’t

| Do | Don’t |
|----|--------|
| Alert on symptoms + causes | Page on non-actionable noise |

---

## 29. Production readiness checklist

- [ ] Migrations automated in deploy pipeline  
- [ ] Secrets from secret manager  
- [ ] HTTPS + secure cookies if cookies used  
- [ ] Rate limits on auth endpoints  
- [ ] Backups and restore tested for Postgres  
- [ ] Redis persistence understood (if relied upon)  
- [ ] DLQ monitored  
- [ ] Runbooks for incident response  

---

## 30. Common anti-patterns to avoid

| Anti-pattern | Why it hurts | Instead |
|--------------|----------------|---------|
| Fat controllers | Untestable, duplicated logic | Services + repos |
| Sync SQL in async routes | Blocks event loop | Async session + asyncpg |
| JWT in localStorage without XSS strategy | Token theft risk | HttpOnly cookies + CSRF strategy or hardened SPA |
| Catching bare `Exception` everywhere | Hides bugs | Typed exceptions + handlers |
| Global mutable request state | Race conditions | Request-scoped DI |
| No idempotency on workers | Duplicate charges/emails | Idempotency keys |
| “Chatty” microservices day one | Ops overhead | Modular monolith until boundaries proven |

---

## Document control

- **Owner:** Platform / backend lead  
- **Review cadence:** Quarterly or when stack changes  
- **Violations:** Address in PR review; exceptions require documented ADR  

---

*End of AI Project Guidelines*
