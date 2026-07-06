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


def test_unknown_template_key_is_rejected() -> None:
    renderer = EmailTemplateRenderer()

    with pytest.raises(ValueError, match="Unsupported email template"):
        renderer.render(
            template_key="missing_template",
            to_email="aman3@test.com",
            data={},
        )
