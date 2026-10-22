"""Programmatic Alembic configuration without runtime settings or URL logging."""

import os
from collections.abc import Mapping

from alembic.config import Config

from app.db.migration_config import migration_database_url


def build_migration_config(
    environ: Mapping[str, str] | None = None, *, config_path: str = "alembic.ini"
) -> Config:
    config = Config(config_path)
    # Attributes avoid ConfigParser interpolation of percent-encoded passwords.
    config.attributes["migration_database_url"] = migration_database_url(environ)
    config.attributes["configure_logger"] = False
    return config


def build_staging_migration_config(
    environ: Mapping[str, str] | None = None, *, config_path: str = "alembic.ini"
) -> Config:
    """Explicit TLS binding for the structured Staging migrator, not a secret edit."""
    binding = dict(os.environ if environ is None else environ)
    if binding.get("APP_ENV") != "staging":
        raise ValueError("Staging migration harness requires APP_ENV=staging")
    # Preserve certificate verification if configured; otherwise require TLS,
    # never libpq's opportunistic prefer/allow behavior or plaintext disable.
    if binding.get("MIGRATION_DATABASE_SSLMODE") not in {"verify-ca", "verify-full"}:
        binding["MIGRATION_DATABASE_SSLMODE"] = "require"
    return build_migration_config(binding, config_path=config_path)
