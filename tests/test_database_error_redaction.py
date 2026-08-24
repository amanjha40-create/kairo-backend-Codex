from __future__ import annotations

import logging

import pytest
from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from app.exceptions.handlers import sqlalchemy_exception_handler, unhandled_exception_handler


@pytest.mark.asyncio
async def test_sqlalchemy_handler_redacts_database_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR)

    request = Request({"type": "http"})
    exc = SQLAlchemyError(
        "connection failed for postgresql+asyncpg://user:super-secret@db.example:5432/kairo"
    )

    response = await sqlalchemy_exception_handler(request, exc)

    assert response.status_code == 500
    logs = " ".join(record.getMessage() for record in caplog.records)
    assert "super-secret" not in logs
    assert "user:***@" in logs


@pytest.mark.asyncio
async def test_unhandled_handler_redacts_password_like_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR)

    request = Request({"type": "http"})

    try:
        raise RuntimeError(
            "password=super-secret DATABASE_URL=postgresql+asyncpg://user:pw@db/kairo"
        )
    except RuntimeError as exc:
        response = await unhandled_exception_handler(request, exc)

    assert response.status_code == 500
    logs = " ".join(record.getMessage() for record in caplog.records)
    assert "super-secret" not in logs
    assert "password=***" in logs
    assert "user:***@" in logs
