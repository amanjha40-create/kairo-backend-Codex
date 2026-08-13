"""Unit tests for email template rendering."""

from __future__ import annotations

import pytest

from app.integrations.email.renderer import EmailTemplateRenderer
from app.integrations.email.templates import DEFAULT_TEMPLATE_VERSION, EmailTemplateKey


def test_render_trust_invitation_template() -> None:
    renderer = EmailTemplateRenderer()

    message = renderer.render(
        template_key=EmailTemplateKey.TRUST_INVITATION.value,
        to_email="aman3@test.com",
        data={
            "organization_name": "Kairo Labs",
            "subject_name": "Aman Jha",
            "invitation_url": "https://example.com/invite/token",
            "expires_at_iso": "2026-07-10T12:00:00+00:00",
        },
    )

    assert message.template_key == EmailTemplateKey.TRUST_INVITATION.value
    assert message.template_version == DEFAULT_TEMPLATE_VERSION
    assert message.to_email == "aman3@test.com"
    assert "Kairo Labs" in message.subject
    assert "Open your invitation" in message.text_body
    assert "invitation_url" not in message.audit_payload
    assert message.audit_payload["organization_name"] == "Kairo Labs"


@pytest.mark.parametrize(
    ("template_key", "data", "expected_phrase"),
    [
        (
            EmailTemplateKey.SIGNUP_OTP.value,
            {"code": "123456", "ttl_minutes": 10},
            "verification code",
        ),
        (
            EmailTemplateKey.PASSWORD_RESET.value,
            {"reset_token": "reset-token", "ttl_minutes": 15},
            "password reset token",
        ),
        (
            EmailTemplateKey.EMPLOYER_VERIFICATION.value,
            {
                "contact_name": "Reviewer",
                "subject_full_name": "Candidate",
                "employer_name": "Example Company",
                "job_title": "Engineer",
                "relationship": "HR",
                "review_url": "https://example.com/review/token",
                "ttl_hours": 72,
            },
            "verify their employment",
        ),
    ],
)
def test_render_additional_transactional_templates(
    template_key: str,
    data: dict[str, object],
    expected_phrase: str,
) -> None:
    renderer = EmailTemplateRenderer()

    message = renderer.render(
        template_key=template_key,
        to_email="aman3@test.com",
        data=data,
    )

    assert message.template_key == template_key
    assert expected_phrase in message.text_body.lower()


def test_render_contact_form_submission_template() -> None:
    renderer = EmailTemplateRenderer()

    message = renderer.render(
        template_key=EmailTemplateKey.CONTACT_FORM_SUBMISSION.value,
        to_email="contact@kairoid.com",
        data={
            "full_name": "Aman Jha",
            "work_email": "aman@example.com",
            "company": "Kairo Labs",
            "hires_per_month": "25",
            "message": "We want to see a demo.",
            "submitted_at_iso": "2026-08-12T10:00:00+00:00",
            "request_id": "req-123",
        },
    )

    assert message.template_key == EmailTemplateKey.CONTACT_FORM_SUBMISSION.value
    assert message.template_version == DEFAULT_TEMPLATE_VERSION
    assert message.to_email == "contact@kairoid.com"
    assert message.reply_to == "aman@example.com"
    assert "Kairo Labs" in message.subject
    assert "We want to see a demo." in message.text_body
    assert message.audit_payload["work_email_domain"] == "example.com"
    assert message.audit_payload["request_id"] == "req-123"
    assert "message" not in message.audit_payload


def test_unknown_template_key_is_rejected() -> None:
    renderer = EmailTemplateRenderer()

    with pytest.raises(ValueError, match="Unsupported email template"):
        renderer.render(
            template_key="missing_template",
            to_email="aman3@test.com",
            data={},
        )
