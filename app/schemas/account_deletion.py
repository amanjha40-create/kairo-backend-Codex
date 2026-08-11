"""Candidate account deletion request schema."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AccountDeletionRequest(BaseModel):
    """Explicit confirmation payload for irreversible candidate account deletion."""

    model_config = ConfigDict(str_strip_whitespace=True)

    confirm: str = Field(
        ...,
        description='Must be exactly "DELETE" to confirm irreversible erasure.',
    )
    current_password: str | None = Field(
        default=None,
        min_length=8,
        max_length=255,
        description="Required when the account has an email/password credential.",
    )
