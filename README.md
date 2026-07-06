# kairo-backend

Enterprise-style FastAPI service with **clean architecture** (API → services → repositories), **async SQLAlchemy 2 + PostgreSQL**, **JWT access tokens**, **opaque refresh tokens with rotation**, **Redis**, **Alembic migrations**, **structured logging**, and **Docker Compose** (Postgres + Redis + API).

See **`docs/ARCHITECTURE.md`** for design decisions, tradeoffs, scaling notes, and security rationale.

See **`docs/CONFIG.md`** for environment variables, configuration loading, and production hardening flags.

See **`docs/LOGGING.md`** for structured logs, correlation IDs, and access logging.

See **`docs/DATABASE.md`** for SQLAlchemy sessions, pooling, migrations, and transactions.

See **`docs/production-env.md`** for production-safe environment guidance.

See **`docs/production-secrets.md`** for required production secrets and secret-handling expectations.

## Stack

| Layer | Choice |
|-------|--------|
| Runtime | Python 3.12, FastAPI, Pydantic v2 |
| Persistence | PostgreSQL, SQLAlchemy 2 async (`asyncpg`), Alembic |
| Cache / coordination | Redis (`redis.asyncio`) |
| Async workloads | Amazon SQS (`app/infrastructure/sqs/`, `python -m app/workers.sqs_worker`), see **`docs/SQS.md`** |
| Delivery | Docker / Gunicorn + Uvicorn workers, optional NGINX |

## Production hardening requirements

Before exposing this service to real users:

- Use **HTTPS** for all public API traffic.
- Do **not** expose the production API through a raw public IP.
- Set **`DOCS_ENABLED=false`** in production.
- Provide all required production secrets documented in **`docs/production-secrets.md`**.
- Run **database migrations before serving traffic**.
- Run the **worker** in production if async jobs are enabled.

This repository currently supports production hardening on the existing FastAPI stack. It should not be treated as production-safe if those requirements are skipped.

## Local development

1. Copy env template and set **`DATABASE_URL`**, **`JWT_SECRET_KEY`** (≥32 chars), **`REDIS_URL`**:

   ```bash
   cp .env.example .env
   ```

2. Install dependencies (Python **3.12**):

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-dev.txt
   ```

3. Apply migrations (requires Postgres):

   ```bash
   alembic upgrade head
   ```

4. Run the API:

   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

5. Tests (unit smoke — excludes `@pytest.mark.integration`):

   ```bash
   pytest -m "not integration"
   ```

   Docker Compose local development images install `requirements-dev.txt`, so the same test command also works inside the API container:

   ```bash
   docker compose exec -T api pytest -m "not integration"
   ```

6. Full stack with Compose (runs migrations then Gunicorn):

   ```bash
   cp .env.example .env   # if you have not already
   docker compose up --build
   ```

   `docker-compose.yml` sets **`DATABASE_URL`** / **`REDIS_URL`** to the **`postgres`** and **`redis`** service hostnames inside containers. Keep **`localhost`** in `.env` when running **uvicorn on your machine** against Compose-published ports.

## API surface (`/api/v1`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/v1/health/live` | No |
| GET | `/api/v1/health/ready` | No |
| POST | `/api/v1/auth/register` | No — sends email OTP (`SignupStartResponse`) |
| POST | `/api/v1/auth/signup/verify` | No — completes signup, returns tokens |
| POST | `/api/v1/auth/signup/resend` | No — resend OTP |
| POST | `/api/v1/auth/login` | No — requires verified email |
| POST | `/api/v1/auth/refresh` | Refresh body |
| POST | `/api/v1/auth/logout` | Refresh body |
| GET | `/api/v1/users/me` | Bearer JWT |

OpenAPI: **`/docs`**, **`/redoc`**.

In production, set **`DOCS_ENABLED=false`** so the interactive API docs are not exposed publicly.

## GitHub / AWS deployment

Repository variables / secrets and EC2/ECR flow are unchanged from earlier bootstrap — update CD health curls to **`/api/v1/health/live`** and **`/api/v1/health/ready`** (already aligned in `.github/workflows/cd.yml`).

Runtime env on EC2 / RDS example:

```env
DATABASE_URL=postgresql+asyncpg://user:pass@your-rds-endpoint:5432/kairo
JWT_SECRET_KEY=your-long-random-secret-at-least-32-chars
REDIS_URL=redis://your-elasticache:6379/0
```

Production deployments should also define:

- SMTP credentials for OTP / verification email
- S3 bucket configuration for documents
- SQS queue URLs for async jobs
- OAuth client secrets for any enabled providers
- HTTPS-safe values for `APP_PUBLIC_BASE_URL`, `CORS_ORIGINS`, and `TRUSTED_HOSTS`

Do not use raw IPs for `APP_PUBLIC_BASE_URL` or frontend/API integration in production.

## Infrastructure files

- `Dockerfile` — non-root, health check against **`/api/v1/health/live`**
- `docker-compose.yml` — Postgres (healthy gate), Redis, API with `alembic upgrade head` before Gunicorn
- `alembic/` — migrations (`001_initial_schema`)
- `nginx/default.conf` — reverse proxy template
- `scripts/bootstrap_ec2.sh`, `scripts/deploy_ec2.sh`
- `.github/workflows/ci.yml`, `.github/workflows/cd.yml`

## Production startup rule

The production release process must apply **`alembic upgrade head`** successfully before the API starts serving traffic. If the schema is not up to date, do not continue the rollout.

If asynchronous jobs are configured, the worker process (`python -m app.workers.sqs_worker`) must also be deployed so queue-backed work does not stall.
