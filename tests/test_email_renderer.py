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


def test_render_admin_invitation_keeps_tokenized_url_out_of_audit_payload() -> None:
    renderer = EmailTemplateRenderer()
    raw_token = "single-use-admin-token-1234567890"
    invitation_url = f"https://admin.example.com/admin/accept-invitation#token={raw_token}"

    message = renderer.render(
        template_key=EmailTemplateKey.ADMIN_INVITATION.value,
        to_email="invited-admin@example.com",
        data={
            "invited_role_label": "Support",
            "invitation_url": invitation_url,
            "expires_at_iso": "2026-08-30T10:00:00+00:00",
        },
    )

    assert "Accept admin invitation" in message.text_body
    assert invitation_url in message.text_body
    assert "invitation_url" not in message.audit_payload
    assert raw_token not in str(message.audit_payload)


def test_render_institution_verification_keeps_review_url_out_of_audit_payload() -> None:
    renderer = EmailTemplateRenderer()
    raw_token = "institution-magic-link-token-1234567890"
    review_url = f"https://institution.example.com/institution/verify/{raw_token}"

    message = renderer.render(
        template_key=EmailTemplateKey.INSTITUTION_VERIFICATION.value,
        to_email="registrar@example.com",
        data={
            "contact_name": "Registrar",
            "subject_name": "Candidate",
            "institution_name": "Kairo University",
            "degree": "BSc",
            "programme": "Computer Science",
            "review_url": review_url,
            "ttl_hours": 72,
        },
    )

    assert review_url in message.text_body
    assert "review_url" not in message.audit_payload
    assert raw_token not in str(message.audit_payload)


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
        (
            EmailTemplateKey.INSTITUTION_VERIFICATION.value,
            {
                "contact_name": "Registrar",
                "subject_name": "Candidate",
                "institution_name": "Kairo University",
                "degree": "BSc",
                "programme": "Computer Science",
                "review_url": "https://institution.example.com/institution/verify/token",
                "ttl_hours": 72,
            },
            "review an education claim",
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


def test_unknown_template_key_is_rejected() -> None:
    renderer = EmailTemplateRenderer()

    with pytest.raises(ValueError, match="Unsupported email template"):
        renderer.render(
            template_key="missing_template",
            to_email="aman3@test.com",
            data={},
        )
