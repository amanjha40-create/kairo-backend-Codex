"""Candidate-facing notices for committed verification workflow transitions."""

import logging

from app.notifications.contracts import NotificationRequest

logger = logging.getLogger(__name__)

OUTCOME_PRESENTATION = {
    "verified": ("Verification approved", "Your verification has been approved."),
    "rejected": (
        "Verification rejected",
        "Your verification was rejected. Open the request for details.",
    ),
    "unable_to_verify": (
        "Verification could not be completed",
        "Your verification could not be completed. Open the request for details.",
    ),
}


async def notify_verification_attention(
    notifications, session, request, event, *, actor_user_id=None
):
    """Run only after the workflow commit; never include private review comments."""
    try:
        await notifications.create_and_dispatch(
            NotificationRequest(
                event_type="verification_information_required",
                channel="in_app",
                template_key="verification_in_app",
                category="verification",
                title="Verification needs your attention",
                body=(
                    "Additional information or corrections are needed. "
                    "Open your verification request to continue."
                ),
                recipient_user_id=request.subject_user_id,
                dedupe_key=f"verification-attention:{event.public_id}:candidate",
                metadata={"verification_request_public_id": str(request.public_id)},
            ),
            actor_user_id=actor_user_id,
        )
    except Exception:
        await session.rollback()
        logger.warning("verification_attention_notification_failed")
