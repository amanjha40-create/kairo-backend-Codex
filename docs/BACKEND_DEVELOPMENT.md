# Backend Development Guide

This guide is the working reference for developing and verifying the Kairo backend safely.

Principles:

- do not change product behavior casually
- prefer additive, reviewable commits
- verify changes locally before asking for merge review
- keep backend contracts stable for frontend integration

## Local Docker Setup

The repository includes Docker Compose for local API, PostgreSQL, and Redis development.

Start the backend stack:

```bash
docker compose up -d --build api
```

Start the full stack:

```bash
docker compose up -d --build
```

Inspect service status:

```bash
docker compose ps
```

Useful local URLs:

- API base: `http://localhost:8000/api/v1`
- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

## Running Migrations

Apply all migrations inside Docker:

```bash
docker compose exec -T api alembic upgrade head
```

Check current revision:

```bash
docker compose exec -T api alembic current
```

Check latest head:

```bash
docker compose exec -T api alembic heads
```

Rules:

- always run migrations before validating schema-dependent changes
- never ship backend changes if `alembic current` is behind `alembic heads`
- do not modify old migrations after they are part of shared branch history

## Running Tests

Run the full backend regression suite inside Docker:

```bash
docker compose exec -T api pytest -q
```

Run a focused test file:

```bash
docker compose exec -T api pytest tests/test_public_passport.py -q
```

Run multiple focused files:

```bash
docker compose exec -T api pytest tests/test_public_passport.py tests/test_reset_password_routes.py -q
```

Compile Python sources:

```bash
env PYTHONPYCACHEPREFIX=/tmp/kairo-pycache python3 -m compileall app tests
```

Rules:

- run focused tests while iterating
- run the full suite before merge review
- if Docker was rebuilt or dependencies changed, rerun the suite from the container you expect to deploy

## Adding a New Endpoint

Recommended flow:

1. Add or extend request/response schemas in `app/schemas/`
2. Add the use-case behavior in the relevant service under `app/services/`
3. Add repository access in `app/repositories/` only if new persistence reads/writes are needed
4. Add the route in `app/api/v1/routes/`
5. Register the route through `app/api/v1/router.py` if it is a new route module
6. Add route-contract tests in `tests/`
7. Verify Swagger/OpenAPI output

Design rules:

- keep routes thin
- keep business logic in services
- keep authorization enforced server-side
- prefer stable `public_id` values externally where the platform engine supports them
- return shared error envelopes and shared page envelopes where applicable

## Adding a Migration

Recommended flow:

1. Update models and any related enums or schema-layer assumptions
2. Generate or author a new Alembic migration
3. Review the migration carefully for indexes, constraints, and naming
4. Apply the migration locally
5. Run the regression suite

Typical commands:

```bash
docker compose exec -T api alembic revision -m "describe change"
docker compose exec -T api alembic upgrade head
```

Migration rules:

- one logical schema change per migration where practical
- avoid mixing unrelated schema changes into a single revision
- do not add placeholder migrations
- verify downgrade intent if the migration is risky or operationally sensitive

## Branch and Commit Rules

Expected working style:

- develop on feature or hotfix branches, not directly on `main`
- use small, clean commits with one clear purpose each
- keep product changes separate from docs, CI, or test-only changes
- do not rebase or force-push shared branches without explicit approval

Suggested branch naming:

- `feature/<topic>`
- `hotfix/<topic>`
- `chore/<topic>`

Suggested commit characteristics:

- one behavior change per commit
- one documentation concern per docs commit
- one infrastructure or CI concern per chore/CI commit

## Verification Checklist

Before review:

1. Confirm you are on the intended branch.
2. Confirm `git status` is understood.
3. Rebuild Docker when runtime behavior or tests depend on updated files:

   ```bash
   docker compose up -d --build api
   ```

4. Run compile checks:

   ```bash
   env PYTHONPYCACHEPREFIX=/tmp/kairo-pycache python3 -m compileall app tests
   ```

5. Run focused tests for the change.
6. Run the full regression suite:

   ```bash
   docker compose exec -T api pytest -q
   ```

7. Confirm API docs still load:

   ```bash
   docker compose exec -T api sh -lc "curl -fsS http://127.0.0.1:8000/openapi.json >/tmp/openapi.json"
   docker compose exec -T api sh -lc "curl -I -s http://127.0.0.1:8000/docs | head -n 1"
   ```

8. If schema changed, confirm:

   ```bash
   docker compose exec -T api alembic current
   docker compose exec -T api alembic heads
   ```

9. Confirm the working tree is clean or intentionally staged before handoff.

## Quality Gate Summary

Every backend PR should be able to answer yes to these questions:

- Does CI install dependencies successfully?
- Does `compileall` pass?
- Does `pytest -q` pass?
- Are docs or contracts updated if the API shape changed?
- Is the branch history clean and reviewable?
- Is the backend still safe for frontend integration?
