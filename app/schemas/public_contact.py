"""Public website contact-form request/response contracts."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field, field_validator


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


class PublicContactRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True,
    )

    first_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            validation_alias=AliasChoices("first_name", "firstName"),
        ),
    ]
    last_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            validation_alias=AliasChoices("last_name", "lastName"),
        ),
    ]
    work_email: Annotated[
        EmailStr,
        Field(validation_alias=AliasChoices("work_email", "email", "workEmail")),
    ]
    company: Annotated[str, Field(min_length=1, max_length=160)]
    hires_per_month: Annotated[
        str,
        Field(
            min_length=1,
            max_length=40,
            validation_alias=AliasChoices("hires_per_month", "hires", "hiresPerMonth"),
        ),
    ]
    message: Annotated[str, Field(min_length=10, max_length=2000)]
    website: Annotated[str, Field(max_length=255)] = ""

    @field_validator("first_name", "last_name", "company", "hires_per_month", mode="before")
    @classmethod
    def normalize_single_line_fields(cls, value: object) -> object:
        if isinstance(value, str):
            return _collapse_whitespace(value)
        return value

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.replace("\r\n", "\n").replace("\r", "\n")
        lines = [_collapse_whitespace(line) for line in normalized.split("\n")]
        return "\n".join(line for line in lines if line).strip()

    @field_validator("website", mode="before")
    @classmethod
    def normalize_website(cls, value: object) -> str:
        if isinstance(value, str):
            return value.strip()
        return ""

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class PublicContactAcceptedResponse(BaseModel):
    status: str = "accepted"
    message: str = "Thanks — we’ve received your message."
