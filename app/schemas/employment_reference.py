"""Explicit allowlists: candidate summaries never serialize private reference content."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ManagerNomination(StrictBody):
    full_name: str = Field(min_length=1, max_length=255)
    designation: str = Field(min_length=1, max_length=255)
    work_email: EmailStr | None = None
    phone: str | None = Field(default=None, pattern=r"^\+[1-9][0-9]{7,14}$")

    @field_validator("work_email")
    @classmethod
    def normalize_email(cls, value):
        return str(value).lower() if value else None

    @model_validator(mode="after")
    def contact_required(self):
        if not (self.work_email or self.phone):
            raise ValueError("Provide a work email or international phone number")
        return self


class HRReference(StrictBody):
    status: Literal["completed", "cannot_confirm"] = "completed"
    eligible_for_rehire: Literal["yes", "no", "prefer_not_to_answer"] = "prefer_not_to_answer"
    comments: str | None = Field(default=None, max_length=2000)


class ManagerValidation(StrictBody):
    nomination_id: UUID
    relationship_decision: Literal[
        "confirmed_reporting_manager",
        "worked_here_but_not_reporting_manager",
        "not_recognized",
        "details_incorrect",
        "cannot_confirm",
        "left_organization",
    ]
    contact_provenance: Literal["hr_confirmed", "hr_corrected", "hr_supplied", "hr_cannot_confirm"]
    confirmed_contact: ManagerNomination | None = None

    @model_validator(mode="after")
    def corrected_contact_required(self):
        if (
            self.contact_provenance in {"hr_corrected", "hr_supplied"}
            and self.confirmed_contact is None
        ):
            raise ValueError("HR-corrected/supplied contact details are required")
        if (
            self.contact_provenance not in {"hr_corrected", "hr_supplied"}
            and self.confirmed_contact is not None
        ):
            raise ValueError("Contact details require corrected or supplied provenance")
        return self


class ReferenceSummary(BaseModel):
    status: str
    completed_at: datetime | None = None


class ManagerSummary(ReferenceSummary):
    identity_withheld: bool = False
    nomination_id: UUID | None = None
    full_name: str | None = None
    designation: str | None = None
    relationship: Literal["reporting_manager", "former_reporting_manager"] = "reporting_manager"
    relationship_confirmed_by_hr: bool = False
    nomination_locked: bool = False
    nominated_at: datetime | None = None
    validated_at: datetime | None = None
    invitation_sent_at: datetime | None = None
    invitation_expires_at: datetime | None = None
    invitation_blocked_reason: (
        Literal["awaiting_hr_validation", "employment_not_verified", "email_required"] | None
    ) = None


class CandidateReferences(BaseModel):
    employment_id: UUID
    completed_count: int
    total_count: Literal[2] = 2
    hr_reference: ReferenceSummary
    reporting_manager: ManagerSummary


class SendReference(StrictBody):
    nomination_id: UUID
    idempotency_key: UUID


class ManagerResponse(StrictBody):
    directly_managed: Literal["yes", "no", "cannot_confirm"]
    working_relationship: Literal["direct_manager", "former_direct_manager", "other"]
    period_start: date | None = None
    period_end: date | None = None
    overall_performance: int | None = Field(default=None, ge=1, le=5, strict=True)
    reliability_ownership: int | None = Field(default=None, ge=1, le=5, strict=True)
    communication: int | None = Field(default=None, ge=1, le=5, strict=True)
    teamwork_collaboration: int | None = Field(default=None, ge=1, le=5, strict=True)
    work_together_again: Literal["yes", "no", "prefer_not_to_answer"] = "prefer_not_to_answer"
    key_strength: str | None = Field(default=None, max_length=1000)
    additional_comments: str | None = Field(default=None, max_length=2000)
    attested: bool = False

    @model_validator(mode="after")
    def validate_response(self):
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("Working period end must not precede start")
        if self.directly_managed == "yes":
            if not self.attested or self.working_relationship == "other":
                raise ValueError("Direct management and self-confirmation are required")
            if any(
                getattr(self, key) is None
                for key in (
                    "overall_performance",
                    "reliability_ownership",
                    "communication",
                    "teamwork_collaboration",
                )
            ):
                raise ValueError("All four 1-5 ratings are required")
        return self
