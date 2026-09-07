"""Regression coverage for credentials in request and exception logging."""

from __future__ import annotations

import pytest

from app.exceptions.handlers import _redacted_traceback
from app.logging.request_redaction import redact_request_credentials


@pytest.mark.parametrize(
    ("target", "safe_target"),
    [
        (
            "/api/v1/public/employer-verifications/verifier-secret/verify",
            "/api/v1/public/employer-verifications/[REDACTED]/verify",
        ),
        (
            "/employer-verification/verifier-secret",
            "/employer-verification/[REDACTED]",
        ),
        (
            "/api/v1/public/passport/passport-secret",
            "/api/v1/public/passport/[REDACTED]",
        ),
        (
            "/trust-invitations/invitation-secret/accept",
            "/trust-invitations/[REDACTED]/accept",
        ),
        (
            "https://candidate.example/reset-password-confirm?token=reset-secret&page=1",
            "https://candidate.example/reset-password-confirm?token=[REDACTED]&page=1",
        ),
        (
            "/api/v1/auth/google/callback?code=google-code&state=oauth-state",
            "/api/v1/auth/google/callback?code=[REDACTED]&state=[REDACTED]",
        ),
    ],
)
def test_redact_request_credentials_removes_sensitive_url_values(target: str, safe_target: str) -> None:
    assert redact_request_credentials(target) == safe_target


def test_redact_request_credentials_keeps_non_sensitive_path_useful() -> None:
    assert redact_request_credentials("/api/v1/health/ready?page=2") == "/api/v1/health/ready?page=2"


def test_exception_traceback_does_not_reintroduce_url_credential() -> None:
    secret = "verifier-secret"
    try:
        raise RuntimeError(f"request failed at /api/v1/public/employer-verifications/{secret}")
    except RuntimeError as exc:
        logged_traceback = _redacted_traceback(exc)

    assert secret not in logged_traceback
    assert "/api/v1/public/employer-verifications/[REDACTED]" in logged_traceback
