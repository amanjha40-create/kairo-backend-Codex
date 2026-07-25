"""Focused Version 1 Trust Score engine tests."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models import Education, Employment, TrustScoreSnapshot, User, UserDocument
from app.services.trust_score_service import TrustScoreService


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value


class _Session:
    def __init__(self, user, documents=None, employments=None, educations=None):
        self.user = user
        self.documents = documents or []
        self.employments = employments or []
        self.educations = educations or []
        self.added = []
        self.snapshot = None

    async def execute(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        values = {
            User: self.user,
            UserDocument: self.documents,
            Employment: self.employments,
            Education: self.educations,
            TrustScoreSnapshot: self.snapshot,
        }
        return _Result(values[entity])

    def add(self, value):
        self.added.append(value)
        if isinstance(value, TrustScoreSnapshot):
            self.snapshot = value

    async def commit(self):
        return None


def _settings():
    return SimpleNamespace(
        trust_score_require_consent=True,
        trust_score_version="v1",
        trust_score_identity_weight=0.25,
        trust_score_employment_weight=0.45,
        trust_score_education_weight=0.30,
    )


def _user(**overrides):
    values = {
        "id": uuid4(),
        "deleted_at": None,
        "email_verified_at": datetime.now(UTC),
        "phone_verified_at": datetime.now(UTC),
        "trust_score_consent_at": None,
        "trust_score_consent_version": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_consent_gate_returns_no_numeric_score_and_persists_reason():
    user = _user()
    session = _Session(user)
    response = await TrustScoreService(session, _settings()).calculate_trust_score(user.id)

    assert response.status == "consent_required"
    assert response.overall is None
    assert response.score_version == "v1"
    assert response.manual_review_reason is not None
    assert session.added[0].status == "consent_required"


@pytest.mark.asyncio
async def test_v1_scores_only_three_domains_and_explains_verified_inputs():
    user = _user(trust_score_consent_at=datetime.now(UTC), trust_score_consent_version="v1-consent")
    session = _Session(
        user,
        documents=[SimpleNamespace(verification_status="approved", deleted_at=None)],
        employments=[SimpleNamespace(verification_status="approved", deleted_at=None, employer_legal_name="Example Corp")],
        educations=[SimpleNamespace(verification_status="verified", deleted_at=None, institution_name="Example University")],
    )
    response = await TrustScoreService(session, _settings()).calculate_trust_score(user.id)

    assert response.status == "calculated"
    assert response.overall == 82
    assert response.breakdown is not None
    assert response.breakdown.identity == 100
    assert response.breakdown.employment == 80
    assert response.breakdown.education == 70
    assert response.breakdown.documents is None
    assert {item.code for item in response.positive_contributors} >= {
        "identity_authoritative",
        "phone_verified",
        "email_verified",
        "employment_authoritative",
        "education_authoritative",
    }
    assert session.added[0].score_version == "v1"


@pytest.mark.asyncio
async def test_repeated_unchanged_calculation_reuses_latest_snapshot():
    user = _user(trust_score_consent_at=datetime.now(UTC), trust_score_consent_version="v1-consent")
    session = _Session(user)
    service = TrustScoreService(session, _settings())

    first = await service.calculate_trust_score(user.id)
    session.snapshot.calculated_at = first.last_calculated_at
    second = await service.calculate_trust_score(user.id)

    assert len(session.added) == 1
    assert second.last_calculated_at == first.last_calculated_at


@pytest.mark.asyncio
async def test_withdrawing_consent_hides_future_score_but_keeps_snapshot():
    user = _user(trust_score_consent_at=datetime.now(UTC), trust_score_consent_version="v1-consent")
    session = _Session(user)
    service = TrustScoreService(session, _settings())
    await service.calculate_trust_score(user.id)
    await service.withdraw_consent(user.id)

    response = await service.calculate_trust_score(user.id)
    assert response.status == "consent_required"
    assert response.overall is None
    assert session.snapshot is not None


def test_domain_score_is_floored_and_capped():
    result = TrustScoreService._domain(140, 100, 0.45, [], [])
    assert result.score == 100
    result = TrustScoreService._domain(-10, 100, 0.45, [], [])
    assert result.score == 0
