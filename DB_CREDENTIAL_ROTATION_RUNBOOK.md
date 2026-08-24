# DB Credential Rotation Runbook

This runbook defines the target Kairo database credential architecture and the safe rotation workflow for production-like environments.

No secret values belong in this document.

## Target Architecture

### Runtime identity

- Principal: dedicated least-privileged runtime database role such as `kairo_app`
- Used by:
  - API service
  - async worker service
- Required privileges:
  - connect to the application database
  - schema usage
  - table `SELECT`, `INSERT`, `UPDATE`, `DELETE`
  - sequence usage / nextval where required by SQLAlchemy models
- Must not own schema migrations or broad administrative privileges

### Migration identity

- Principal: separate privileged migration role such as `kairo_migrator`
- Used by:
  - deployment migration task only
- Required privileges:
  - Alembic `upgrade` / `downgrade` operations
  - DDL required by the current schema lifecycle
- Must not be injected into the steady-state API or worker service

### Secret ownership

- Runtime application secret:
  - canonical source for runtime DB credentials
  - preferred format: structured fields
    - `DATABASE_HOST`
    - `DATABASE_PORT`
    - `DATABASE_NAME`
    - `DATABASE_USER`
    - `DATABASE_PASSWORD`
    - `DATABASE_SSLMODE`
- Migration secret:
  - separate canonical source for migration credentials when runtime and migration identities are split
- RDS-managed master secret:
  - retained for administration, recovery, and emergency use
  - not duplicated into the runtime application secret

### IAM readers

- API runtime task role / execution role:
  - read runtime application secret only
- Worker runtime task role / execution role:
  - read runtime application secret only
- Migration task role / execution role:
  - read migration secret only
- Rotation automation component, if introduced:
  - read/write only the specific runtime secret it rotates
  - no wildcard Secrets Manager write access

## Configuration Contract

The backend supports two mutually exclusive DB configuration styles:

1. URL form
   - `DATABASE_URL`
   - optional `MIGRATION_DATABASE_URL`
2. Structured form
   - `DATABASE_*`
   - optional `MIGRATION_DATABASE_*`

Rules:

- Runtime must use exactly one style.
- Migration must use exactly one style when explicitly configured.
- Mixed URL + structured fields fail closed at startup.
- Incomplete structured fields fail closed at startup.
- If migration settings are omitted, Alembic falls back to the resolved runtime configuration.

## Rotation Workflow

Rotation is complete only after the new credential is in service behind readiness checks.

### Normal sequence

1. Confirm current service health.
   - `/api/v1/health/live = 200`
   - `/api/v1/health/ready = 200`
   - ECS desired/running counts stable
2. Generate or rotate the target DB credential.
   - If runtime and migration identities are separate, rotate only the intended identity.
3. Update the canonical secret atomically.
   - runtime secret for API/worker
   - migration secret for migration task, if applicable
4. Validate the new credential with a fresh connection.
   - do not rely on pooled existing sessions
   - validate from the same network environment as the ECS task
5. Register or update the ECS task definition only if required by the deployment mechanism.
   - if the task definition already references the same secret ARN/key, force a new deployment so fresh tasks re-read the secret
6. Start new ECS tasks.
7. Wait for readiness.
   - DB connection must succeed on `/api/v1/health/ready`
   - load balancer must mark the new task healthy
8. Drain old tasks only after new tasks are healthy.
9. Confirm steady state.
   - desired = running
   - pending = 0
   - rollout completed
10. Mark the rotation complete only after post-deploy validation passes.

### Required post-rotation validation

- fresh DB connectivity passes
- `/api/v1/health/live = 200`
- `/api/v1/health/ready = 200`
- no unexpected 5xx
- no DB-auth failures in recent logs
- no credential leakage in logs

## ECS Refresh Rules

- Updating a Secrets Manager value alone does not refresh running ECS task environments.
- A fresh deployment is required so new tasks consume the new secret.
- Readiness must prove DB connectivity before a task can enter service.
- ECS deployment circuit breaker should remain enabled so DB-broken tasks fail closed.

## Failure Modes

### A. DB password changes but secret update fails

- Expected behavior:
  - existing tasks may continue on already-open connections
  - new fresh connections fail
- Safe stop point:
  - before old tasks are drained
- Recovery:
  - restore the known-good password in DB or complete the secret update before any rollout

### B. Secret changes but DB password does not

- Expected behavior:
  - new tasks fail readiness with DB auth errors
- Safe stop point:
  - ECS rollout should halt before replacing healthy old tasks if the circuit breaker is active
- Recovery:
  - restore the old secret value or apply the matching DB password intentionally

### C. Fresh validation fails

- Expected behavior:
  - do not continue to ECS rollout
- Recovery:
  - fix credential, privilege, host, TLS, or network issue first

### D. ECS replacement fails readiness

- Expected behavior:
  - new task never reaches target health
  - old task should remain serving if circuit breaker rollback is enabled
- Recovery:
  - inspect DB auth and secret-injection logs
  - restore prior task definition / secret if required

### E. ECS rolls back

- Expected behavior:
  - healthy old task stays live
- Recovery:
  - treat rollout as failed
  - do not retry until fresh validation succeeds

### F. Old DB sessions continue after rotation

- Expected behavior:
  - old tasks may keep serving until drained
- Recovery:
  - this is acceptable during transition as long as new tasks validate successfully before drain

### G. Migration runs during credential transition

- Expected behavior:
  - risk of migration using stale or mismatched credentials
- Recovery:
  - freeze migrations during runtime credential rotation unless the migration identity is independent and validated

## Logging and Redaction Rules

- Never log:
  - full DSNs
  - database passwords
  - raw Secrets Manager payloads
- Database and unhandled exceptions must redact:
  - URL passwords
  - password-like key/value pairs
- Preserve enough sanitized context to identify:
  - driver
  - host
  - port
  - auth vs TLS vs routing failure category

## Re-enabling Automatic Rotation

Automatic rotation may be re-enabled only after all of the following are proven in staging:

1. one canonical runtime secret exists
2. fresh validation uses the new credential successfully
3. ECS deployment refresh is deterministic
4. readiness blocks DB-broken tasks
5. rollback leaves healthy old tasks in service
6. logs remain credential-safe

If rotation is orchestrated by automation, that component must:

- rotate the intended secret only
- validate the fresh credential
- trigger ECS rollout
- wait for readiness success
- stop automatically on validation or deployment failure

## Emergency Manual Procedure

Use only when automated rotation is unavailable or fails:

1. confirm current health and snapshot/backups
2. update the intended DB credential
3. update the canonical runtime or migration secret
4. run fresh connection validation from inside the application network
5. force ECS deployment
6. wait for readiness and load balancer health
7. confirm no unexpected 5xx or DB auth failures
8. retain rollback path until post-deploy validation is complete

## Production Transition Preconditions

Before moving this architecture into production:

- production service is healthy
- current task definition and image SHA are recorded
- current Alembic revision is recorded
- recovery snapshot exists and is recent
- RDS deletion protection remains enabled
- rotation remains suspended until the new workflow is proven
- staging rehearsal has passed end to end
