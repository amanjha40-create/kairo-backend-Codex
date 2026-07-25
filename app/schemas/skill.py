"""Candidate skill API schemas."""

from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class SkillCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Skill name is required")
        return value


class SkillResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    verification_status: str

    model_config = {"from_attributes": True}
