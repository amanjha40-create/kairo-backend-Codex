"""Owner-only address input and safe outcome DTOs; never serialize target points."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)


class PermanentAddressInput(StrictInput):
    address_line_1: str = Field(min_length=3, max_length=160)
    address_line_2: str | None = Field(default=None, max_length=160)
    locality: str | None = Field(default=None, max_length=100)
    city: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    postal_code: str = Field(pattern=r"^[1-9][0-9]{5}$")
    country: Literal["IN"] = "IN"

    @field_validator("address_line_1", "address_line_2", "locality", "city", "state")
    @classmethod
    def printable(cls, value):
        if value is not None and any(ord(c) < 32 for c in value):
            raise ValueError("Address contains unsupported control characters")
        return value or None


class AddressEvidenceInput(StrictInput):
    address_version_id: UUID
    document_id: UUID


class LocationStartInput(StrictInput):
    address_version_id: UUID


class LocationSample(StrictInput):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False, strict=True)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False, strict=True)
    accuracy_m: float = Field(gt=0, le=10000, allow_inf_nan=False, strict=True)
    timestamp: datetime
    mock_location: bool = Field(default=False, strict=True)

    @field_validator("timestamp")
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None:
            raise ValueError("Sample timestamp must include a timezone")
        return value


class LocationCompleteInput(StrictInput):
    challenge: str = Field(min_length=32, max_length=128, repr=False)
    samples: list[LocationSample] = Field(min_length=5, max_length=10, repr=False)


class LocationCancelInput(StrictInput):
    challenge: str = Field(min_length=32, max_length=128, repr=False)


class AddressReviewInput(StrictInput):
    document_id: UUID
    outcome: Literal["MATCH", "MISMATCH", "NEEDS_REVIEW"]
    observed_address: PermanentAddressInput | None = None


class LocationChallenge(BaseModel):
    session_id: UUID
    challenge: str = Field(repr=False)
    expires_at: datetime
    minimum_duration_seconds: int = 30
    maximum_duration_seconds: int = 60
    minimum_samples: int = 5
    maximum_samples: int = 10


class PermanentAddressState(BaseModel):
    enabled: bool
    status: str
    address_version_id: UUID | None = None
    address_version: int | None = None
    claimed_address: PermanentAddressInput | None = None
    document_status: str = "REQUIRED"
    evidence_document_id: UUID | None = None
    geocode_status: str = "NOT_STARTED"
    geocode_quality: str | None = None
    target_confirmation_required: bool = False
    target_source: Literal["provider_geocode", "onsite_confirmation"] | None = None
    successful_gps_checks: int = 0
    required_gps_checks: int = 3
    today_complete: bool = False
    can_start_location: bool = False
    last_location_result: str | None = None
    expires_at: datetime | None = None
    completed_at: datetime | None = None
