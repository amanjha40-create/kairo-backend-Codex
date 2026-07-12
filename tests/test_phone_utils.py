"""Phone normalization coverage for staged signup."""

from __future__ import annotations

import pytest

from app.auth.phone_utils import mask_phone, normalize_phone
from app.config import get_settings
from app.exceptions import ValidationAppError


def test_normalize_phone_accepts_e164() -> None:
    settings = get_settings()
    assert normalize_phone("+919876543210", settings) == "+919876543210"


def test_normalize_phone_applies_default_country_code() -> None:
    settings = get_settings()
    assert normalize_phone("9876543210", settings) == "+919876543210"


def test_normalize_phone_rejects_invalid_number() -> None:
    settings = get_settings()
    with pytest.raises(ValidationAppError):
        normalize_phone("123", settings)


def test_mask_phone() -> None:
    assert mask_phone("+919876543210") == "+91******3210"
