"""Signup email masking and OTP helpers."""

from __future__ import annotations

from app.auth.email_utils import mask_email, normalize_email
from app.auth.signup_otp import generate_otp_code, hash_otp_code, verify_otp_code


def test_normalize_email() -> None:
    assert normalize_email("  User@Example.COM ") == "user@example.com"


def test_mask_email() -> None:
    assert mask_email("ankit@gmail.com") == "a***t@gmail.com"
    assert mask_email("ab@x.com") == "a*@x.com"


def test_otp_hash_roundtrip() -> None:
    code = generate_otp_code()
    assert len(code) == 6
    assert code.isdigit()
    hashed = hash_otp_code(code)
    assert verify_otp_code(code, hashed)
    assert not verify_otp_code("000000", hashed)
