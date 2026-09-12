from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.exceptions import ValidationAppError
from app.resumes.schemas import ParsedResumeResult
from app.schemas.user import UserUpdate
from app.services.resume_review_service import ResumeReviewService
from app.services.user_service import UserService


def test_resume_profile_claim_excludes_contact_identity_and_remains_a_suggestion() -> None:
    parsed = ParsedResumeResult.model_validate(
        {
            "candidate_profile": {
                "full_name": "Resume Test Person",
                "email": "resume-test@example.invalid",
                "phone": "+10000000000",
                "professional_headline": "Synthetic resume headline",
                "location": {"city": "Synthetic City", "country": "IN"},
            },
            "employments": [
                {
                    "company_name": "Synthetic Company",
                    "role_title": "Engineer",
                }
            ],
        }
    )

    claims = ResumeReviewService._claims(parsed)
    profile = next(payload for claim_type, payload in claims if claim_type == "profile")

    assert profile["full_name"] == "Resume Test Person"
    assert profile["professional_headline"] == "Synthetic resume headline"
    assert "email" not in profile
    assert "phone" not in profile
    assert any(claim_type == "employment" for claim_type, _ in claims)


@pytest.mark.asyncio
async def test_resume_profile_cannot_create_or_overwrite_account_identity() -> None:
    account = SimpleNamespace(
        full_name="Authenticated Account",
        headline="Account headline",
        bio="Account introduction",
        location="Account City",
    )
    service = ResumeReviewService(SimpleNamespace())
    foreign_profile = {
        "claim_type": "profile",
        "full_name": "Resume Test Person",
        "professional_headline": "Foreign headline",
        "summary": "Foreign introduction",
        "location": {"city": "Foreign City"},
    }

    with pytest.raises(ValidationAppError) as create_error:
        await service._create_record(uuid4(), "profile", foreign_profile)
    with pytest.raises(ValidationAppError) as update_error:
        service._apply_update(account, "profile", foreign_profile)

    assert create_error.value.code == "resume_profile_suggestion_only"
    assert update_error.value.code == "resume_profile_suggestion_only"
    assert account.full_name == "Authenticated Account"
    assert account.headline == "Account headline"
    assert account.bio == "Account introduction"
    assert account.location == "Account City"


@pytest.mark.asyncio
async def test_legacy_selected_profile_is_excluded_while_career_import_plan_remains_ready() -> None:
    profile_item = SimpleNamespace(
        id=uuid4(),
        selected=True,
        claim_type="profile",
        import_action="create_new",
        edited_payload={"claim_type": "profile", "full_name": "Resume Test Person"},
        target_record_id=None,
        duplicate_status="no_match",
        conflict_warnings=[],
    )
    employment_item = SimpleNamespace(
        id=uuid4(),
        selected=True,
        claim_type="employment",
        import_action="create_new",
        edited_payload={
            "claim_type": "employment",
            "company_name": "Synthetic Company",
            "role_title": "Engineer",
            "start_date": "2024-01-01",
            "is_current": True,
        },
        target_record_id=None,
        duplicate_status="no_match",
        conflict_warnings=[],
    )

    class FakeScalars:
        def all(self) -> list[SimpleNamespace]:
            return [profile_item, employment_item]

    class FakeSession:
        async def scalars(self, _statement: object) -> FakeScalars:
            return FakeScalars()

    review = SimpleNamespace(id=uuid4(), user_id=uuid4(), version=1)
    plan = await ResumeReviewService(FakeSession())._build_plan(review)

    assert plan.ready is True
    assert [item.claim_type for item in plan.items] == ["employment"]


@pytest.mark.asyncio
async def test_import_execution_rejects_profile_claim_defensively() -> None:
    item = SimpleNamespace(claim_type="profile")
    service = ResumeReviewService(SimpleNamespace())

    with pytest.raises(ValidationAppError) as error:
        await service._import_item(
            uuid4(),
            SimpleNamespace(),
            SimpleNamespace(),
            item,
            datetime.now(UTC),
        )

    assert error.value.code == "resume_profile_suggestion_only"


@pytest.mark.asyncio
async def test_profile_read_and_explicit_edit_use_only_the_authenticated_user_id() -> None:
    account_a_id = uuid4()
    account_b_id = uuid4()

    def profile(user_id: object, full_name: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=user_id,
            full_name=full_name,
            email_verified_at=None,
            phone_verified_at=None,
            phone=None,
            headline=None,
            current_role=None,
            industry=None,
            years_of_experience=None,
            employment_onboarding_completed_at=None,
        )

    accounts = {
        account_a_id: profile(account_a_id, "Account A"),
        account_b_id: profile(account_b_id, "Account B"),
    }

    class FakeUsers:
        def __init__(self) -> None:
            self.requested_ids: list[object] = []

        async def get_by_id(self, user_id: object) -> SimpleNamespace | None:
            self.requested_ids.append(user_id)
            return accounts.get(user_id)

    class FakeSession:
        async def commit(self) -> None:
            return None

        async def refresh(self, _value: object) -> None:
            return None

    repository = FakeUsers()
    service = UserService(FakeSession(), SimpleNamespace())
    service._users = repository

    async def public_identity(user: SimpleNamespace) -> SimpleNamespace:
        return user

    service._to_public = public_identity

    profile_a = await service.get_public_profile(account_a_id)
    updated_b = await service.update_profile(
        account_b_id,
        UserUpdate(full_name="Account B Explicitly Updated"),
    )

    assert profile_a.id == account_a_id
    assert profile_a.full_name == "Account A"
    assert updated_b.id == account_b_id
    assert updated_b.full_name == "Account B Explicitly Updated"
    assert repository.requested_ids == [account_a_id, account_b_id]
