"""Template-driven email rendering."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.integrations.email.templates import DEFAULT_TEMPLATE_VERSION, EmailTemplateKey
from app.integrations.email.templates.contact_form_submission import (
    ContactFormSubmissionContext,
    render_contact_form_submission,
)
from app.integrations.email.templates.employer_verification import (
    EmployerVerificationContext,
    render_employer_verification,
)
from app.integrations.email.templates.password_reset import (
    PasswordResetContext,
    render_password_reset,
)
from app.integrations.email.templates.signup_otp import SignupOtpContext, render_signup_otp
from app.integrations.email.templates.trust_invitation import (
    TrustInvitationContext,
    render_trust_invitation,
)
from app.integrations.email.templates.verification_completed import (
    VerificationCompletedContext,
    render_verification_completed,
)
from app.schemas.email_delivery import (
    ContactFormSubmissionEmailTemplateData,
    EmployerVerificationEmailTemplateData,
    PasswordResetEmailTemplateData,
    RenderedEmailMessage,
    SignupOtpEmailTemplateData,
    TrustInvitationEmailTemplateData,
    VerificationCompletedEmailTemplateData,
)

RendererFn = Callable[[str, dict[str, Any]], RenderedEmailMessage]


def _render_signup_otp(to_email: str, data: dict[str, Any]) -> RenderedEmailMessage:
    payload = SignupOtpEmailTemplateData.model_validate(data)
    content = render_signup_otp(
        SignupOtpContext(
            code=payload.code,
            ttl_minutes=payload.ttl_minutes,
        )
    )
    return RenderedEmailMessage(
        template_key=EmailTemplateKey.SIGNUP_OTP.value,
        template_version=DEFAULT_TEMPLATE_VERSION,
        to_email=to_email,
        subject=content.subject,
        text_body=content.text_body,
        html_body=content.html_body,
        audit_payload={
            "ttl_minutes": payload.ttl_minutes,
        },
    )


def _render_password_reset(to_email: str, data: dict[str, Any]) -> RenderedEmailMessage:
    payload = PasswordResetEmailTemplateData.model_validate(data)
    content = render_password_reset(
        PasswordResetContext(
            reset_token=payload.reset_token,
            ttl_minutes=payload.ttl_minutes,
        )
    )
    return RenderedEmailMessage(
        template_key=EmailTemplateKey.PASSWORD_RESET.value,
        template_version=DEFAULT_TEMPLATE_VERSION,
        to_email=to_email,
        subject=content.subject,
        text_body=content.text_body,
        html_body=content.html_body,
        audit_payload={
            "ttl_minutes": payload.ttl_minutes,
        },
    )


def _render_employer_verification(to_email: str, data: dict[str, Any]) -> RenderedEmailMessage:
    payload = EmployerVerificationEmailTemplateData.model_validate(data)
    content = render_employer_verification(
        EmployerVerificationContext(
            contact_name=payload.contact_name,
            subject_full_name=payload.subject_full_name,
            employer_name=payload.employer_name,
            job_title=payload.job_title,
            relationship=payload.relationship,
            review_url=payload.review_url,
            expires_hours=payload.ttl_hours,
        )
    )
    return RenderedEmailMessage(
        template_key=EmailTemplateKey.EMPLOYER_VERIFICATION.value,
        template_version=DEFAULT_TEMPLATE_VERSION,
        to_email=to_email,
        subject=content.subject,
        text_body=content.text_body,
        html_body=content.html_body,
        audit_payload={
            "contact_name": payload.contact_name,
            "subject_full_name": payload.subject_full_name,
            "employer_name": payload.employer_name,
            "job_title": payload.job_title,
            "relationship": payload.relationship,
            "ttl_hours": payload.ttl_hours,
        },
    )


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


def _render_contact_form_submission(to_email: str, data: dict[str, Any]) -> RenderedEmailMessage:
    payload = ContactFormSubmissionEmailTemplateData.model_validate(data)
    content = render_contact_form_submission(
        ContactFormSubmissionContext(
            full_name=payload.full_name,
            work_email=payload.work_email,
            company=payload.company,
            hires_per_month=payload.hires_per_month,
            message=payload.message,
            submitted_at_iso=payload.submitted_at_iso,
            request_id=payload.request_id,
        )
    )
    return RenderedEmailMessage(
        template_key=EmailTemplateKey.CONTACT_FORM_SUBMISSION.value,
        template_version=DEFAULT_TEMPLATE_VERSION,
        to_email=to_email,
        subject=content.subject,
        text_body=content.text_body,
        html_body=content.html_body,
        reply_to=str(payload.work_email),
        audit_payload={
            "full_name": payload.full_name,
            "work_email_domain": payload.work_email.split("@")[-1],
            "company": payload.company,
            "hires_per_month": payload.hires_per_month,
            "submitted_at_iso": payload.submitted_at_iso,
            "request_id": payload.request_id,
            "message_length": len(payload.message),
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
            EmailTemplateKey.SIGNUP_OTP.value: _render_signup_otp,
            EmailTemplateKey.PASSWORD_RESET.value: _render_password_reset,
            EmailTemplateKey.EMPLOYER_VERIFICATION.value: _render_employer_verification,
            EmailTemplateKey.CONTACT_FORM_SUBMISSION.value: _render_contact_form_submission,
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
