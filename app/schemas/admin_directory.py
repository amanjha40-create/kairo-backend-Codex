"""Read-only directory DTOs used by the Admin review console."""

from uuid import UUID

from pydantic import BaseModel

from app.schemas.pagination import Page


class AdminReviewerResponse(BaseModel):
    user_id: UUID
    full_name: str | None
    email: str
    role: str


class AdminOrganizationSearchItem(BaseModel):
    public_id: UUID
    name: str
    organization_type: str
    verification_capabilities: list[str]
    registry_record_public_id: UUID | None
    registry_resolution_status: str


class AdminReviewerPage(Page[AdminReviewerResponse]):
    pass


class AdminOrganizationSearchPage(Page[AdminOrganizationSearchItem]):
    pass
