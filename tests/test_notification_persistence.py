"""Rollback-only local database checks for notification persistence and isolation."""

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import Settings
from app.exceptions import NotFoundError
from app.models import User
from app.schemas.pagination import ListQueryParams
from app.services.notification_in_app_channel import NotificationInAppChannel
from app.services.notification_service import NotificationService
from app.services.verification_notification import notify_verification_attention
from app.services.verification_request_admin_review_service import (
    VerificationRequestAdminReviewService,
)
from tests.test_verification_notification_emission import request_fixture


@pytest.mark.asyncio
@pytest.mark.integration
async def test_committed_notices_persist_once_and_read_state_is_recipient_scoped():
    url = os.environ["DATABASE_URL"]
    if "@127.0.0.1:" not in url and "@localhost:" not in url:
        pytest.skip("Local isolated database only")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    owner = User(email=f"notification-{uuid4()}@example.invalid")
                    other = User(email=f"notification-{uuid4()}@example.invalid")
                    session.add_all([owner, other])
                    await session.flush()
                    service = NotificationService(session, Settings())
                    # Block external delivery while retaining real notification persistence.
                    service._dispatcher = SimpleNamespace(dispatch=NotificationInAppChannel().send)
                    workflow = VerificationRequestAdminReviewService.__new__(
                        VerificationRequestAdminReviewService
                    )
                    workflow._notifications, workflow._session = service, session
                    request = request_fixture()
                    request.subject_user_id = owner.id
                    for outcome in ("verified", "rejected", "unable_to_verify"):
                        for _ in range(2):
                            await workflow._notify_finalization(request, owner.id, outcome)
                    event = SimpleNamespace(public_id=uuid4())
                    for _ in range(2):
                        await notify_verification_attention(service, session, request, event)
                    page = await service.list_user_notifications(owner.id, ListQueryParams())
                    assert page.total == 4
                    assert (await service.unread_count(owner.id)).unread_count == 4
                    assert (
                        await service.list_user_notifications(other.id, ListQueryParams())
                    ).total == 0
                    notice_id = page.items[0].public_id
                    with pytest.raises(NotFoundError):
                        await service.mark_user_read(other.id, notice_id)
                    await service.mark_user_read(owner.id, notice_id)
                    await service.mark_user_read(owner.id, notice_id)
                    assert (await service.unread_count(owner.id)).unread_count == 3
                    assert await service.mark_user_read_all(owner.id) == 3
                    assert (await service.unread_count(owner.id)).unread_count == 0
            finally:
                await outer.rollback()
    finally:
        await engine.dispose()
