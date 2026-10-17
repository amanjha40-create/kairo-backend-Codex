"""Read-only composition of the certified Permanent Address domain projections."""

from sqlalchemy import select

from app.core.constants import Role
from app.exceptions import NotFoundError
from app.models.permanent_address import PermanentAddressDocument as Evidence
from app.models.permanent_address import PermanentAddressReview as Review
from app.models.permanent_address import PermanentAddressVersion as Version
from app.models.user import User
from app.models.user_account_event import UserAccountEvent
from app.models.user_document import UserDocument
from app.schemas.permanent_address_admin import (
    AdminAddressDetail,
    AdminAddressDiscovery,
    AdminAddressDocument,
    AdminAddressEvent,
    AdminAddressSummary,
    AdminAddressVersion,
)

DOCUMENT_EVENTS = frozenset(
    {
        "upload_started",
        "uploaded",
        "submitted",
        "replaced",
        "approve_matching",
        "reject",
        "request_correction",
        "request_different_document",
        "approval_invalidated_by_address_edit",
        "legacy_review_match",
        "legacy_review_mismatch",
        "legacy_review_needs_review",
    }
)


class PermanentAddressAdminRead:
    def __init__(self, service):
        self.svc = service
        self.db = service.db

    async def _candidate(self, reviewer, candidate_id):
        await self.svc.admin_read_actor(reviewer)
        candidate = await self.db.get(User, candidate_id)
        if candidate is None or candidate.role != Role.USER or candidate_id == reviewer:
            raise NotFoundError()

    async def _summary(self, reviewer, candidate_id):
        state = await self.svc.admin_state(reviewer, candidate_id)
        row = await self.svc.current(candidate_id)
        attempts = await self.svc.sessions(row) if row else []
        latest = (
            await self.svc.manual_location_detail(reviewer, row.id, attempts[-1].id)
            if attempts
            else None
        )
        return (
            AdminAddressSummary(
                candidate_id=candidate_id,
                address_version_id=state.address_version_id,
                address_version=state.address_version,
                overall_status=state.status,
                document_status=state.document_status,
                successful_location_checks=state.successful_gps_checks,
                today_complete=state.today_complete,
                cycle_expires_at=state.expires_at,
                manual_review_status=state.manual_review_status,
                pending_manual_review_target_available=bool(
                    latest and latest["pending_target_available"]
                ),
                manual_location_approval_eligible=bool(latest and latest["approval_eligible"]),
                active_target_source=state.target_source,
                current_attempt_state=attempts[-1].result if attempts else None,
            ),
            row,
            latest,
        )

    async def discover(self, reviewer, *, limit=20, offset=0, candidate_id=None):
        await self.svc.admin_read_actor(reviewer)
        if not 1 <= limit <= 50 or offset < 0:
            raise ValueError("Invalid bounded page")
        query = (
            select(Version)
            .join(User, User.id == Version.user_id)
            .where(
                Version.invalidated_at.is_(None),
                Version.user_id != reviewer,
                User.role == Role.USER,
            )
        )
        if candidate_id is not None:
            await self._candidate(reviewer, candidate_id)
            query = query.where(Version.user_id == candidate_id)
        rows = list(
            (
                await self.db.scalars(
                    query.order_by(Version.created_at.desc(), Version.id)
                    .offset(offset)
                    .limit(limit + 1)
                )
            ).all()
        )
        items = [(await self._summary(reviewer, row.user_id))[0] for row in rows[:limit]]
        return AdminAddressDiscovery(
            items=items, next_offset=offset + limit if len(rows) > limit else None
        )

    async def detail(self, reviewer, candidate_id, *, address_version_id=None):
        await self._candidate(reviewer, candidate_id)
        row = await self.svc.current(candidate_id)
        if address_version_id is not None and (row is None or row.id != address_version_id):
            raise NotFoundError()
        summary, row, latest = await self._summary(reviewer, candidate_id)
        if row is None:
            return AdminAddressDetail(
                permanent_address=summary, claimed_address=None, document=AdminAddressDocument()
            )
        state = await self.svc.document_state_for_version(row)
        doc = await self.db.get(UserDocument, state.document_id) if state.document_id else None
        if doc is not None and doc.user_id != candidate_id:
            raise NotFoundError()
        present = bool(doc and not doc.deleted_at and not doc.superseded_at)
        evidence = (
            await self.db.scalar(select(Evidence).where(Evidence.document_id == state.document_id))
            if present
            else None
        )
        valid = await self.svc.evidence_valid(candidate_id, row)
        preview = bool(
            self.svc.settings.permanent_address_enabled
            and present and valid and valid.id == state.document_id
        )
        review = (
            await self.db.scalar(
                select(Review)
                .where(Review.address_version_id == row.id, Review.document_id == state.document_id)
                .order_by(Review.created_at.desc(), Review.id)
                .limit(1)
            )
            if present
            else None
        )
        versions = list(
            (
                await self.db.scalars(
                    select(Version)
                    .where(Version.user_id == candidate_id)
                    .order_by(Version.version.desc())
                )
            ).all()
        )
        events = list(
            (
                await self.db.scalars(
                    select(UserAccountEvent)
                    .where(
                        UserAccountEvent.user_id == candidate_id,
                        UserAccountEvent.event_type == "permanent_address_document",
                        UserAccountEvent.metadata_payload["address_version_id"].astext
                        == str(row.id),
                    )
                    .order_by(UserAccountEvent.created_at.desc())
                    .limit(100)
                )
            ).all()
        )
        return AdminAddressDetail(
            permanent_address=summary,
            claimed_address=row.claimed_address,
            document=AdminAddressDocument(
                present=present,
                document_id=doc.id if present else None,
                document_type=doc.document_type if present else None,
                upload_state=evidence.status if evidence else None,
                review_state=state.status if present else "REQUIRED",
                uploaded_at=state.uploaded_at,
                issued_on=state.issued_on,
                reviewed_at=review.created_at if review else None,
                preview_available=preview,
                content_path=f"/api/v1/permanent-address/reviews/{row.id}/content"
                if preview
                else None,
            ),
            latest_attempt=latest,
            versions=[
                AdminAddressVersion(
                    address_version_id=v.id,
                    address_version=v.version,
                    current=v.id == row.id,
                    created_at=v.created_at,
                    invalidated_at=v.invalidated_at,
                )
                for v in versions
            ],
            audit=[
                AdminAddressEvent(action=e.metadata_payload["action"], at=e.created_at)
                for e in events
                if e.metadata_payload.get("action") in DOCUMENT_EVENTS
            ],
        )
