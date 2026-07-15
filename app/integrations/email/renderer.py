"""Template-driven email rendering."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.integrations.email.templates import DEFAULT_TEMPLATE_VERSION, EmailTemplateKey
from app.integrations.email.templates.trust_invitation import (
    TrustInvitationContext,
    render_trust_invitation,
)
from app.integrations.email.templates.verification_completed import (
    VerificationCompletedContext,
    render_verification_completed,
)
from app.schemas.email_delivery import (
    RenderedEmailMessage,
    TrustInvitationEmailTemplateData,
    VerificationCompletedEmailTemplateData,
)


RendererFn = Callable[[str, dict[str, Any]], RenderedEmailMessage]


def _render_trust_invitation(to_email: str, data: dict[str, Any]) -> RenderedEmailMessage:
    payload = TrustInvitationEmailTemplateData.model_validate(data)
    content = render_trust_invitation(
        TrustInvitationContext(
            organization_name=payload.organization_name,
            subject_name=payload.subject_name,
            invitation_url=payload.invitation_url,
            expires_at_iso=payload.expires_at_iso,
        )
    )
    return RenderedEmailMessage(
        template_key=EmailTemplateKey.TRUST_INVITATION.value,
        template_version=DEFAULT_TEMPLATE_VERSION,
        to_email=to_email,
        subject=content.subject,
        text_body=content.text_body,
        html_body=content.html_body,
        audit_payload={
            "organization_name": payload.organization_name,
            "subject_name": payload.subject_name,
            "expires_at_iso": payload.expires_at_iso,
        },
    )


def _render_verification_completed(to_email: str, data: dict[str, Any]) -> RenderedEmailMessage:
    payload = VerificationCompletedEmailTemplateData.model_validate(data)
    content = render_verification_completed(
        VerificationCompletedContext(
            subject_name=payload.subject_name,
            organization_name=payload.organization_name,
            request_type=payload.request_type,
            completed_at_iso=payload.completed_at_iso,
        )
    )
    return RenderedEmailMessage(
        template_key=EmailTemplateKey.VERIFICATION_COMPLETED.value,
        template_version=DEFAULT_TEMPLATE_VERSION,
        to_email=to_email,
        subject=content.subject,
        text_body=content.text_body,
        html_body=content.html_body,
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
