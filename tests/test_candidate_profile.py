from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.profile import ProfileLanguageCreate, ProfileLinkCreate
from app.schemas.user import UserUpdate
from app.services.user_service import UserService


def test_profile_completion_is_deterministic_and_profile_scoped() -> None:
    user = SimpleNamespace(
        full_name="Aman Jha",
        avatar_key="users/avatar.webp",
        headline="Investor relations specialist",
        bio="Professional summary",
        email_verified_at=object(),
        phone_verified_at=object(),
        location_city="Mumbai",
        location_country="IN",
        location=None,
    )

    assert UserService._profile_completion(user, [object()], [object()]) == 100
    assert UserService._profile_completion(SimpleNamespace(**{key: None for key in vars(user)}), [], []) == 0


def test_profile_country_is_normalized_to_iso_uppercase() -> None:
    assert UserUpdate(location_country="in").location_country == "IN"


def test_profile_language_validates_supported_proficiency() -> None:
    assert ProfileLanguageCreate(language="Hindi", proficiency="fluent").language == "Hindi"
    with pytest.raises(ValidationError):
        ProfileLanguageCreate(language="Hindi", proficiency="expert")


def test_professional_link_normalizes_safe_urls_and_rejects_unsafe_urls() -> None:
    assert UserService._normalize_url("linkedin.com/in/example") == "https://linkedin.com/in/example"
    assert UserService._normalize_url("https://example.com/profile") == "https://example.com/profile"
    with pytest.raises(Exception, match="valid professional link"):
        UserService._normalize_url("javascript:alert(1)")
    with pytest.raises(Exception, match="valid professional link"):
        UserService._normalize_url("https://user@example.com")


def test_professional_link_schema_requires_a_supported_type_and_url() -> None:
    payload = ProfileLinkCreate(link_type="linkedin", url="linkedin.com/in/example")
    assert payload.link_type == "linkedin"
    with pytest.raises(ValidationError):
        ProfileLinkCreate(link_type="resume", url="example.com")
