"""Read-only reviewer and organization directories for Admin review."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission, get_roles_with_permission
from app.repositories.organization import OrganizationRepository
from app.repositories.user import UserRepository
from app.schemas.admin_directory import (
    AdminOrganizationSearchItem,
    AdminOrganizationSearchPage,
    AdminReviewerPage,
    AdminReviewerResponse,
)
from app.schemas.pagination import ListQueryParams
from app.organization.enums import OrganizationType


def normalize_organization_type(organization_type: OrganizationType | str) -> str:
    return organization_type.value if isinstance(organization_type, OrganizationType) else organization_type


class AdminDirectoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)
        self._organizations = OrganizationRepository(session)

    async def list_reviewers(self, params: ListQueryParams) -> AdminReviewerPage:
        users, total = await self._users.list_by_roles(
            get_roles_with_permission(Permission.REVIEW_VERIFICATION),
            search=params.search,
            offset=params.offset or 0,
            limit=params.limit or 20,
        )
        return AdminReviewerPage.create(
            items=[
                AdminReviewerResponse(user_id=user.id, full_name=user.full_name, email=user.email, role=user.role)
                for user in users
            ],
            total=total,
            params=params,
        )

    async def search_organizations(self, params: ListQueryParams) -> AdminOrganizationSearchPage:
        organizations, total = await self._organizations.search_all(
            search=params.search,
            offset=params.offset or 0,
            limit=params.limit or 20,
        )
        return AdminOrganizationSearchPage.create(
            items=[
                AdminOrganizationSearchItem(
                    public_id=item.public_id,
                    name=item.name,
                    organization_type=normalize_organization_type(item.organization_type),
                    verification_capabilities=list(item.verification_capabilities),
                    registry_record_public_id=item.registry_record.public_id if item.registry_record else None,
                    registry_resolution_status="resolved" if item.registry_record_id else "unresolved",
                )
                for item in organizations
            ],
            total=total,
            params=params,
        )
