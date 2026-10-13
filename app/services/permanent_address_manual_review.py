"""Prospective, document-backed review of encrypted GPS representatives only."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from app.core.constants import Role
from app.core.permissions import Permission, has_permission
from app.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.models.permanent_address import PermanentAddressSession as Session
from app.models.permanent_address import PermanentAddressVersion as Version
from app.models.user import User
from app.models.user_account_event import UserAccountEvent
from app.services.permanent_address_geocoder import TargetCipher
from app.services.permanent_address_policy import calendar_day

LOCKED_SOURCES = {"onsite_confirmation", "onsite_confirmation_manual_review"}
REVIEWABLE = {"pending", "additional_evidence_requested"}
OUTCOMES = {
    "APPROVE_ONSITE_LOCATION": "approved",
    "REJECT_ONSITE_LOCATION": "rejected",
    "REQUEST_ADDRESS_CORRECTION": "correction_requested",
    "REQUEST_ADDITIONAL_EVIDENCE": "additional_evidence_requested",
}


class PendingTargetCipher(TargetCipher):
    def __init__(self, settings, attempt_id):
        super().__init__(settings)
        self.attempt_id = attempt_id

    def aad(self, owner, version, key_id):
        return super().aad(owner, version, key_id) + f":pending-review:{self.attempt_id}".encode()


def manual_eligible(decision):
    """Never combine component agreement across different provider candidates."""
    if decision.get("accepted") is not False:
        return False
    diagnostics = decision.get("diagnostics") or {}
    candidates = diagnostics.get(
        "candidate_evaluations", [{**diagnostics, "reason": decision.get("reason")}]
    )
    return any(
        c.get("reason") in {"street_conflict", "address_number_conflict"}
        and c.get("reverse_precision_supported") is True
        and c.get("reverse_estimated_point_address_valid") is True
        and all(
            c.get(k) is True
            for k in (
                "country_match",
                "state_match",
                "city_match",
                "postal_code_match",
                "provider_postal_code_present",
            )
        )
        for c in candidates[:5]
    )


def discard_pending(attempt, status):
    attempt.pending_target_encrypted = None
    attempt.pending_target_key_id = None
    attempt.manual_review_status = status


class ManualLocationReviewMixin:
    async def manual_actor(self, reviewer):
        self.require_enabled()
        actor = await self.db.get(User, reviewer, populate_existing=True)
        if (
            actor is None
            or not actor.is_active
            or actor.email_verified_at is None
            or actor.role not in {Role.ADMIN, Role.SUPERADMIN}
            or not has_permission(actor.role, Permission.REVIEW_VERIFICATION)
        ):
            raise ForbiddenError("Authorized review access required")
        return actor

    async def manual_review_label(self, row, attempt):
        if attempt is None or attempt.result != "NEEDS_REVIEW":
            return None
        if attempt.manual_review_status and attempt.manual_review_status not in REVIEWABLE:
            return attempt.manual_review_status
        if row.document_status != "MATCH" or not await self.evidence_valid(row.user_id, row):
            return "waiting_for_address_document"
        if not attempt.pending_target_encrypted:
            return "historical_target_not_retained"
        if not row.window_started_at or self.clock() >= row.window_started_at + timedelta(days=7):
            return "review_window_expired"
        return attempt.manual_review_status

    async def manual_location_queue(self, reviewer):
        await self.manual_actor(reviewer)
        rows = (
            await self.db.execute(
                select(Version, Session)
                .join(Session, Session.address_version_id == Version.id)
                .where(
                    Version.invalidated_at.is_(None),
                    Version.user_id != reviewer,
                    Session.result == "NEEDS_REVIEW",
                    Session.cycle == Version.cycle,
                    Session.manual_review_status.in_(REVIEWABLE),
                    Session.pending_target_encrypted.is_not(None),
                )
                .order_by(Session.started_at)
                .limit(50)
            )
        ).all()
        return {
            "items": [
                {
                    "candidate_id": row.user_id,
                    "address_version_id": row.id,
                    "session_id": attempt.id,
                    "attempted_at": attempt.started_at,
                    "manual_review_status": await self.manual_review_label(row, attempt),
                }
                for row, attempt in rows
            ]
        }

    async def manual_location_detail(self, reviewer, version_id, session_id):
        await self.manual_actor(reviewer)
        row = await self.db.get(Version, version_id)
        attempt = await self.db.get(Session, session_id)
        if (
            row is None
            or row.user_id == reviewer
            or attempt is None
            or attempt.address_version_id != row.id
        ):
            raise NotFoundError()
        history = list(
            (
                await self.db.scalars(
                    select(Session)
                    .where(Session.address_version_id == row.id)
                    .order_by(Session.started_at)
                )
            ).all()
        )
        evidence = attempt.derived_evidence or {}
        automatic = evidence.get("onsite_confirmation") or {}
        diagnostic = automatic.get("diagnostics") or {}
        # Project an explicit allowlist, never ORM or provider payload serialization.
        flags = (
            "country_match",
            "state_match",
            "city_match",
            "postal_code_match",
            "provider_postal_code_present",
            "reverse_place_type",
            "reverse_estimated_point_address",
            "reverse_precision_supported",
            "street_match",
            "street_decision_reason",
            "address_number_state",
        )
        candidates = diagnostic.get("candidate_evaluations", [diagnostic])[:5]
        available = bool(attempt.pending_target_encrypted)
        current = row.invalidated_at is None and attempt.cycle == row.cycle
        status = await self.manual_review_label(row, attempt)
        return {
            "candidate_id": row.user_id,
            "address_version_id": row.id,
            "address_version": row.version,
            "session_id": attempt.id,
            "current_address_version": current,
            "manual_review_status": status,
            "pending_target_available": available,
            "approval_eligible": current and available and status in REVIEWABLE,
            "gps_quality": "PASS"
            if attempt.manual_review_status
            else "not_certified_for_manual_review",
            "accepted_sample_count": evidence.get("sample_count"),
            "accuracy_m": evidence.get("accuracy_m"),
            "candidate_count": diagnostic.get(
                "bounded_result_count", diagnostic.get("reverse_result_count", 0)
            ),
            "candidate_comparisons": [{k: c.get(k) for k in flags} for c in candidates],
            "automatic_result": attempt.result,
            "automatic_failure_reason": automatic.get("reason"),
            "document_status": row.document_status,
            "attempted_at": attempt.started_at,
            "prior_attempt_count": sum(s.started_at < attempt.started_at for s in history),
            "history": [
                {
                    "session_id": s.id,
                    "attempted_at": s.started_at,
                    "automatic_result": s.result,
                    "manual_review_status": s.manual_review_status,
                }
                for s in history
            ],
            "resolutions": attempt.manual_resolutions or [],
        }

    async def resolve_manual_location(self, reviewer, version_id, session_id, payload):
        actor = await self.manual_actor(reviewer)
        if reviewer == payload.candidate_id:
            raise ForbiddenError("Self-review is not permitted")
        row = await self.active(payload.candidate_id, version_id)
        await self.db.refresh(row)
        attempt = await self.db.scalar(
            select(Session)
            .where(Session.id == session_id, Session.address_version_id == row.id)
            .execution_options(populate_existing=True)
        )
        if attempt is None:
            raise NotFoundError()
        receipts = attempt.manual_resolutions or []
        for receipt in receipts:
            if receipt["idempotency_key"] == str(payload.idempotency_key):
                if receipt["outcome"] != payload.outcome:
                    raise ConflictError("Idempotency key already used for a different outcome")
                return receipt
        if receipts and receipts[-1]["outcome"] == payload.outcome:
            return receipts[-1]
        history = await self.sessions(row)
        if (
            payload.outcome not in OUTCOMES
            or attempt.result != "NEEDS_REVIEW"
            or not attempt.completed_at
            or attempt.manual_review_status not in REVIEWABLE
            or not attempt.pending_target_encrypted
            or not attempt.pending_target_key_id
            or not history
            or history[-1].id != attempt.id
            or attempt.cycle != row.cycle
            or any(s.counted_day or s.result == "CHECKING" for s in history)
            or row.completed_at
            or row.target_confirmed_at
            or row.target_source != "provider_geocode"
            or row.target_status != "needs_review"
            or not manual_eligible((attempt.derived_evidence or {}).get("onsite_confirmation", {}))
        ):
            raise ConflictError("This location attempt is not eligible for manual review")
        now = self.clock()
        if payload.outcome == "APPROVE_ONSITE_LOCATION":
            if row.document_status != "MATCH" or not await self.evidence_valid(row.user_id, row):
                raise ValidationAppError(
                    "An approved matching address document is required",
                    code="ADDRESS_DOCUMENT_REQUIRED_FOR_MANUAL_LOCATION_APPROVAL",
                )
            if not row.window_started_at or now >= row.window_started_at + timedelta(days=7):
                raise ConflictError("The original location cycle has expired")
            point = PendingTargetCipher(self.settings, attempt.id).decrypt(
                attempt.pending_target_encrypted, attempt.pending_target_key_id, row.user_id, row.id
            )
            cipher = TargetCipher(self.settings)
            row.target_encrypted = cipher.encrypt(point, row.user_id, row.id)
            row.target_key_id = cipher.active
            row.target_source = "onsite_confirmation_manual_review"
            row.target_status = "active"
            row.target_confirmed_at = now
            row.geocode_metadata = {
                **(row.geocode_metadata or {}),
                "provider_target_superseded": True,
            }
            # Count the physical observation day, never the later review day.
            attempt.counted_day = calendar_day(attempt.completed_at)
        status = OUTCOMES[payload.outcome]
        if status == "additional_evidence_requested":
            attempt.manual_review_status = status
            row.document_status = "NEEDS_REVIEW" if row.document_id else "REQUIRED"
        else:
            discard_pending(attempt, status)
        event_id = uuid4()
        receipt = {
            "outcome": payload.outcome,
            "reviewed_at": now.isoformat(),
            "reviewer_id": str(reviewer),
            "audit_event_id": str(event_id),
            "idempotency_key": str(payload.idempotency_key),
        }
        attempt.manual_resolutions = [*receipts, receipt]
        self.db.add(
            UserAccountEvent(
                id=event_id,
                user_id=row.user_id,
                actor_user_id=reviewer,
                actor_role=actor.role,
                event_type="permanent_address_location_review",
                title="Permanent Address location review resolved",
                metadata_payload={
                    "address_version_id": str(row.id),
                    "session_id": str(attempt.id),
                    "outcome": payload.outcome,
                    "previous_result": "NEEDS_REVIEW",
                },
                created_at=now,
            )
        )
        await self.db.commit()
        return receipt
