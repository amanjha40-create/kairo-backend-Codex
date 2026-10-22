"""Migration credentials only; never initialize runtime integration settings."""

import os
from collections.abc import Mapping

from sqlalchemy.engine import make_url

from app.db.url import build_database_url, build_sync_database_url


def migration_database_url(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    fields = {
        key: env.get(f"MIGRATION_DATABASE_{key}")
        for key in ("HOST", "PORT", "NAME", "USER", "PASSWORD", "SSLMODE")
    }
    if any(value not in (None, "") for value in fields.values()):
        missing = sorted(key for key, value in fields.items() if value in (None, ""))
        if missing:
            raise ValueError("Incomplete migration database fields: " + ", ".join(missing))
        try:
            port = int(fields["PORT"])
            if not 1 <= port <= 65535:
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError("Invalid migration database port") from None
        value = build_database_url(
            drivername="postgresql+psycopg",
            host=fields["HOST"],
            port=port,
            database=fields["NAME"],
            username=fields["USER"],
            password=fields["PASSWORD"],
            sslmode=fields["SSLMODE"],
        )
    else:
        value = env.get("MIGRATION_DATABASE_URL")
        if not value:
            raise ValueError("Migration database configuration required")
    try:
        url = make_url(value)
        valid = url.drivername in {"postgresql+asyncpg", "postgresql+psycopg"} and bool(
            url.host and url.database and url.username
        )
    except Exception:
        raise ValueError("Invalid migration database URL") from None
    if not valid:
        raise ValueError("Invalid migration database URL")
    if env.get("APP_ENV", "").lower() in {"staging", "production"}:
        if url.query.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
            raise ValueError("Remote migrations require TLS")
    return build_sync_database_url(value)
