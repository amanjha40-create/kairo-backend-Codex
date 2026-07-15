"""Contracts shared by every transactional email template."""

from __future__ import annotations

import pytest

from app.integrations.email.templates.base import (
    FOOTER_TEXT,
    SUPPORT_EMAIL,
    TransactionalEmailContent,
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


@pytest.fixture(
    params=(
        lambda: render_signup_otp(SignupOtpContext(code="123456", ttl_minutes=10)),
        lambda: render_password_reset(
            PasswordResetContext(reset_token="reset-token", ttl_minutes=30)
        ),
        lambda: render_employer_verification(
            EmployerVerificationContext(
                contact_name="Reviewer",
                subject_full_name="Candidate",
                employer_name="Example Company",
                job_title="Engineer",
                relationship="HR",
                review_url="https://app.example.com/verify/token",
                expires_hours=72,
            )
        ),
        lambda: render_trust_invitation(
            TrustInvitationContext(
                organization_name="Example Company",
                subject_name="Candidate",
                invitation_url="https://app.example.com/invitation/token",
                expires_at_iso="2026-07-20T10:00:00+00:00",
            )
        ),
        lambda: render_verification_completed(
            VerificationCompletedContext(
                subject_name="Candidate",
                organization_name="Example Company",
                request_type="employment",
                completed_at_iso="2026-07-20T10:00:00+00:00",
            )
        ),
    )
)
def rendered_template(request: pytest.FixtureRequest) -> TransactionalEmailContent:
    renderer = request.param
    return renderer()


def test_every_template_has_complete_kairo_content(
    rendered_template: TransactionalEmailContent,
) -> None:
    assert rendered_template.subject.strip()
    assert rendered_template.html_body.strip()
    assert rendered_template.text_body.strip()
    assert SUPPORT_EMAIL in rendered_template.html_body
    assert SUPPORT_EMAIL in rendered_template.text_body
    assert FOOTER_TEXT in rendered_template.html_body
    assert FOOTER_TEXT in rendered_template.text_body


def test_signup_otp_contains_code_expiry_and_security_notice() -> None:
    content = render_signup_otp(SignupOtpContext(code="654321", ttl_minutes=12))

    assert "654321" in content.html_body
    assert "654321" in content.text_body
    assert "12 minutes" in content.html_body
    assert "12 minutes" in content.text_body
    assert "never ask you to share this code" in content.text_body


def test_password_reset_contains_token_expiry_and_security_notice() -> None:
    content = render_password_reset(
        PasswordResetContext(reset_token="one-time-reset", ttl_minutes=30)
    )

    assert "one-time-reset" in content.html_body
    assert "one-time-reset" in content.text_body
    assert "30 minutes" in content.html_body
    assert "30 minutes" in content.text_body
    assert "Never share this token" in content.text_body


def test_action_template_escapes_user_controlled_html_and_url() -> None:
    content = render_employer_verification(
        EmployerVerificationContext(
            contact_name='<script>alert("contact")</script>',
            subject_full_name="Candidate & Co",
            employer_name="Employer <unsafe>",
            job_title='Engineer "Lead"',
            relationship="HR & Admin",
            review_url="https://app.example.com/verify/token?a=1&b=2",
            expires_hours=48,
        )
    )

    assert "<script>" not in content.html_body
    assert "&lt;script&gt;" in content.html_body
    assert "Candidate &amp; Co" in content.html_body
    assert "Employer &lt;unsafe&gt;" in content.html_body
    assert "a=1&amp;b=2" in content.html_body
    assert "48 hours" in content.text_body


def test_generic_templates_escape_user_controlled_values() -> None:
    invitation = render_trust_invitation(
        TrustInvitationContext(
            organization_name="Org <unsafe>",
            subject_name="User & Team",
            invitation_url="https://app.example.com/invite?a=1&b=2",
            expires_at_iso="2026-07-20T10:00:00+00:00",
        )
    )
    completed = render_verification_completed(
        VerificationCompletedContext(
            subject_name="User <unsafe>",
            organization_name="Org & Co",
            request_type="employment",
            completed_at_iso="2026-07-20T10:00:00+00:00",
        )
    )

    assert "Org &lt;unsafe&gt;" in invitation.html_body
    assert "User &amp; Team" in invitation.html_body
    assert "a=1&amp;b=2" in invitation.html_body
    assert "User &lt;unsafe&gt;" in completed.html_body
    assert "Org &amp; Co" in completed.html_body
