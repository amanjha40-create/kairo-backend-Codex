"""Template resolution for notification center events."""

from __future__ import annotations

from app.exceptions import ValidationAppError
from app.notifications.contracts import NotificationRequest


class NotificationTemplateResolver:
    """Resolves template keys and versions from event-driven notification requests."""

    DEFAULT_TEMPLATE_BY_EVENT: dict[str, str] = {
        "trust_invitation_created": "trust_invitation",
        "verification_completed": "verification_completed",
    }

    def resolve(self, request: NotificationRequest) -> tuple[str, str]:
        template_key = request.template_key or self.DEFAULT_TEMPLATE_BY_EVENT.get(request.normalized_event_type())
        if template_key is None:
            raise ValidationAppError("Notification template could not be resolved", code="notification_template_missing")
        return template_key.strip().lower(), request.template_version.strip() or "v1"
