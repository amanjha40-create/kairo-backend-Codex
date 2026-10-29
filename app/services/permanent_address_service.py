"""Owner-serialized versioned verification; no token, address or sample logging."""

import hashlib
import hmac
import json
import secrets
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config.permanent_address import validate_configuration
from app.core.constants import Role
from app.core.permissions import Permission, has_permission
from app.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationAppError,
)
from app.models.permanent_address import (
    PermanentAddressGeocodeBudget as Budget,
)
from app.models.permanent_address import (
    PermanentAddressReview as Review,
)
from app.models.permanent_address import (
    PermanentAddressSession as Session,
)
from app.models.permanent_address import (
    PermanentAddressVersion as Version,
)
from app.models.user import User
from app.models.user_account_event import UserAccountEvent
from app.models.user_document import UserDocument
from app.schemas.permanent_address import LocationChallenge, PermanentAddressState
from app.services.document_pack_storage import DocumentPackStorage
from app.services.permanent_address_documents import AddressDocumentMixin
from app.services.permanent_address_geocoder import TargetCipher, build_address_geocoder
from app.services.permanent_address_manual_review import (
    LOCKED_SOURCES,
    REVIEWABLE,
    ManualLocationReviewMixin,
    PendingTargetCipher,
    discard_pending,
    manual_eligible,
)
from app.services.permanent_address_onsite import ambiguous_area_valid
from app.services.permanent_address_policy import (
    LocationOutcome,
    LocationPolicy,
    assess_location_batch,
    calendar_day,
    count_days,
    document_match,
    evaluate_location,
    overall_status,
)
from app.services.permanent_address_quality import STREET_UNAVAILABLE_QUALITY, normalize
from app.services.private_owner_guard import lock_private_owner

ALLOWED_EVIDENCE = {"address_proof", "driving_license", "passport", "voter_id", "government_id"}


class PermanentAddressService(AddressDocumentMixin, ManualLocationReviewMixin):
    def __init__(self, session, settings, *, geocoder=None, clock=None, storage=None):
        self.db, self.settings = session, settings
        self.geocoder = geocoder or build_address_geocoder(settings)
        self.storage = storage or DocumentPackStorage(settings)
        self.clock = clock or (lambda: datetime.now(UTC))
        if clock is not None and str(settings.app_env) != "test":
            raise ValueError("Test clock is unavailable outside tests")

    def enabled(self):
        validate_configuration(self.settings)
        return self.settings.permanent_address_enabled

    def require_enabled(self):
        if not self.enabled():
            raise NotFoundError()

    async def current(self, owner):
        return await self.db.scalar(
            select(Version)
            .where(Version.user_id == owner, Version.invalidated_at.is_(None))
            .order_by(Version.version.desc())
            .limit(1)
        )

    async def active(self, owner, version_id):
        await lock_private_owner(self.db, owner)
        row = await self.current(owner)
        if row is None or row.id != version_id:
            raise NotFoundError()
        return row

    @staticmethod
    def confirmation_required(row):
        return (
            row.target_status == "confirmation_required"
            and row.target_source not in LOCKED_SOURCES
            and row.claimed_address.get("country") == "IN"
            and row.target_confirmation_reason
            in {
                "provider_ambiguity",
                "reviewed_provider_discrepancy",
                "address_version_changed",
            }
        )

    async def evidence_valid(self, owner, row):
        if not row.document_id:
            return None
        doc = await self.db.get(UserDocument, row.document_id)
        if (
            doc is None
            or doc.user_id != owner
            or doc.deleted_at
            or doc.superseded_at
            or doc.document_type not in ALLOWED_EVIDENCE
            or doc.verification_status not in {"approved", "pending"}
            or not doc.checksum_sha256
            or doc.checksum_sha256 != row.document_checksum
            or (doc.expires_at and doc.expires_at < calendar_day(self.clock()))
        ):
            return None
        try:
            evidence = await self.document_record(doc.id)
            if evidence and evidence.address_version_id != row.id:
                return None
            self.check_document_freshness(doc, evidence)
            if self.settings.permanent_address_enabled:
                if await self.document_binding(doc) != row.evidence_binding:
                    return None
            elif not row.evidence_binding:
                return None
            # OFF-state Admin projections describe persisted evidence only; they
            # cannot preview/approve it and must not inspect cloud storage.
        except (NotFoundError, ServiceUnavailableError, ValidationAppError):
            return None
        return doc

    async def document_binding(self, doc):
        binding = await self.storage.inspect(doc.object_key)
        if binding.size != doc.byte_size or binding.content_type != doc.content_type:
            raise ValidationAppError("Document upload is not complete")
        return {
            "etag": binding.etag,
            "version": binding.version,
            "size": binding.size,
            "content_type": binding.content_type,
        }

    async def available_evidence(self, owner):
        self.require_enabled()
        docs = (
            await self.db.scalars(
                select(UserDocument)
                .where(
                    UserDocument.user_id == owner,
                    UserDocument.deleted_at.is_(None),
                    UserDocument.superseded_at.is_(None),
                    UserDocument.document_type.in_(ALLOWED_EVIDENCE),
                    UserDocument.verification_status.in_(["pending", "approved"]),
                    UserDocument.checksum_sha256 != "",
                )
                .order_by(UserDocument.created_at.desc())
                .limit(100)
            )
        ).all()
        return {
            "items": [
                {"id": d.id, "document_type": d.document_type, "created_at": d.created_at}
                for d in docs
                if not d.expires_at or d.expires_at >= calendar_day(self.clock())
            ]
        }

    async def sessions(self, row):
        return list(
            (
                await self.db.scalars(
                    select(Session)
                    .where(Session.address_version_id == row.id, Session.cycle == row.cycle)
                    .order_by(Session.started_at)
                )
            ).all()
        )

    async def state(self, owner):
        if not self.enabled():
            return PermanentAddressState(enabled=False, status="NOT_STARTED")
        return await self._state_projection(owner, enabled=True)

    async def admin_state(self, reviewer, owner):
        await self.admin_read_actor(reviewer)
        return await self._state_projection(owner, enabled=self.settings.permanent_address_enabled)

    async def _state_projection(self, owner, *, enabled):
        row = await self.current(owner)
        if row is None:
            return PermanentAddressState(enabled=enabled, status="NOT_STARTED")
        now = self.clock()
        sessions = await self.sessions(row)
        days = [s.counted_day for s in sessions if s.counted_day]
        checks = 3 if row.completed_at else count_days(days, row.window_started_at, now)
        doc_status = row.document_status
        if row.document_id and not await self.evidence_valid(owner, row):
            doc_status = "NEEDS_REVIEW"
        if not row.document_id:
            doc_status = "REQUIRED"
        geocode = row.geocode_status
        if geocode == "REQUESTED" and now - row.created_at > timedelta(seconds=60):
            geocode = "NEEDS_REVIEW"
        today = calendar_day(now) in days
        checking = any(s.result == "CHECKING" and s.expires_at > now for s in sessions)
        can_start = (
            geocode == "READY"
            and (row.target_encrypted is not None or self.confirmation_required(row))
            and row.target_status not in {"needs_review", "superseded"}
            and not today
            and not checking
            and checks < 3
        )
        status = overall_status(doc_status, checks, geocode, checking=checking)
        if row.target_status == "needs_review":
            status = "NEEDS_REVIEW"
        return PermanentAddressState(
            enabled=enabled,
            status=status,
            address_version_id=row.id,
            address_version=row.version,
            claimed_address=row.claimed_address,
            document_status=doc_status,
            evidence_document_id=row.document_id,
            geocode_status=geocode,
            geocode_quality=(row.geocode_metadata or {}).get("quality"),
            target_confirmation_required=self.confirmation_required(row),
            target_source=row.target_source
            or ("provider_geocode" if row.target_encrypted else None),
            manual_review_status=await self.manual_review_label(
                row, sessions[-1] if sessions else None
            ),
            successful_gps_checks=checks,
            today_complete=today,
            can_start_location=enabled and can_start,
            last_location_result=sessions[-1].result
            if sessions and sessions[-1].result != "CHECKING"
            else None,
            expires_at=row.window_started_at + timedelta(days=7)
            if row.window_started_at and not row.completed_at
            else None,
            completed_at=row.completed_at if status == "PERMANENT_ADDRESS_VERIFIED" else None,
        )

    async def save_address(self, owner, payload):
        self.require_enabled()
        cipher = TargetCipher(self.settings)
        await lock_private_owner(self.db, owner)
        place_id = payload.google_place_id
        claimed = payload.model_dump(exclude={"google_place_id"})
        canonical = {k: normalize(v) for k, v in claimed.items()}
        digest = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
        previous = await self.current(owner)
        if (
            previous
            and previous.address_hash == digest
            and (
                not place_id
                or (
                    previous.geocode_status == "READY"
                    and (previous.geocode_metadata or {}).get("resolution_mode") == "place_id"
                )
            )
        ):
            return await self.state(owner)
        now = self.clock()
        recent = list(
            (
                await self.db.scalars(
                    select(Version.id).where(
                        Version.user_id == owner, Version.created_at >= now - timedelta(days=1)
                    )
                )
            ).all()
        )
        if len(recent) >= 5:
            raise RateLimitError("Too many address changes; try again later")
        month = now.strftime("%Y-%m")
        await self.db.execute(
            insert(Budget).values(month=month, request_count=0).on_conflict_do_nothing()
        )
        budget = await self.db.scalar(select(Budget).where(Budget.month == month).with_for_update())
        if budget.request_count >= self.settings.permanent_address_monthly_geocode_limit:
            raise RateLimitError("Address lookup limit reached; try again later")
        budget.request_count += 1
        if previous:
            if previous.document_id:
                self.document_event(
                    previous,
                    previous.document_id,
                    "approval_invalidated_by_address_edit",
                )
            previous.invalidated_at = now
            previous.target_status = "superseded"
            attempts = (
                await self.db.scalars(
                    select(Session).where(Session.address_version_id == previous.id)
                )
            ).all()
            for attempt in attempts:
                if attempt.manual_review_status in REVIEWABLE:
                    discard_pending(attempt, "invalidated")
        row = Version(
            id=uuid4(),
            user_id=owner,
            version=previous.version + 1 if previous else 1,
            claimed_address=claimed,
            address_hash=digest,
            geocode_status="REQUESTED",
            document_status="REQUIRED",
            cycle=1,
        )
        self.db.add(row)
        # Persist the paid-call reservation before network I/O. A crash or retry
        # cannot automatically spend again for this address version.
        await self.db.commit()
        try:
            if place_id:
                metadata, target = await self.geocoder.geocode_place_id(claimed, place_id)
            else:
                metadata, target = await self.geocoder.geocode(claimed)
        except ServiceUnavailableError:
            metadata, target = (
                {
                    "provider": getattr(self.geocoder, "provider_name", "unavailable"),
                    "classification": "ADDRESS_NEEDS_REVIEW",
                    "reasons": ["provider_unavailable"],
                    "resolution_mode": "place_id" if place_id else "text",
                },
                None,
            )
        row = await self.active(owner, row.id)
        row.geocode_metadata = metadata
        row.geocoded_at = self.clock()
        row.geocode_status = "READY" if target else "NEEDS_REVIEW"
        row.target_source = "provider_geocode"
        row.target_status = "active" if target else "needs_review"
        if target:
            row.target_key_id = cipher.active
            row.target_encrypted = cipher.encrypt(target, owner, row.id)
        if ambiguous_area_valid(metadata):
            row.geocode_status = "READY"
            row.target_status = "confirmation_required"
            row.target_confirmation_reason = "provider_ambiguity"
        elif (
            target
            and previous
            and (previous.target_source in LOCKED_SOURCES or previous.target_confirmation_reason)
        ):
            row.target_status = "confirmation_required"
            row.target_confirmation_reason = "address_version_changed"
        await self.db.commit()
        return await self.state(owner)

    async def attach_evidence(self, owner, payload):
        self.require_enabled()
        row = await self.active(owner, payload.address_version_id)
        doc = await self.db.get(UserDocument, payload.document_id)
        if doc is None or doc.user_id != owner or doc.deleted_at:
            raise NotFoundError()
        if (
            doc.superseded_at
            or doc.document_type not in ALLOWED_EVIDENCE
            or doc.verification_status not in {"pending", "approved"}
            or not doc.checksum_sha256
            or (doc.expires_at and doc.expires_at < calendar_day(self.clock()))
        ):
            raise ValidationAppError("Select a completed current address-bearing document")
        binding = await self.document_binding(doc)
        if (
            row.document_id == doc.id
            and row.document_checksum == doc.checksum_sha256
            and row.evidence_binding == binding
        ):
            return await self.state(owner)
        if row.completed_at or row.document_status == "MATCH":
            raise ConflictError("The current address document is already approved")
        await self.bind_address_document(row, doc, binding)
        row.document_id, row.document_checksum = doc.id, doc.checksum_sha256
        row.evidence_binding = binding
        # Current extractors do not certify structured addresses. A human review
        # must explicitly compare this document with this immutable address version.
        row.document_status = "NEEDS_REVIEW"
        row.completed_at = None
        await self.db.commit()
        return await self.state(owner)

    async def review_queue(self, reviewer):
        await self.admin_read_actor(reviewer)
        rows = (
            await self.db.scalars(
                select(Version)
                .where(
                    Version.invalidated_at.is_(None),
                    Version.user_id != reviewer,
                    Version.document_id.is_not(None),
                    Version.document_status == "NEEDS_REVIEW",
                )
                .order_by(Version.created_at)
                .limit(50)
            )
        ).all()
        # List contains no exact address, coordinates, object key or document bytes.
        return {
            "items": [{"address_version_id": row.id, "created_at": row.created_at} for row in rows]
        }

    async def review_detail(self, reviewer, version_id, *, content=False):
        if content:
            await self.manual_actor(reviewer)
        else:
            await self.admin_read_actor(reviewer)
        row = await self.db.get(Version, version_id)
        if row is None or row.invalidated_at or row.user_id == reviewer:
            raise NotFoundError()
        doc = await self.evidence_valid(row.user_id, row)
        if doc is None:
            raise ConflictError("Address evidence is no longer eligible")
        if not content:
            return {
                "address_version_id": row.id,
                "claimed_address": row.claimed_address,
                "document_id": doc.id,
                "document_type": doc.document_type,
                "document_status": row.document_status,
            }
        from types import SimpleNamespace

        item = SimpleNamespace(
            object_key=doc.object_key,
            object_version=row.evidence_binding["version"],
            object_etag=row.evidence_binding["etag"],
            byte_size=doc.byte_size,
            filename="address-evidence",
        )
        chunks, headers = await self.storage.open(item)
        return chunks, headers, doc.content_type

    async def review(self, reviewer, version_id, payload):
        await self.manual_actor(reviewer)
        row = await self.db.get(Version, version_id)
        if row is None:
            raise NotFoundError()
        if row.user_id == reviewer:
            raise ForbiddenError("Self-review is not permitted")
        row = await self.active(row.user_id, version_id)
        doc = await self.evidence_valid(row.user_id, row)
        if doc is None or doc.id != payload.document_id:
            raise ConflictError("Address evidence is no longer eligible")
        outcome = payload.outcome
        if outcome == "MATCH":
            if payload.observed_address is None:
                raise ValidationAppError("A reviewed structured document address is required")
            outcome = document_match(row.claimed_address, payload.observed_address.model_dump())
        row.document_status = outcome
        evidence = await self.document_record(doc.id)
        if evidence:
            evidence.status = {
                "MATCH": "MATCH",
                "MISMATCH": "REJECTED",
                "NEEDS_REVIEW": "NEEDS_CORRECTION",
            }[outcome]
        self.document_event(row, doc.id, "legacy_review_" + outcome.lower(), reviewer)
        row.completed_at = None
        self.db.add(
            Review(
                address_version_id=row.id,
                reviewer_id=reviewer,
                document_id=doc.id,
                document_checksum=doc.checksum_sha256,
                outcome=outcome,
            )
        )
        now = self.clock()
        sessions = await self.sessions(row)
        if (
            outcome == "MATCH"
            and count_days(
                [s.counted_day for s in sessions if s.counted_day], row.window_started_at, now
            )
            >= 3
        ):
            row.completed_at = now
        await self.db.commit()
        return {"document_status": outcome}

    async def resolve_location_review(self, reviewer, version_id, session_id, payload):
        self.require_enabled()
        actor = await self.db.get(User, reviewer)
        if (
            actor is None
            or not actor.is_active
            or actor.email_verified_at is None
            or actor.role not in {Role.ADMIN, Role.SUPERADMIN}
            or not has_permission(actor.role, Permission.REVIEW_VERIFICATION)
        ):
            raise ForbiddenError("Authorized review access required")
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
        if attempt.result != "NEEDS_REVIEW" or attempt.completed_at is None:
            raise ConflictError("This location attempt is not reviewable")
        evidence = attempt.derived_evidence or {}
        previous = evidence.get("review_resolution")
        if previous is not None:
            # Replay acknowledges the original disposition; it never rearms a later attempt.
            if previous.get("resolution") != payload.resolution:
                raise ConflictError("This location review is already resolved")
            return previous
        history = await self.sessions(row)
        if (
            payload.resolution != "retry_allowed"
            or attempt.manual_review_status is not None
            or not history
            or history[-1].id != attempt.id
            or attempt.cycle != row.cycle
            or any(s.counted_day or s.result == "CHECKING" for s in history)
            or row.completed_at
            or row.target_confirmed_at
            or row.target_source != "provider_geocode"
            or row.target_status != "needs_review"
            or row.geocode_status != "READY"
            or not row.target_encrypted
            or row.claimed_address.get("country") != "IN"
        ):
            raise ConflictError("The current address is not eligible for this review resolution")
        now, event_id = self.clock(), uuid4()
        resolution = {
            "resolution": "retry_allowed",
            "reviewed_at": now.isoformat(),
            "reviewer_id": str(reviewer),
            "audit_event_id": str(event_id),
        }
        attempt.derived_evidence = {**evidence, "review_resolution": resolution}
        row.target_status = "confirmation_required"
        row.target_confirmation_reason = "reviewed_provider_discrepancy"
        self.db.add(
            UserAccountEvent(
                id=event_id,
                user_id=row.user_id,
                actor_user_id=reviewer,
                actor_role=actor.role,
                event_type="permanent_address_retry_allowed",
                title="Manual location review resolved - retry allowed",
                metadata_payload={
                    "address_version_id": str(row.id),
                    "session_id": str(attempt.id),
                    "resolution": "retry_allowed",
                    "previous_result": "NEEDS_REVIEW",
                },
                created_at=now,
            )
        )
        await self.db.commit()
        return resolution

    async def start(self, owner, version_id):
        self.require_enabled()
        row = await self.active(owner, version_id)
        now = self.clock()
        if (
            row.window_started_at
            and now >= row.window_started_at + timedelta(days=7)
            and not row.completed_at
        ):
            row.cycle += 1
            row.window_started_at = None
        state = await self.state(owner)
        if not state.can_start_location:
            raise ConflictError("A location check cannot start for the current address state")
        history = await self.sessions(row)
        if (
            len(history) >= 21
            or sum(s.started_at >= now - timedelta(hours=1) for s in history) >= 5
        ):
            raise RateLimitError("Location check limit reached; try again later")
        if not self.confirmation_required(row):
            TargetCipher(self.settings).decrypt(
                row.target_encrypted, row.target_key_id, owner, row.id
            )
        challenge = secrets.token_urlsafe(32)
        session = Session(
            id=uuid4(),
            address_version_id=row.id,
            cycle=row.cycle,
            challenge_hash=hashlib.sha256(challenge.encode()).hexdigest(),
            started_at=now,
            expires_at=now + timedelta(seconds=120),
            result="CHECKING",
        )
        self.db.add(session)
        if row.window_started_at is None:
            row.window_started_at = now
        await self.db.commit()
        return LocationChallenge(
            session_id=session.id, challenge=challenge, expires_at=session.expires_at
        )

    async def finish(self, owner, session_id, payload, *, cancel=False):
        self.require_enabled()
        await lock_private_owner(self.db, owner)
        session = await self.db.scalar(
            select(Session)
            .join(Version, Version.id == Session.address_version_id)
            .where(Session.id == session_id, Version.user_id == owner)
            .with_for_update()
        )
        if session is None:
            raise NotFoundError()
        row = await self.active(owner, session.address_version_id)
        if not hmac.compare_digest(
            session.challenge_hash, hashlib.sha256(payload.challenge.encode()).hexdigest()
        ):
            raise NotFoundError()
        if session.result != "CHECKING" or session.cycle != row.cycle:
            raise ConflictError("This location session is no longer active")
        now = self.clock()
        if cancel or now >= session.expires_at:
            session.result = "CANCELLED" if cancel else "RETRY_REQUIRED"
        else:
            if row.geocode_status != "READY":
                raise ConflictError("Review the address before checking location")
            policy = LocationPolicy(
                precise_radius_m=self.settings.permanent_address_radius_m,
                approximate_radius_m=self.settings.permanent_address_approximate_radius_m,
                street_unavailable_radius_m=(
                    self.settings.permanent_address_street_unavailable_radius_m
                ),
            )
            if self.confirmation_required(row):
                outcome = await self.enroll_target(
                    owner, row, session, payload.samples, now, policy
                )
            else:
                if row.target_status in {"needs_review", "superseded"}:
                    raise ConflictError("Review the address before checking location")
                target = TargetCipher(self.settings).decrypt(
                    row.target_encrypted, row.target_key_id, owner, row.id
                )["position"]
                outcome = evaluate_location(
                    payload.samples,
                    (target[1], target[0]),
                    session.started_at,
                    now,
                    STREET_UNAVAILABLE_QUALITY
                    if row.target_source in LOCKED_SOURCES
                    else row.geocode_metadata["quality"],
                    policy,
                )
            audit = session.derived_evidence or {}
            session.result, session.derived_evidence = outcome.result, asdict(outcome)
            if "onsite_confirmation" in audit:
                session.derived_evidence = {
                    **session.derived_evidence,
                    "onsite_confirmation": audit["onsite_confirmation"],
                }
            if outcome.result == "MATCHED":
                day = calendar_day(now)
                if not any(s.counted_day == day for s in await self.sessions(row)):
                    session.counted_day = day
        session.completed_at = now
        await self.db.flush()
        sessions = await self.sessions(row)
        if (
            row.document_status == "MATCH"
            and await self.evidence_valid(owner, row)
            and count_days(
                [s.counted_day for s in sessions if s.counted_day], row.window_started_at, now
            )
            >= 3
        ):
            row.completed_at = now
        await self.db.commit()
        return await self.state(owner)

    async def enroll_target(self, owner, row, session, samples, now, policy):
        outcome, representative = assess_location_batch(samples, session.started_at, now, policy)
        if representative is None:
            if outcome.result == "NEEDS_REVIEW":
                row.target_status = "needs_review"
            return outcome
        outcome = LocationOutcome(
            "MATCHED", round(outcome.accuracy_m, 1), sample_count=outcome.sample_count
        )
        cipher = TargetCipher(self.settings)
        month = now.strftime("%Y-%m")
        await self.db.execute(
            insert(Budget).values(month=month, request_count=0).on_conflict_do_nothing()
        )
        budget = await self.db.scalar(select(Budget).where(Budget.month == month).with_for_update())
        if budget.request_count >= self.settings.permanent_address_monthly_geocode_limit:
            return LocationOutcome(
                "NEEDS_REVIEW", outcome.accuracy_m, sample_count=outcome.sample_count
            )
        budget.request_count += 1
        # Durable one-shot reservation. A crash, duplicate completion, or timeout
        # leaves review required, never another provider call or silent recentering.
        row.target_status = "needs_review"
        session.result = "NEEDS_REVIEW"
        session.completed_at = now
        session.derived_evidence = {
            **asdict(outcome),
            "result": "NEEDS_REVIEW",
            "onsite_confirmation": {"provider_call_reserved": True},
        }
        await self.db.commit()
        try:
            decision = await self.geocoder.confirm_area(row.claimed_address, representative)
        except ServiceUnavailableError:
            decision = {"accepted": False, "reason": "provider_unavailable"}
        # An address edit or deletion while AWS was in flight cannot enroll the old version.
        await lock_private_owner(self.db, owner)
        await self.db.refresh(row)
        await self.db.refresh(session)
        await self.active(owner, row.id)
        if row.target_status != "needs_review" or row.target_source in LOCKED_SOURCES:
            raise ConflictError("Address target state changed during confirmation")
        session.derived_evidence = {
            "onsite_confirmation": {**decision, "provider_call_reserved": True}
        }
        if not decision["accepted"]:
            if manual_eligible(decision):
                pending = PendingTargetCipher(self.settings, session.id)
                session.pending_target_encrypted = pending.encrypt(
                    {"position": [representative[1], representative[0]]},
                    owner,
                    row.id,
                )
                session.pending_target_key_id = pending.active
                session.manual_review_status = "pending"
            return LocationOutcome(
                "NEEDS_REVIEW", outcome.accuracy_m, sample_count=outcome.sample_count
            )
        row.target_encrypted = cipher.encrypt(
            {"position": [representative[1], representative[0]]},
            owner,
            row.id,
        )
        row.target_key_id = cipher.active
        row.target_source = "onsite_confirmation"
        row.target_status = "active"
        row.target_confirmed_at = self.clock()
        row.geocode_metadata = {**(row.geocode_metadata or {}), "provider_target_superseded": True}
        return outcome
