"""Contracts shared by every transactional email template."""

from __future__ import annotations

import re

import pytest

from app.integrations.email.templates.admin_invitation import (
    AdminInvitationContext,
    render_admin_invitation,
)
from app.integrations.email.templates.base import (
    LEGAL_TEXT,
    LOGO_URL,
    SUPPORT_EMAIL,
    TransactionalEmailContent,
)
from app.integrations.email.templates.candidate_account_activation import (
    CandidateAccountActivationContext,
    render_candidate_account_activation,
)
from app.integrations.email.templates.employer_verification import (
    EmployerVerificationContext,
    render_employer_verification,
)
from app.integrations.email.templates.institution_verification import (
    InstitutionVerificationContext,
    render_institution_verification,
)
from app.integrations.email.templates.password_reset import (
    PasswordResetContext,
    render_password_reset,
)
from app.integrations.email.templates.set_password_otp import (
    SetPasswordOtpContext,
    render_set_password_otp,
)
from app.integrations.email.templates.signup_otp import SignupOtpContext, render_signup_otp
from app.integrations.email.templates.team_invitation import (
    TeamInvitationContext,
    render_team_invitation,
)
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
        lambda: render_set_password_otp(
            SetPasswordOtpContext(code="123456", ttl_minutes=10, first_name="Aman")
        ),
        lambda: render_password_reset(
            PasswordResetContext(reset_token="reset-token", ttl_minutes=30)
        ),
        lambda: render_admin_invitation(
            AdminInvitationContext(
                invited_role_label="Support",
                invitation_url="https://admin.example.com/admin/accept-invitation#token=single-use-token",
                expires_at_iso="2026-08-30T10:00:00+00:00",
            )
        ),
        lambda: render_candidate_account_activation(
            CandidateAccountActivationContext(
                candidate_name="Candidate",
                activation_url="https://app.example.com/activate/token",
                expires_at_iso="2026-08-30T10:00:00+00:00",
            )
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
        lambda: render_institution_verification(
            InstitutionVerificationContext(
                contact_name="Registrar",
                subject_name="Candidate",
                institution_name="Example University",
                degree="BSc",
                programme="Computer Science",
                review_url="https://app.example.com/education/token",
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
        lambda: render_team_invitation(
            TeamInvitationContext(
                organization_name="Example Company",
                inviter_name="Hiring Manager",
                invited_role_label="Recruiter",
                invitation_url="https://app.example.com/team/token",
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
    assert SUPPORT_EMAIL == "contact@kairoid.com"
    assert "KairoID" in rendered_template.html_body
    assert "Trust that travels." in rendered_template.html_body
    assert "KairoID" in rendered_template.text_body
    assert "Trust that travels." in rendered_template.text_body
    assert LOGO_URL in rendered_template.html_body
    assert 'alt="KairoID"' in rendered_template.html_body
    assert LEGAL_TEXT in rendered_template.html_body
    assert LEGAL_TEXT in rendered_template.text_body
    assert re.search(r"\bKairo\b", rendered_template.subject) is None
    assert re.search(r"\bKairo\b", rendered_template.html_body) is None
    assert re.search(r"\bKairo\b", rendered_template.text_body) is None


def test_signup_otp_contains_code_expiry_and_security_notice() -> None:
    content = render_signup_otp(SignupOtpContext(code="654321", ttl_minutes=12))

    assert "654321" in content.html_body
    assert "654321" in content.text_body
    assert "12 minutes" in content.html_body
    assert "12 minutes" in content.text_body
    assert "never ask you to share this code" in content.text_body


def test_set_password_otp_uses_branded_copy_preheader_and_personalization() -> None:
    content = render_set_password_otp(
        SetPasswordOtpContext(code="654321", ttl_minutes=10, first_name="Aman")
    )

    assert content.subject == "Your KairoID verification code"
    assert "Hi Aman," in content.html_body
    assert "Hi Aman," in content.text_body
    assert (
        "Use this code to set your KairoID password. It expires in 10 minutes." in content.html_body
    )
    assert "654321" in content.html_body
    assert "654321" in content.text_body
    assert "email, phone, or chat" in content.text_body


def test_set_password_otp_uses_safe_greeting_fallback() -> None:
    content = render_set_password_otp(SetPasswordOtpContext(code="654321", ttl_minutes=10))

    assert "Hi there," in content.html_body
    assert "Hi there," in content.text_body
    assert "undefined" not in content.html_body
    assert "null" not in content.html_body


def test_password_reset_contains_token_expiry_and_security_notice() -> None:
    content = render_password_reset(
        PasswordResetContext(reset_token="one-time-reset", ttl_minutes=30)
    )

    assert "one-time-reset" in content.html_body
    assert "one-time-reset" in content.text_body
    assert "30 minutes" in content.html_body
    assert "30 minutes" in content.text_body
    assert "Never share this token" in content.text_body


def test_password_reset_prefers_reset_link_when_available() -> None:
    reset_url = (
        "https://institution-staging.d3lrsnjzo6p8fc.amplifyapp.com/"
        "institution/login?reset_token=opaque-reset-token"
    )
    content = render_password_reset(
        PasswordResetContext(
            reset_token="one-time-reset",
            ttl_minutes=30,
            reset_url=reset_url,
        )
    )

    assert "Reset password" in content.html_body
    assert reset_url in content.html_body
    assert reset_url in content.text_body
    assert "Password reset token:" not in content.text_body


def test_admin_invitation_uses_acceptance_cta_without_standalone_token() -> None:
    raw_token = "single-use-admin-token-1234567890"
    invitation_url = f"https://admin.example.com/admin/accept-invitation#token={raw_token}"
    content = render_admin_invitation(
        AdminInvitationContext(
            invited_role_label="Support",
            invitation_url=invitation_url,
            expires_at_iso="2026-08-30T10:00:00+00:00",
        )
    )

    assert "Accept admin invitation" in content.html_body
    assert invitation_url in content.text_body
    assert "Sanctioned role: Support" in content.text_body
    assert "2026-08-30T10:00:00+00:00" in content.text_body
    assert "Admin invitation token:" not in content.text_body
    assert "Use this token" not in content.html_body
    assert content.text_body.count(raw_token) == 1


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


def test_candidate_activation_names_the_server_resolved_client() -> None:
    content = render_candidate_account_activation(
        CandidateAccountActivationContext(
            candidate_name="Candidate",
            activation_url="https://app.example.com/activate/token",
            expires_at_iso="2026-11-20T10:00:00+00:00",
            organization_name="Godress Pharma Pvt. Ltd.",
        )
    )

    assert content.subject == "Godress Pharma Pvt. Ltd. has invited you to join KairoID"
    assert "Godress Pharma Pvt. Ltd. has invited you to join KairoID" in content.text_body
    assert "KairoID is facilitating this invitation on their behalf" in content.text_body
    assert "Godress Pharma Pvt. Ltd." in content.html_body
