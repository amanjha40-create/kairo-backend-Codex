"""Release-hold truth and privacy policies, without provider traffic."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.exceptions import ValidationAppError
from app.schemas.hr_v2 import (
    VerificationReportCheckStatus as Status,
)
from app.schemas.hr_v2 import (
    VerificationReportCheckSummary,
)
from app.schemas.trust_invitation import TrustInvitationCreateRequest
from app.services.hr_v2_service import HRV2Service
from app.services.trust_invitation_service import TrustInvitationService
from app.verification_requests.enums import VerificationRequestStatus, VerificationRequestType


@pytest.mark.parametrize(
    "check,status",
    [
        ("references", Status.PENDING),
        ("references", Status.AWAITING_RESPONSE),
        ("address", Status.PENDING),
        ("court_record_search", Status.PENDING),
        ("identity", Status.DISCREPANCY),
        ("employment", Status.REJECTED),
        ("education", Status.UNABLE_TO_VERIFY),
    ],
)
def test_unresolved_items_use_one_finality_policy(check, status):
    service = HRV2Service.__new__(HRV2Service)
    summaries = [
        VerificationReportCheckSummary(check=check, status=status, display_text="Unresolved")
    ]
    finality, items, review = service._report_finality([], summaries)
    assert finality == "INTERIM"
    assert review is True and len(items) == 1 and items[0].check == check


def test_not_ordered_does_not_block_closed_checks():
    service = HRV2Service.__new__(HRV2Service)
    summaries = [
        VerificationReportCheckSummary(check=key, status=status, display_text="Safe")
        for key, status in [
            ("identity", Status.CONFIRMED),
            ("address", Status.NOT_ORDERED),
            ("references", Status.NOT_ORDERED),
        ]
    ]
    assert service._report_finality([], summaries) == ("FINAL", [], False)
    assert service._report_finality([], []) == ("INTERIM", [], False)


@pytest.mark.parametrize(
    "status",
    [
        VerificationRequestStatus.AWAITING_INFORMATION,
        VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS,
        VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW,
        VerificationRequestStatus.REJECTED,
        VerificationRequestStatus.EXPIRED,
    ],
)
def test_generic_work_and_clarifications_block_final_even_outside_summary_types(status):
    request = SimpleNamespace(
        public_id=uuid4(), request_type=VerificationRequestType.CUSTOM, status=status
    )
    finality, items, review = HRV2Service.__new__(HRV2Service)._report_finality([request], [])
    assert finality == "INTERIM" and items and review


def test_pending_second_request_not_hidden_by_confirmed_first():
    now = datetime.now(UTC)
    requests = [
        SimpleNamespace(request_type=VerificationRequestType.IDENTITY, updated_at=now, status=value)
        for value in (VerificationRequestStatus.VERIFIED, VerificationRequestStatus.IN_PROGRESS)
    ]
    service = HRV2Service.__new__(HRV2Service)
    summary = service._check_summaries(requests, [], [], [], [], [])
    assert next(item.status for item in summary if item.check == "identity") == Status.PENDING


def test_ordered_without_results_is_pending_and_explicit_selection_does_not_inherit_address():
    service = HRV2Service.__new__(HRV2Service)
    invitation = SimpleNamespace(
        requested_verification_types=["professional_reference"],
        verification_preferences_snapshot={
            "checks": {"address": True},
            "requested_types_source": "explicit",
        },
    )
    ordered = service._ordered_report_checks([], [invitation])
    assert ordered == {"references"}
    summaries = service._check_summaries([], [], [], [], [], [], ordered=ordered)
    assert next(row.status for row in summaries if row.check == "references") == Status.PENDING
    assert next(row.status for row in summaries if row.check == "address") == Status.NOT_ORDERED
    invitation.verification_preferences_snapshot.pop("requested_types_source")
    assert "address" in service._ordered_report_checks([], [invitation])


@pytest.mark.asyncio
@pytest.mark.parametrize("canonical", [True, False])
async def test_current_and_legacy_reference_fields(canonical):
    service = HRV2Service.__new__(HRV2Service)
    row = SimpleNamespace(
        id=uuid4(),
        nomination={
            "full_name" if canonical else "name": "Synthetic Manager",
            "designation" if canonical else "title": "Lead",
        },
        answers={
            "key_strength" if canonical else "strengths": "Internal strength",
            "additional_comments" if canonical else "comments": "Internal comment",
            "eligible_for_rehire" if canonical else "rehire_response": "no",
        },
        nominated_at=None,
        completed_at=None,
        status="completed",
    )
    service._session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [row])),
                SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [])),
            ]
        )
    )
    (item,) = await service._reference_items([SimpleNamespace(employment_id=uuid4())])
    assert (item.name, item.title_or_relationship, item.strengths, item.comments) == (
        "Synthetic Manager",
        "Lead",
        "Internal strength",
        "Internal comment",
    )
    assert item.rehire_response == "no"


@pytest.mark.parametrize(
    "kind", [VerificationRequestType.REFERENCE, VerificationRequestType.CERTIFICATION]
)
@pytest.mark.parametrize(
    "status",
    [VerificationRequestStatus.CANCELLED, VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE],
)
def test_cancelled_request_does_not_satisfy_active_invitation_order(kind, status):
    service = HRV2Service.__new__(HRV2Service)
    request = SimpleNamespace(
        public_id=uuid4(),
        request_type=kind,
        updated_at=datetime.now(UTC),
        status=status,
    )
    check = "references" if kind == VerificationRequestType.REFERENCE else "certification"
    invitation = SimpleNamespace(
        requested_verification_types=[check], verification_preferences_snapshot={}
    )
    ordered = service._ordered_report_checks([request], [invitation])
    summaries = service._check_summaries([request], [], [], [], [], [], ordered=ordered)
    state, items, review = service._report_finality([request], summaries, ordered)
    assert state == "INTERIM" and review and any(row.check == check for row in items)
    without_order = service._ordered_report_checks([request], [])
    assert not without_order


@pytest.mark.asyncio
@pytest.mark.parametrize("require_pair", [True, False])
@pytest.mark.parametrize(
    "completed_kinds",
    [
        [],
        ["hr_reference"],
        ["reporting_manager_reference"],
        ["hr_reference", "reporting_manager_reference"],
    ],
)
async def test_ordered_reference_pair_missing_member_blocks_final(completed_kinds, require_pair):
    service = HRV2Service.__new__(HRV2Service)
    employment_id = uuid4()
    rows = [
        SimpleNamespace(
            id=uuid4(),
            employment_id=employment_id,
            kind=kind,
            nomination={},
            answers={},
            status="completed",
            nominated_at=None,
            completed_at=None,
        )
        for kind in completed_kinds
    ]
    service._session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows)),
                SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [])),
            ]
        )
    )
    request = SimpleNamespace(
        public_id=uuid4(),
        employment_id=employment_id,
        request_type=VerificationRequestType.EMPLOYMENT,
        status=VerificationRequestStatus.VERIFIED,
        updated_at=datetime.now(UTC),
    )
    references = await service._reference_items([request], require_pair=require_pair)
    assert len(references) == (2 if require_pair else len(completed_kinds))
    ordered = {"references"} if require_pair else set()
    summaries = service._check_summaries([request], [], [], [], references, [], ordered=ordered)
    state, items, review = service._report_finality([request], summaries, ordered)
    incomplete = require_pair and len(completed_kinds) < 2
    assert state == ("INTERIM" if incomplete else "FINAL")
    assert bool(items) == review == incomplete


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [False, True])
async def test_omitted_vs_empty_types_before_any_persistence(explicit):
    service = TrustInvitationService.__new__(TrustInvitationService)
    service._organizations = SimpleNamespace(
        require_org_member=AsyncMock(
            return_value=(
                SimpleNamespace(
                    id=uuid4(), verification_preferences={"checks": {"identity": True}}
                ),
                None,
            )
        )
    )
    service._build_signed_token = lambda _: "synthetic"

    class Captured(Exception):
        pass

    async def capture(invitation):
        assert invitation.requested_verification_types == ([] if explicit else ["identity"])
        assert invitation.verification_preferences_snapshot["requested_types_source"] == (
            "explicit" if explicit else "defaults"
        )
        raise Captured

    service._repo = SimpleNamespace(create=capture)
    payload = {
        "subject_name": "Synthetic",
        "subject_email": "qa@example.com",
        "mode": "draft",
        "expires_at": datetime.now(UTC) + timedelta(days=1),
    }
    if explicit:
        payload["requested_verification_types"] = []
    with pytest.raises(Captured):
        await service.create(uuid4(), uuid4(), TrustInvitationCreateRequest(**payload))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "checks,count,message",
    [
        ({"address": True}, 0, "Address is not supported"),
        ({"references": True}, 2, "Reference-count orchestration is not supported"),
    ],
)
async def test_unsupported_orchestration_never_silently_succeeds(checks, count, message):
    service = TrustInvitationService.__new__(TrustInvitationService)
    service._organizations = SimpleNamespace(
        require_org_member=AsyncMock(
            return_value=(
                SimpleNamespace(
                    verification_preferences={"checks": checks, "reference_count": count}
                ),
                None,
            )
        )
    )
    with pytest.raises(ValidationAppError, match=message):
        await service.create(
            uuid4(),
            uuid4(),
            TrustInvitationCreateRequest(
                subject_name="Synthetic",
                subject_email="qa@example.com",
                mode="draft",
                expires_at=datetime.now(UTC) + timedelta(days=1),
            ),
        )
