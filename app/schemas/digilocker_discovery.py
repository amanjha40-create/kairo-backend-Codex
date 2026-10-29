"""Safe Candidate-facing contracts for DigiLocker discovery and explicit import."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.schemas.permanent_address import PermanentAddressInput

MatchState = Literal["CLEAR_MATCH", "NO_MATCH", "AMBIGUOUS", "ALREADY_ADDED"]
ReviewState = Literal["ready", "already_added", "needs_review", "parse_failed"]


class AvailableRecord(BaseModel):
    candidate_id: str = Field(min_length=16, max_length=128)
    doctype: str
    record_type: str
    display_type: str
    description: str | None = None
    issuer_name: str | None = None
    source: Literal["digilocker"] = "digilocker"
    xml_available: bool
    pdf_available: bool
    parsed_data_available: bool
    import_status: Literal["available", "already_added", "needs_review"]
    possible_existing_record_match: MatchState
    review_state: ReviewState


class EducationEvidence(AvailableRecord):
    evidence_type: str


class EducationGroup(BaseModel):
    candidate_id: str = Field(min_length=16, max_length=128)
    record_type: str
    display_type: str
    source: Literal["digilocker"] = "digilocker"
    possible_existing_record_match: MatchState
    import_status: Literal["available", "already_added", "needs_review"]
    review_state: ReviewState
    evidence: list[EducationEvidence]


class AddressCandidate(BaseModel):
    candidate_id: str = Field(min_length=16, max_length=128)
    doctype: Literal["DRVLC"]
    display_type: Literal["Driving Licence address"]
    source: Literal["digilocker_driving_licence"]
    review_state: Literal["ready"]
    address: PermanentAddressInput


class DiscoveryCounts(BaseModel):
    total_issued: int
    supported: int
    unsupported: int
    identity: int
    education: int
    address_candidates: int
    xml_available: int
    pdf_only: int
    parse_failures: int
    malformed: int


class AvailableRecordsResponse(BaseModel):
    identity: list[AvailableRecord]
    education: list[EducationGroup]
    address_candidates: list[AddressCandidate]
    counts: DiscoveryCounts
    discovered_at: datetime


class ImportRecordsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    candidate_ids: list[str] = Field(min_length=1, max_length=25)
    education_targets: dict[str, UUID] = Field(default_factory=dict, max_length=25)
    consent: StrictBool = False
    consent_version: Literal["v1"] = "v1"

    @model_validator(mode="after")
    def targets_are_selected(self):
        if set(self.education_targets) - set(self.candidate_ids):
            raise ValueError("Education targets must refer to selected discovery groups")
        return self


class ImportOutcome(BaseModel):
    candidate_id: str
    domain: Literal["identity", "education", "address"]
    status: Literal["imported", "linked", "already_added", "needs_review", "use_address_save"]
    record_id: UUID | None = None
    verification_id: UUID | None = None
    evidence_count: int = 0
    review_state: ReviewState


class ImportRecordsResponse(BaseModel):
    outcomes: list[ImportOutcome]
    completed_at: datetime
