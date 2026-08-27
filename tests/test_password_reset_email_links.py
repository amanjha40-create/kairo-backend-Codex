"""Focused tests for product-specific password reset link generation."""

from __future__ import annotations

import pytest

from app.auth.service import AuthService
from app.config import Settings
from app.core.constants import Role
from app.exceptions import ValidationAppError
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.organization.enums import OrganizationRole, OrganizationType


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
        "candidate_portal_base_url": "https://candidate-staging.example.com",
        "hr_portal_base_url": "https://hr-staging.example.com",
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
async def test_password_reset_url_targets_candidate_frontend_for_candidate_accounts() -> None:
    service = AuthService(session=object(), settings=_settings(), redis=object())  # type: ignore[arg-type]
    service._organizations.list_for_user = lambda user_id: _async_return([])  # type: ignore[method-assign]
    user = User(email="candidate.user@example.com", role=Role.USER.value)

    url = await service._password_reset_url_for_user(user, "reset-token")

    assert url == "https://candidate-staging.example.com/reset-password-confirm?token=reset-token"


@pytest.mark.asyncio
async def test_password_reset_url_targets_hr_frontend_for_hr_accounts() -> None:
    service = AuthService(session=object(), settings=_settings(), redis=object())  # type: ignore[arg-type]
    service._organizations.list_for_user = lambda user_id: _async_return([])  # type: ignore[method-assign]
    user = User(email="hr.user@example.com", role=Role.HR.value)

    url = await service._password_reset_url_for_user(user, "reset-token")

    assert url == "https://hr-staging.example.com/forgot-password?reset_token=reset-token"


@pytest.mark.asyncio
async def test_password_reset_url_uses_matching_institution_request_origin_without_membership() -> None:
    service = AuthService(session=object(), settings=_settings(), redis=object())  # type: ignore[arg-type]
    service._organizations.list_for_user = lambda user_id: _async_return([])  # type: ignore[method-assign]
    user = User(email="institution.user@example.com")

    url = await service._password_reset_url_for_user(
        user,
        "reset-token",
        requested_base_url="https://institution-staging.d3lrsnjzo6p8fc.amplifyapp.com/institution/login",
    )

    assert (
        url
        == "https://institution-staging.d3lrsnjzo6p8fc.amplifyapp.com"
        "/institution/login?reset_token=reset-token"
    )


@pytest.mark.asyncio
async def test_password_reset_url_requires_candidate_portal_for_candidate_accounts() -> None:
    service = AuthService(
        session=object(),
        settings=_settings(candidate_portal_base_url=None),
        redis=object(),
    )  # type: ignore[arg-type]
    service._organizations.list_for_user = lambda user_id: _async_return([])  # type: ignore[method-assign]
    user = User(email="candidate.user@example.com", role=Role.USER.value)

    with pytest.raises(ValidationAppError, match="CANDIDATE_PORTAL_BASE_URL"):
        await service._password_reset_url_for_user(user, "reset-token")


@pytest.mark.asyncio
async def test_password_reset_url_requires_hr_portal_for_hr_accounts() -> None:
    service = AuthService(
        session=object(),
        settings=_settings(hr_portal_base_url=None),
        redis=object(),
    )  # type: ignore[arg-type]
    service._organizations.list_for_user = lambda user_id: _async_return([])  # type: ignore[method-assign]
    user = User(email="hr.user@example.com", role=Role.HR.value)

    with pytest.raises(ValidationAppError, match="HR_PORTAL_BASE_URL"):
        await service._password_reset_url_for_user(user, "reset-token")


async def _async_return(value):  # noqa: ANN001
    return value
