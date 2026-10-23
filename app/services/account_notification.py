"""Small, privacy-safe inbox notices for committed account events."""

import logging

from app.notifications.contracts import NotificationRequest
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


async def notify_password_changed(session, settings, user_id, event_id):
    await _send(
        session,
        settings,
        NotificationRequest(
            event_type="password_changed",
            channel="in_app",
            template_key="account_in_app",
            category="security",
            title="Password updated",
            body=(
                "Your KairoID password was updated. "
                "If this was not you, review your account security."
            ),
            recipient_user_id=user_id,
            dedupe_key=f"password-changed:{event_id}",
        ),
    )


async def notify_team_invitation(session, settings, invitation):
    from app.repositories.user import UserRepository

    user = await UserRepository(session).get_by_email(invitation.invitee_email.strip().lower())
    if user is None or not user.is_active or user.email_verified_at is None:
        return
    await _send(
        session,
        settings,
        NotificationRequest(
            event_type="team_invitation_created",
            channel="in_app",
            template_key="account_in_app",
            category="system",
            title="Organization invitation",
            body=("You have an organization invitation. "
                  "Use the invitation email to review and respond."),
            recipient_user_id=user.id,
            dedupe_key=f"team-invitation:{invitation.public_id}:{invitation.token_version}",
            metadata={"organization_invitation_public_id": str(invitation.public_id)},
        ),
    )


async def notify_identity_result(session, settings, user_id, *, document_type, result, event_id):
    title, body = {
        "VERIFIED_MATCH": (
            "Identity verification completed",
            "Your document verification matched your profile.",
        ),
        "PARTIAL_MATCH": (
            "Identity verification needs attention",
            "Your document verification is partial. Review the result and your profile.",
        ),
    }.get(
        result,
        (
            "Identity verification could not be completed",
            "Review your document verification result for details.",
        ),
    )
    await _send(
        session,
        settings,
        NotificationRequest(
            event_type="identity_verification_completed",
            channel="in_app",
            template_key="identity_in_app",
            category="verification",
            title=title,
            body=body,
            recipient_user_id=user_id,
            dedupe_key=f"identity-result:{event_id}",
            metadata={"document_type": document_type, "outcome": result},
        ),
    )


async def _send(session, settings, request):
    try:
        await NotificationService(session, settings).create_and_dispatch(request)
    except Exception:
        await session.rollback()
        logger.warning(
            "account_inbox_notification_failed", extra={"event_type": request.event_type}
        )
