"""Template-driven email rendering."""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from typing import Any

from app.integrations.email.templates import DEFAULT_TEMPLATE_VERSION, EmailTemplateKey
from app.schemas.email_delivery import (
    RenderedEmailMessage,
    TrustInvitationEmailTemplateData,
    VerificationCompletedEmailTemplateData,
)


RendererFn = Callable[[str, dict[str, Any]], RenderedEmailMessage]


def _render_trust_invitation(to_email: str, data: dict[str, Any]) -> RenderedEmailMessage:
    payload = TrustInvitationEmailTemplateData.model_validate(data)
    subject = f"{payload.organization_name} invited you to Kairo"
    text_body = (
        f"Hello {payload.subject_name},\n\n"
        f"{payload.organization_name} invited you to continue a trust verification workflow on Kairo.\n\n"
        f"Open your invitation: {payload.invitation_url}\n\n"
        f"This invitation expires at {payload.expires_at_iso}.\n"
    )
    html_body = (
        "<html><body>"
        f"<p>Hello {escape(payload.subject_name)},</p>"
        f"<p>{escape(payload.organization_name)} invited you to continue a trust verification workflow on Kairo.</p>"
        f'<p><a href="{escape(payload.invitation_url)}">Open invitation</a></p>'
        f"<p>This invitation expires at {escape(payload.expires_at_iso)}.</p>"
        "</body></html>"
    )
    return RenderedEmailMessage(
        template_key=EmailTemplateKey.TRUST_INVITATION.value,
        template_version=DEFAULT_TEMPLATE_VERSION,
        to_email=to_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        audit_payload={
            "organization_name": payload.organization_name,
            "subject_name": payload.subject_name,
            "expires_at_iso": payload.expires_at_iso,
        },
    )


def _render_verification_completed(to_email: str, data: dict[str, Any]) -> RenderedEmailMessage:
    payload = VerificationCompletedEmailTemplateData.model_validate(data)
    request_type = payload.request_type.replace("_", " ").strip().title()
    subject = f"Your {request_type} verification is complete"
    text_body = (
        f"Hello {payload.subject_name},\n\n"
        f"Your {request_type.lower()} verification with {payload.organization_name} has been completed on Kairo.\n\n"
        f"Completed at: {payload.completed_at_iso}\n"
    )
    html_body = (
        "<html><body>"
        f"<p>Hello {escape(payload.subject_name)},</p>"
        f"<p>Your {escape(request_type.lower())} verification with {escape(payload.organization_name)} has been completed on Kairo.</p>"
        f"<p>Completed at: {escape(payload.completed_at_iso)}</p>"
        "</body></html>"
    )
    return RenderedEmailMessage(
        template_key=EmailTemplateKey.VERIFICATION_COMPLETED.value,
        template_version=DEFAULT_TEMPLATE_VERSION,
        to_email=to_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        audit_payload={
            "subject_name": payload.subject_name,
            "organization_name": payload.organization_name,
            "request_type": payload.request_type,
            "completed_at_iso": payload.completed_at_iso,
        },
    )


class EmailTemplateRenderer:
    """Central registry for transactional email rendering."""

    def __init__(self) -> None:
        self._registry: dict[str, RendererFn] = {
            EmailTemplateKey.TRUST_INVITATION.value: _render_trust_invitation,
            EmailTemplateKey.VERIFICATION_COMPLETED.value: _render_verification_completed,
        }

    def render(
        self,
        *,
        template_key: str,
        to_email: str,
        data: dict[str, Any],
    ) -> RenderedEmailMessage:
        renderer = self._registry.get(template_key)
        if renderer is None:
            msg = f"Unsupported email template: {template_key}"
            raise ValueError(msg)
        return renderer(to_email, data)
