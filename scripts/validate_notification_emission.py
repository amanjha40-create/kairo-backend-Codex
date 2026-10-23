"""One bounded, rollback-only Staging/local notification contract check. No delivery."""

import asyncio
import json
import logging
import os
import signal
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.services import get_notification_service
from app.api.v1.routes.notifications import user_router
from app.auth.deps import get_current_user
from app.config import get_settings
from app.db.session import engine
from app.exceptions import AppException
from app.exceptions.handlers import app_exception_handler
from app.models import User
from app.services.account_notification import (
    notify_identity_result,
    notify_password_changed,
    notify_team_invitation,
)
from app.services.notification_dispatcher import NotificationDispatcher
from app.services.notification_in_app_channel import NotificationInAppChannel
from app.services.notification_service import NotificationService
from app.services.trust_invitation_service import TrustInvitationService
from app.services.verification_notification import notify_verification_attention
from app.services.verification_request_admin_review_service import (
    VerificationRequestAdminReviewService,
)
from app.trust_invitations.enums import TrustInvitationEventType


async def main():
    environment = os.environ["APP_ENV"]
    assert environment in {"test", "staging"}
    if environment == "test":
        assert engine.url.host in {"localhost", "127.0.0.1"}
    settings = get_settings()
    recipient_ids = [uuid4(), uuid4()]
    original_dispatch = NotificationDispatcher.dispatch
    deliveries = []

    async def local_delivery(self, notification):
        deliveries.append(notification.event_type)
        return await NotificationInAppChannel().send(notification)

    # Even email-channel notices use the local handler: no email/SMS/provider path runs.
    NotificationDispatcher.dispatch = local_delivery
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            await connection.execute(text("SET LOCAL statement_timeout='20s'"))
            await connection.execute(text("SET LOCAL lock_timeout='5s'"))
            if environment == "staging":
                assert (
                    await connection.scalar(
                        text("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()")
                    )
                    is True
                )
            assert list(
                await connection.scalars(text("SELECT version_num FROM alembic_version"))
            ) == ["095"]
            try:
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    users = [
                        User(
                            id=value,
                            email=f"notification-{value}@example.invalid",
                            full_name="Synthetic Notification",
                            is_active=True,
                            email_verified_at=datetime.now(UTC),
                        )
                        for value in recipient_ids
                    ]
                    session.add_all(users)
                    await session.commit()
                    service = NotificationService(session, settings)
                    workflow = VerificationRequestAdminReviewService.__new__(
                        VerificationRequestAdminReviewService
                    )
                    workflow._notifications, workflow._session = service, session
                    request = SimpleNamespace(
                        public_id=uuid4(),
                        subject_user_id=users[0].id,
                        subject_email=users[0].email,
                        subject_name="Synthetic",
                        organization=None,
                        target_organization_name="Synthetic",
                        request_type="education",
                        employment_id=None,
                        education_id=None,
                    )
                    for outcome in ("verified", "rejected", "unable_to_verify"):
                        for _ in range(2):
                            await workflow._notify_finalization(request, users[0].id, outcome)
                    event = SimpleNamespace(public_id=uuid4())
                    for _ in range(2):
                        await notify_verification_attention(service, session, request, event)
                    invitation = SimpleNamespace(
                        public_id=uuid4(),
                        subject_email=users[0].email,
                        subject_name="Synthetic",
                        organization=SimpleNamespace(name="Synthetic", public_id=uuid4()),
                        expires_at=datetime.now(UTC),
                        purpose="Synthetic notification test",
                    )
                    trust = TrustInvitationService(session, settings)
                    for _ in range(2):
                        await trust._deliver_invitation(
                            invitation,
                            actor_user_id=users[0].id,
                            trigger_event=TrustInvitationEventType.SENT,
                            record_event=False,
                        )
                    for outcome in ("VERIFIED_MATCH", "PARTIAL_MATCH", "UNABLE_TO_VERIFY"):
                        await notify_identity_result(
                            session,
                            settings,
                            users[0].id,
                            document_type="DRVLC",
                            result=outcome,
                            event_id=str(uuid4()),
                        )
                    await notify_password_changed(session, settings, users[0].id, uuid4())
                    team_invitation = SimpleNamespace(
                        public_id=uuid4(),
                        token_version=1,
                        invitee_email=users[0].email,
                    )
                    for _ in range(2):
                        await notify_team_invitation(session, settings, team_invitation)
                    api = FastAPI()
                    api.add_exception_handler(AppException, app_exception_handler)
                    api.include_router(user_router, prefix="/api/v1")
                    current = SimpleNamespace(id=users[0].id, role="user")
                    api.dependency_overrides[get_notification_service] = lambda: service
                    api.dependency_overrides[get_current_user] = lambda: current
                    async with AsyncClient(
                        transport=ASGITransport(app=api), base_url="http://synthetic"
                    ) as client:
                        response = await client.get("/api/v1/notifications")
                        assert response.status_code == 200
                        page = response.json()
                        assert page["total"] == 10
                        assert len(deliveries) == 10
                        rows = page["items"]
                        assert all(row["read_at"] is None for row in rows)
                        final = [
                            row for row in rows if row["event_type"] == "verification_completed"
                        ]
                        assert {row["metadata"]["outcome"] for row in final} == {
                            "verified",
                            "rejected",
                            "unable_to_verify",
                        }
                        assert all(
                            row["metadata"]["verification_request_public_id"]
                            == str(request.public_id)
                            for row in final
                        )
                        assert {row["title"] for row in final} == {
                            "Verification approved",
                            "Verification rejected",
                            "Verification could not be completed",
                        }
                        unread = await client.get("/api/v1/notifications/unread-count")
                        assert unread.json()["unread_count"] == 10
                        notice_id = rows[0]["public_id"]
                        current.id = users[1].id
                        assert (await client.get("/api/v1/notifications")).json()["total"] == 0
                        assert (
                            await client.post(f"/api/v1/notifications/{notice_id}/read")
                        ).status_code == 404
                        current.id = users[0].id
                        for _ in range(2):
                            assert (
                                await client.post(f"/api/v1/notifications/{notice_id}/read")
                            ).status_code == 204
                        assert (await client.get("/api/v1/notifications/unread-count")).json()[
                            "unread_count"
                        ] == 9
                        assert (
                            await client.post("/api/v1/notifications/read-all")
                        ).status_code == 204
                        assert (await client.get("/api/v1/notifications/unread-count")).json()[
                            "unread_count"
                        ] == 0
            finally:
                assert outer.is_active
                await outer.rollback()
        async with engine.connect() as connection:
            assert (
                await connection.scalar(select(User.id).where(User.id.in_(recipient_ids))) is None
            )
    finally:
        NotificationDispatcher.dispatch = original_dispatch
        await engine.dispose()
    print(
        "NOTIFICATION_EVIDENCE="
        + json.dumps(
            {
                "passed": True,
                "db": "095",
                "approval": True,
                "rejection": True,
                "importantUpdate": True,
                "invitation": True,
                "identity": True,
                "security": True,
                "duplicateSuppression": True,
                "recipientIsolation": True,
                "apiReadState": True,
                "rollbackVerified": True,
                "externalDelivery": False,
                "notifications": 10,
            }
        )
    )


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    signal.signal(signal.SIGALRM, lambda *args: (_ for _ in ()).throw(TimeoutError()))
    signal.alarm(180)
    try:
        asyncio.run(main())
    except Exception as error:
        print(
            "NOTIFICATION_EVIDENCE=" + json.dumps({"passed": False, "error": type(error).__name__})
        )
        raise SystemExit(1) from None
