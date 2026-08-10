"""Transactional email template registry and shared constants."""

from __future__ import annotations

from enum import StrEnum


class EmailTemplateKey(StrEnum):
    SIGNUP_OTP = "signup_otp"
    PASSWORD_RESET = "password_reset"
    EMPLOYER_VERIFICATION = "employer_verification"
    TRUST_INVITATION = "trust_invitation"
    VERIFICATION_COMPLETED = "verification_completed"


DEFAULT_TEMPLATE_VERSION = "v1"


__all__ = ["DEFAULT_TEMPLATE_VERSION", "EmailTemplateKey"]
