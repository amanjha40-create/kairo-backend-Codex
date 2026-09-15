"""Versioned disclosure policy. Absent marker means legacy, never false-like V2."""

from dataclasses import dataclass

from pydantic import ValidationError

from app.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.schemas.passport_share import (
    PassportSharePermissions,
    PassportShareV2Permissions,
    PassportShareUpdateRequest,
    ResolvedSharingMode,
    validate_v2_permissions,
)


@dataclass(frozen=True)
class SharingPolicy:
    version: int
    mode: ResolvedSharingMode
    permissions: PassportSharePermissions


def resolve_policy(stored: dict) -> SharingPolicy:
    try:
        if not isinstance(stored, dict):
            raise ValueError("Invalid policy")
        values = dict(stored)
        if "verified_only" not in values:
            return SharingPolicy(
                1, "legacy_mixed", PassportSharePermissions.model_validate(values, strict=True)
            )
        marker = values.pop("verified_only")
        if type(marker) is not bool or set(values) != set(PassportShareV2Permissions.model_fields):
            raise ValueError("Incomplete marked policy")
        mode = "verified_only" if marker else "verified_and_candidate_provided"
        permissions = PassportShareV2Permissions.model_validate(values)
        validate_v2_permissions(mode, permissions)
        return SharingPolicy(2, mode, permissions)
    except (ValidationError, ValueError, TypeError) as exc:
        raise NotFoundError("Trust Passport not found") from exc


def stored_v2(mode: str, permissions: PassportSharePermissions) -> dict[str, bool]:
    return {**permissions.model_dump(), "verified_only": mode == "verified_only"}


def narrow_policy(stored: dict, patch: PassportShareUpdateRequest) -> dict[str, bool]:
    current = resolve_policy(stored)
    mode = patch.sharing_mode or current.mode
    if mode == "verified_and_candidate_provided" and current.mode == "verified_only":
        raise ConflictError("Broader access requires a new share link")
    previous = current.permissions.model_dump()
    changes = patch.permissions.model_dump(exclude_unset=True) if patch.permissions else {}
    if any(value and not previous[key] for key, value in changes.items()):
        raise ConflictError("Broader access requires a new share link")
    merged = {**previous, **changes}
    if mode == "legacy_mixed":
        return merged
    try:
        permissions = PassportShareV2Permissions.model_validate(merged)
        validate_v2_permissions(mode, permissions)
    except ValueError as exc:
        raise ValidationAppError(str(exc)) from exc
    return stored_v2(mode, permissions)
