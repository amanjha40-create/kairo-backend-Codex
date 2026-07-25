"""Candidate-managed profile subresources."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

LanguageProficiency = Literal["basic", "conversational", "professional", "fluent", "native"]
ProfileLinkType = Literal["linkedin", "github", "website", "portfolio", "other"]


class ProfileLanguageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    language: str
    proficiency: LanguageProficiency | None


class ProfileLanguageCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    language: str = Field(min_length=1, max_length=80)
    proficiency: LanguageProficiency | None = None


class ProfileLanguageUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    language: str | None = Field(default=None, min_length=1, max_length=80)
    proficiency: LanguageProficiency | None = None


class ProfileLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    link_type: ProfileLinkType
    label: str | None
    url: str


class ProfileLinkCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    link_type: ProfileLinkType
    label: str | None = Field(default=None, max_length=120)
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return value.strip()


class ProfileLinkUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    link_type: ProfileLinkType | None = None
    label: str | None = Field(default=None, max_length=120)
    url: str | None = Field(default=None, min_length=1, max_length=2048)


class ProfileLocationUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    city: str | None = Field(default=None, max_length=128)
    region: str | None = Field(default=None, max_length=128)
    country: str | None = Field(default=None, min_length=2, max_length=2)

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        return value.upper() if value else None
