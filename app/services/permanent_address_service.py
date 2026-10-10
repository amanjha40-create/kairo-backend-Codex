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
from app.models.user_document import UserDocument
from app.schemas.permanent_address import LocationChallenge, PermanentAddressState
from app.services.document_pack_storage import DocumentPackStorage
from app.services.permanent_address_geocoder import AmazonAddressGeocoder, TargetCipher
from app.services.permanent_address_policy import (
    LocationPolicy,
    calendar_day,
    count_days,
    document_match,
    evaluate_location,
    overall_status,
)
from app.services.permanent_address_quality import normalize
from app.services.private_owner_guard import lock_private_owner

ALLOWED_EVIDENCE = {"address_proof", "driving_license", "passport", "voter_id", "government_id"}


class PermanentAddressService:
    def __init__(self, session, settings, *, geocoder=None, clock=None, storage=None):
        self.db, self.settings = session, settings
        self.geocoder = geocoder or AmazonAddressGeocoder()
        self.storage = storage or DocumentPackStorage(settings)
        self.clock = clock or (lambda: datetime.now(UTC))
        if clock is not None and str(settings.app_env) != "test":
            raise ValueError("Test clock is unavailable outside tests")

    def enabled(self):
        return self.settings.permanent_address_enabled and str(self.settings.app_env) in {
            "test",
            "staging",
        }

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
            if await self.document_binding(doc) != row.evidence_binding:
                return None
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
        row = await self.current(owner)
        if row is None:
            return PermanentAddressState(enabled=True, status="NOT_STARTED")
        now = self.clock()
        sessions = await self.sessions(row)
        days = [s.counted_day for s in sessions if s.result == "MATCHED" and s.counted_day]
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
            and row.target_encrypted is not None
            and not today
            and not checking
            and checks < 3
        )
        status = overall_status(doc_status, checks, geocode, checking=checking)
        return PermanentAddressState(
            enabled=True,
            status=status,
            address_version_id=row.id,
            address_version=row.version,
            claimed_address=row.claimed_address,
            document_status=doc_status,
            evidence_document_id=row.document_id,
            geocode_status=geocode,
            geocode_quality=(row.geocode_metadata or {}).get("quality"),
            successful_gps_checks=checks,
            today_complete=today,
            can_start_location=can_start,
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
        claimed = payload.model_dump()
        canonical = {k: normalize(v) for k, v in claimed.items()}
        digest = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
        previous = await self.current(owner)
        if previous and previous.address_hash == digest:
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
            previous.invalidated_at = now
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
            metadata, target = await self.geocoder.geocode(claimed)
        except ServiceUnavailableError:
            metadata, target = (
                {
                    "provider": "amazon_location",
                    "classification": "ADDRESS_NEEDS_REVIEW",
                    "reasons": ["provider_unavailable"],
                },
                None,
            )
        row = await self.active(owner, row.id)
        row.geocode_metadata = metadata
        row.geocoded_at = self.clock()
        row.geocode_status = "READY" if target else "NEEDS_REVIEW"
        if target:
            row.target_key_id = cipher.active
            row.target_encrypted = cipher.encrypt(target, owner, row.id)
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
        row.document_id, row.document_checksum = doc.id, doc.checksum_sha256
        row.evidence_binding = binding
        # Current extractors do not certify structured addresses. A human review
        # must explicitly compare this document with this immutable address version.
        row.document_status = "NEEDS_REVIEW"
        row.completed_at = None
        await self.db.commit()
        return await self.state(owner)

    async def review_queue(self, reviewer):
        self.require_enabled()
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
        self.require_enabled()
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
        self.require_enabled()
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
        TargetCipher(self.settings).decrypt(row.target_encrypted, row.target_key_id, owner, row.id)
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
            target = TargetCipher(self.settings).decrypt(
                row.target_encrypted, row.target_key_id, owner, row.id
            )["position"]
            outcome = evaluate_location(
                payload.samples,
                (target[1], target[0]),
                session.started_at,
                now,
                row.geocode_metadata["quality"],
                LocationPolicy(
                    precise_radius_m=self.settings.permanent_address_radius_m,
                    approximate_radius_m=self.settings.permanent_address_approximate_radius_m,
                ),
            )
            session.result, session.derived_evidence = outcome.result, asdict(outcome)
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
