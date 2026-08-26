"""Focused tests for institution password reset link generation."""

from __future__ import annotations

import pytest

from app.auth.service import AuthService
from app.config import Settings
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.organization.enums import OrganizationRole, OrganizationType


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
        "institution_portal_base_url": "https://institution-staging.d3lrsnjzo6p8fc.amplifyapp.com",
        "email_backend": "console",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_password_reset_url_targets_institution_login_for_university_members() -> None:
    service = AuthService(session=object(), settings=_settings(), redis=object())  # type: ignore[arg-type]
    service._organizations.list_for_user = lambda user_id: _async_return(  # type: ignore[method-assign]
        [
            (
                Organization(
                    created_by_user_id=user_id,
                    name="Institution Acceptance University",
                    organization_type=OrganizationType.UNIVERSITY,
                ),
                OrganizationMember(
                    organization_id=user_id,
                    user_id=user_id,
                    role=OrganizationRole.OWNER,
                ),
            )
        ]
    )
    user = User(email="institution.user@example.com")

    url = await service._password_reset_url_for_user(user, "reset token+/=")

    assert (
        url
        == "https://institution-staging.d3lrsnjzo6p8fc.amplifyapp.com"
        "/institution/login?reset_token=reset%20token%2B%2F%3D"
    )


@pytest.mark.asyncio
async def test_password_reset_url_falls_back_when_user_has_no_university_membership() -> None:
    service = AuthService(session=object(), settings=_settings(), redis=object())  # type: ignore[arg-type]
    service._organizations.list_for_user = lambda user_id: _async_return(  # type: ignore[method-assign]
        [
            (
                Organization(
                    created_by_user_id=user_id,
                    name="Example Employer",
                    organization_type=OrganizationType.EMPLOYER,
                ),
                OrganizationMember(
                    organization_id=user_id,
                    user_id=user_id,
                    role=OrganizationRole.ADMIN,
                ),
            )
        ]
    )
    user = User(email="employer.user@example.com")

    url = await service._password_reset_url_for_user(user, "reset-token")

    assert url is None


async def _async_return(value):  # noqa: ANN001
    return value
