from app.db.url import build_async_database_config, build_sync_database_url


def test_async_database_config_translates_sslmode_for_asyncpg() -> None:
    url, connect_args = build_async_database_config(
        "postgresql+asyncpg://user:password@db.example/kairo?sslmode=require"
    )

    assert url.render_as_string(hide_password=False) == "postgresql+asyncpg://user:password@db.example/kairo"
    assert connect_args == {"ssl": "require"}


def test_async_database_config_preserves_urls_without_sslmode() -> None:
    database_url = "postgresql+asyncpg://user:password@db.example/kairo?application_name=kairo"

    url, connect_args = build_async_database_config(database_url)

    assert url.render_as_string(hide_password=False) == database_url
    assert connect_args == {}


def test_alembic_database_url_keeps_sslmode_for_psycopg() -> None:
    database_url = "postgresql+asyncpg://user:password@db.example/kairo?sslmode=require"

    assert build_sync_database_url(database_url) == (
        "postgresql+psycopg://user:password@db.example/kairo?sslmode=require"
    )
