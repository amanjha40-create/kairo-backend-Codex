# Database layer

Async **SQLAlchemy 2** with **PostgreSQL** (`asyncpg`). Schema changes go through **Alembic** only in deployed environments.

## Layout

| Module | Role |
|--------|------|
| `app/db/base.py` | `DeclarativeBase` + **`NAMING_CONVENTION`** for indexes/constraints |
| `app/db/session.py` | **`AsyncEngine`**, **`async_sessionmaker`**, **`get_session`** dependency |
| `app/db/deps.py` | **`get_db`** alias (same as **`get_session`**) |
| `app/db/transactions.py` | Optional **`transaction(session)`** context manager |
| `app/db/health.py` | **`ping_database(session)`** for readiness |

ORM models live under **`app/models/`**; repositories under **`app/repositories/`**.

## Session lifecycle

- **`get_session`** / **`get_db`**: one **`AsyncSession`** per HTTP request (FastAPI `Depends`).
- On uncaught exceptions, the dependency **rolls back** the session.
- **Commits** are owned by **services** after successful writes (`await session.commit()`).

Alternative: wrap a unit of work in **`async with transaction(session):`** — commits on success, rolls back on error. Do **not** mix blind **`commit()`** inside that block without understanding nesting.

## Connection pool

Tuned via settings (see **`.env.example`**):

| Variable | Purpose |
|----------|---------|
| `DATABASE_POOL_SIZE` | Pool size (default `10`) |
| `DATABASE_MAX_OVERFLOW` | Burst connections beyond pool size |
| `DATABASE_POOL_TIMEOUT` | Seconds to wait for a connection |
| `DATABASE_ECHO_SQL` | Log SQL; unset → **on** only when `APP_ENV=development` |

## Shutdown

`app/main.py` lifespan calls **`dispose_engine()`** so pools close cleanly under SIGTERM / container stop.

## Migrations

- Runtime URL: **`postgresql+asyncpg://...`**
- Alembic uses sync **`postgresql+psycopg://...`** (see `alembic/env.py`).

## Development shortcut

**`init_db_schema()`** creates tables from metadata without migrations — **not** for production.

## Imports

```python
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session, ping_database, transaction
from app.db.base import Base
```
