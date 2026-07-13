"""Phone normalization helpers for staged signup."""

from __future__ import annotations

import re

from app.config import Settings
from app.exceptions import ValidationAppError

_NON_DIGIT_RE = re.compile(r"[^\d+]")


def normalize_phone(raw_phone: str, settings: Settings) -> str:
    """Normalize to E.164 using a configurable default country code when needed."""

    cleaned = _NON_DIGIT_RE.sub("", raw_phone.strip())
    if not cleaned:
        raise ValidationAppError("Phone number is required")

    if cleaned.startswith("00"):
        cleaned = f"+{cleaned[2:]}"
    elif cleaned.startswith("+"):
        pass
    else:
        digits = re.sub(r"\D", "", cleaned)
        if len(digits) == 10:
            country = settings.phone_default_country_code.strip()
            if not country.startswith("+"):
                country = f"+{country}"
            cleaned = f"{country}{digits}"
        else:
            cleaned = f"+{digits}"

    digits_only = re.sub(r"\D", "", cleaned)
    if not cleaned.startswith("+") or not digits_only.isdigit() or not 8 <= len(digits_only) <= 15:
        raise ValidationAppError("Phone number must be a valid E.164 number")

    return f"+{digits_only}"


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) <= 4:
        return phone
    country_len = max(1, len(digits) - 10)
    country = digits[:country_len]
    local = digits[country_len:]
    return f"+{country}{'*' * max(len(local) - 4, 2)}{local[-4:]}"
