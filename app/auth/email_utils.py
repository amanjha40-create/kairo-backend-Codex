"""Email helpers for signup verification."""

from __future__ import annotations


def normalize_email(email: str) -> str:
    return email.strip().lower()


def mask_email(email: str) -> str:
    """Mask local part for client display (e.g. a***n@gmail.com)."""

    local, sep, domain = email.partition("@")
    if not sep:
        return email
    if len(local) <= 1:
        masked_local = "*"
    elif len(local) == 2:
        masked_local = f"{local[0]}*"
    else:
        masked_local = f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}"
    return f"{masked_local}@{domain}"
