"""Allowlisted data contract for the owner Trust Passport PDF export."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class PassportPDFProfile(BaseModel):
    display_name: str
    headline: str | None = None
    location: str | None = None
    professional_summary: str | None = None
    current_role: str | None = None
    industry: str | None = None
    years_of_experience: int | None = Field(default=None, ge=0)


class PassportPDFTrustScore(BaseModel):
    overall: int = Field(ge=0, le=100)
    status: str
    status_label: str


class PassportPDFEmployment(BaseModel):
    employer_name: str | None
    job_title: str
    start_date: date | None
    end_date: date | None
    verification_status: str
    verification_label: str


class PassportPDFEducation(BaseModel):
    institution_name: str
    degree: str
    field_of_study: str | None
    start_date: date | None
    end_date: date | None
    is_currently_studying: bool
    verification_status: str
    verification_label: str


class PassportPDFCertification(BaseModel):
    title: str
    issuing_organization: str | None
    issued_date: date | None
    expiry_date: date | None
    does_not_expire: bool
    verification_status: str
    verification_label: str


class PassportPDFProject(BaseModel):
    title: str
    role: str | None
    organization_name: str | None
    description: str | None
    start_date: date | None
    end_date: date | None
    is_ongoing: bool
    verification_status: str
    verification_label: str


class PassportPDFSkill(BaseModel):
    name: str
    verification_status: str
    verification_label: str


class PassportPDFProjection(BaseModel):
    """Professional fields intentionally permitted in an owner PDF export.

    Authentication data, private contact details, database identifiers,
    documents, evidence, storage metadata, and workflow internals have no
    representation in this schema and therefore cannot reach the renderer.
    """

    profile: PassportPDFProfile
    trust_score: PassportPDFTrustScore | None = None
    employments: list[PassportPDFEmployment] = Field(default_factory=list)
    educations: list[PassportPDFEducation] = Field(default_factory=list)
    certifications: list[PassportPDFCertification] = Field(default_factory=list)
    projects: list[PassportPDFProject] = Field(default_factory=list)
    skills: list[PassportPDFSkill] = Field(default_factory=list)
    generated_at: datetime
