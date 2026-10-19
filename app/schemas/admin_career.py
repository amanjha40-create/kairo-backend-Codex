"""Strict Admin adapters for existing Candidate domain fields, not new models."""

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.gig_platform import GigPlatformCreateRequest, GigPlatformUpdateRequest
from app.schemas.portfolio import PortfolioItemCreateRequest, PortfolioItemUpdateRequest
from app.schemas.project import ProjectCreateRequest, ProjectUpdateRequest
from app.schemas.skill import SkillCreateRequest

ExtendedCareerType = Literal["portfolio", "project", "skill", "gig_platform"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminPortfolioCreate(PortfolioItemCreateRequest, _Strict):
    pass


class AdminPortfolioUpdate(PortfolioItemUpdateRequest, _Strict):
    pass


class AdminProjectCreate(ProjectCreateRequest, _Strict):
    pass


class AdminProjectUpdate(ProjectUpdateRequest, _Strict):
    pass


class AdminSkillWrite(SkillCreateRequest, _Strict):
    pass


class _GigConstraints(_Strict):
    @model_validator(mode="after")
    def canonical_storage_bounds(self):
        for field in ("platform_name", "partner_role", "partner_id"):
            value = getattr(self, field)
            if value is not None and (not value.strip() or len(value) > 256):
                raise ValueError(f"{field} must contain 1 to 256 characters")
        if self.started_at and self.ended_at and self.ended_at < self.started_at:
            raise ValueError("ended_at must be on or after started_at")
        if self.rating is not None and (
            not self.rating.is_finite()
            or abs(self.rating) >= 10
            or self.rating != self.rating.quantize(Decimal("0.01"))
        ):
            raise ValueError("rating must fit the canonical two-decimal storage contract")
        return self


class AdminGigCreate(GigPlatformCreateRequest, _GigConstraints):
    pass


class AdminGigUpdate(GigPlatformUpdateRequest, _GigConstraints):
    pass


CREATE_SCHEMAS = {
    "portfolio": AdminPortfolioCreate,
    "project": AdminProjectCreate,
    "skill": AdminSkillWrite,
    "gig_platform": AdminGigCreate,
}
UPDATE_SCHEMAS = {
    "portfolio": AdminPortfolioUpdate,
    "project": AdminProjectUpdate,
    "skill": AdminSkillWrite,
    "gig_platform": AdminGigUpdate,
}


def payload_contract(schema: dict[str, Any], *, update: bool = False) -> None:
    """Expose the claim-type-dependent payload in OpenAPI 3.1."""
    schema["allOf"] = [
        {
            "if": {"properties": {"claim_type": {"const": kind}}},
            "then": {"properties": {"payload": model.model_json_schema()}},
        }
        for kind, model in (UPDATE_SCHEMAS if update else CREATE_SCHEMAS).items()
    ]


def validate_payload(kind: str, payload: dict[str, Any], *, update: bool) -> dict[str, Any]:
    if kind not in CREATE_SCHEMAS:
        return payload
    if update and not payload:
        raise ValueError("At least one Career field is required")
    model = (UPDATE_SCHEMAS if update else CREATE_SCHEMAS)[kind].model_validate(payload)
    changes = model.model_dump(exclude_unset=update)
    for field in ("title", "name", "is_ongoing", "is_active"):
        if field in changes and changes[field] is None:
            raise ValueError(f"{field} cannot be null")
    if kind == "portfolio" and changes.get("tags"):
        if any("," in tag for tag in changes["tags"]) or len(",".join(changes["tags"])) > 1024:
            raise ValueError("tags must fit the canonical comma-separated storage contract")
    return changes
