"""Candidate project API schemas."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, model_validator


class ProjectCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    role: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    start_date: date | None = None
    end_date: date | None = None
    is_ongoing: bool = False
    project_url: HttpUrl | None = None
    repository_url: HttpUrl | None = None
    organization_name: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.is_ongoing and self.end_date is not None:
            raise ValueError("end_date must be null when is_ongoing is true")
        return self


class ProjectUpdateRequest(ProjectCreateRequest):
    title: str | None = Field(default=None, min_length=1, max_length=255)


class ProjectResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    role: str | None
    description: str | None
    start_date: date | None
    end_date: date | None
    is_ongoing: bool
    project_url: str | None
    repository_url: str | None
    organization_name: str | None
    verification_status: str

    model_config = {"from_attributes": True}
