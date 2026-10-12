"""Reference trust chain. Never writes employment status, verification outcome, or score."""

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from app.auth.tokens import hash_refresh_token
from app.config import get_settings
from app.exceptions import (
    ConflictError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationAppError,
)
from app.integrations.email.providers import get_email_provider
from app.models.email_delivery_log import EmailDeliveryLog
from app.models.employer_verification_request import EmployerVerificationRequest
from app.models.employment import Employment
from app.models.employment_reference import EmploymentReference as Reference
from app.models.employment_reference import EmploymentReferenceEvent as Event
from app.models.employment_reference import EmploymentReferenceInvitation as Invitation
from app.schemas.email_delivery import RenderedEmailMessage
from app.schemas.employment_reference import (
    CandidateReferences,
    HRReference,
    ManagerSummary,
    ReferenceSummary,
)
from app.services.private_owner_guard import lock_private_owner

HR = "hr_reference"
MANAGER = "reporting_manager_reference"
CONFIRMED = {"confirmed_reporting_manager", "left_organization"}
CONTACT_APPROVED = {"hr_confirmed", "hr_corrected", "hr_supplied"}


class ReferenceGateError(ConflictError):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class EmploymentReferenceService:
    def __init__(self, session, settings=None):
        self.db = session
        self.settings = settings or get_settings()
        self.provider = None

    @staticmethod
    def factual_binding(req, employment):
        """Bind approval to the factual cycle and claim, not a reusable outreach row ID."""
        facts = {
            key: str(getattr(employment, key))
            for key in (
                "subject_full_name",
                "subject_email",
                "employer_legal_name",
                "employer_trade_name",
                "job_title",
                "employment_type",
                "start_date",
                "end_date",
                "work_location_city",
                "work_location_region",
                "work_location_country",
                "work_arrangement",
            )
        }
        facts.update(
            {
                "hr_request_id": str(req.id),
                "verification_request_id": str(req.verification_request_id),
                "sent_at": req.sent_at.astimezone(UTC).isoformat(),
                "responded_at": req.responded_at.astimezone(UTC).isoformat()
                if req.responded_at
                else None,
                "verifier_email": req.verifier_email.casefold(),
            }
        )
        return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()

    def approval_current(self, row, req, employment):
        return bool(
            req
            and not req.revoked_at
            and req.response == "confirmed"
            and row.validation.get("factual_binding") == self.factual_binding(req, employment)
        )

    async def invalidate_factual_cycle(self, employment_id, *, reset_hr=True):
        """Keep old manager history but create a fresh, unapproved current nomination."""
        await self.employment(employment_id)
        row = await self.active(employment_id)
        if row and row.validated_at:
            row.active = False
            row.superseded_at = datetime.now(UTC)
            await self.revoke_tokens(row)
            self.event(row, "factual_cycle_invalidated", "system")
            await self.db.flush()
            fresh = Reference(
                employment_id=employment_id,
                kind=MANAGER,
                status="awaiting_hr_validation",
                nomination=dict(row.nomination),
                nominated_at=row.nominated_at,
            )
            self.db.add(fresh)
            await self.db.flush()
            self.event(fresh, "factual_revalidation_required", "system")
        hr = await self.active(employment_id, HR) if reset_hr else None
        if hr:
            hr.status = "pending"
            hr.completed_at = None
        await self.db.flush()

    async def employment(self, employment_id, owner=None):
        row = await self.db.get(Employment, employment_id)
        if row is None or (owner is not None and row.created_by_user_id != owner):
            raise NotFoundError("Employment not found")
        user = await lock_private_owner(self.db, row.created_by_user_id)
        row = await self.db.scalar(
            select(Employment)
            .where(Employment.id == employment_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or row.deleted_at is not None:
            raise NotFoundError("Employment not found")
        return row, user

    async def active(self, employment_id, kind=MANAGER):
        return await self.db.scalar(
            select(Reference)
            .where(
                Reference.employment_id == employment_id,
                Reference.kind == kind,
                Reference.active.is_(True),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def invitation(self, reference_id):
        return await self.db.scalar(
            select(Invitation)
            .where(Invitation.reference_id == reference_id)
            .order_by(Invitation.created_at.desc(), Invitation.id.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )

    def event(self, row, name, actor):
        self.db.add(Event(reference_id=row.id, event=name, actor=actor))

    async def revoke_tokens(self, row):
        await self.db.execute(
            update(Invitation)
            .where(Invitation.reference_id == row.id, Invitation.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )

    @staticmethod
    def distinct_contact(contact, employment, user, hr=None):
        email = (contact.get("work_email") or "").casefold()
        name = " ".join(contact["full_name"].casefold().split())
        prohibited_emails = {
            str(value).casefold()
            for value in (user.email, employment.subject_email, getattr(hr, "verifier_email", None))
            if value
        }
        prohibited_names = {
            " ".join(value.casefold().split())
            for value in (employment.subject_full_name, getattr(hr, "contact_name", None))
            if value
        }
        if (
            (email and email in prohibited_emails)
            or name in prohibited_names
            or (contact.get("phone") and contact["phone"] == user.phone)
        ):
            raise ValidationAppError(
                "Choose a separate reporting manager, not the candidate or HR verifier",
                code="reference_identity_conflict",
            )

    async def nominate(self, owner, employment_id, payload, *, replace=False):
        employment, user = await self.employment(employment_id, owner)
        contact = payload.model_dump(mode="json")
        self.distinct_contact(contact, employment, user)
        row = await self.active(employment_id)
        if row and row.nomination == contact and not replace:
            return await self.summary(owner, employment_id)
        if row and row.validated_at and not replace:
            raise ValidationAppError(
                "Request a manager change to require fresh HR validation",
                code="manager_nomination_locked",
            )
        if row:
            row.active = False
            row.superseded_at = datetime.now(UTC)
            await self.revoke_tokens(row)
            self.event(row, "nomination_superseded", "candidate")
            await self.db.flush()
        row = Reference(
            employment_id=employment_id,
            kind=MANAGER,
            status="awaiting_hr_validation",
            nomination=contact,
            nominated_at=datetime.now(UTC),
        )
        self.db.add(row)
        await self.db.flush()
        self.event(row, "manager_nominated", "candidate")
        await self.db.commit()
        return await self.summary(owner, employment_id)

    async def summary(self, owner, employment_id):
        employment, _ = await self.employment(employment_id, owner)
        hr = await self.active(employment_id, HR)
        manager = await self.active(employment_id)
        request = await self.db.scalar(
            select(EmployerVerificationRequest)
            .where(EmployerVerificationRequest.employment_id == employment_id)
            .execution_options(populate_existing=True)
        )
        safe = ManagerSummary(status="not_started")
        if manager:
            invitation = await self.invitation(manager.id)
            current = self.approval_current(manager, request, employment)
            approved = current and manager.validation.get("relationship_decision") in CONFIRMED
            state = manager.status
            if manager.validated_at and not current:
                state = "needs_review"
            if (
                invitation
                and not invitation.revoked_at
                and invitation.expires_at <= datetime.now(UTC)
                and state in {"invitation_sent", "opened"}
            ):
                state = "expired"
            blocked = None
            if not approved or manager.validation.get("contact_provenance") not in CONTACT_APPROVED:
                blocked = "awaiting_hr_validation"
            elif not manager.validation.get("contact", {}).get("work_email"):
                blocked = "email_required"
            elif employment.verification_status != "verified":
                blocked = "employment_not_verified"
            safe = ManagerSummary(
                status=state,
                nomination_id=manager.id,
                identity_withheld=approved
                and any(
                    manager.validation.get("contact", {}).get(key, manager.nomination.get(key))
                    != manager.nomination.get(key)
                    for key in ("full_name", "designation")
                ),
                full_name=manager.nomination.get("full_name"),
                designation=manager.nomination.get("designation"),
                relationship="former_reporting_manager"
                if manager.validation.get("relationship_decision") == "left_organization"
                else "reporting_manager",
                relationship_confirmed_by_hr=approved,
                nomination_locked=manager.validated_at is not None,
                nominated_at=manager.nominated_at,
                validated_at=manager.validated_at,
                completed_at=manager.completed_at,
                invitation_sent_at=invitation.sent_at if invitation else None,
                invitation_expires_at=invitation.expires_at if invitation else None,
                invitation_blocked_reason=blocked,
            )
            if safe.identity_withheld:
                safe.full_name = None
                safe.designation = None
            if not current:
                safe.completed_at = None
        hr_safe = ReferenceSummary(
            status=hr.status
            if hr and self.approval_current(hr, request, employment)
            else "pending",
            completed_at=hr.completed_at
            if hr and self.approval_current(hr, request, employment)
            else None,
        )
        return CandidateReferences(
            employment_id=employment_id,
            completed_count=int(hr_safe.status == "completed") + int(safe.status == "completed"),
            hr_reference=hr_safe,
            reporting_manager=safe,
        )

    async def record_hr(self, req, hr_payload=None, manager_payload=None):
        """Called in the existing employer response transaction, before its commit."""
        employment, user = await self.employment(req.employment_id)
        row = await self.active(employment.id, HR)
        if row is None:
            row = Reference(employment_id=employment.id, kind=HR, status="pending")
            self.db.add(row)
            await self.db.flush()
        payload = hr_payload or HRReference()
        row.status = payload.status
        row.hr_request_id = req.id
        row.answers = payload.model_dump(mode="json")
        row.validation = {"factual_binding": self.factual_binding(req, employment)}
        row.completed_at = datetime.now(UTC) if payload.status == "completed" else None
        self.event(row, "hr_reference_" + payload.status, "employer_link")
        if manager_payload:
            await self.validate_manager(req, manager_payload, employment=employment, user=user)

    async def validate_manager(self, req, payload, *, employment=None, user=None):
        if employment is None:
            employment, user = await self.employment(req.employment_id)
        if req.response != "confirmed":
            raise ValidationAppError(
                "HR must first confirm employment facts", code="hr_confirmation_required"
            )
        row = await self.active(employment.id)
        if row is None or row.id != payload.nomination_id:
            raise ConflictError("Manager nomination changed; reload before validating")
        if row.validated_at is not None:
            if self.approval_current(row, req, employment):
                raise ConflictError(
                    "This nomination has already been reviewed; request a new nomination"
                )
            await self.invalidate_factual_cycle(employment.id, reset_hr=False)
            row = await self.active(employment.id)
        contact = (
            row.nomination
            if payload.contact_provenance == "hr_confirmed"
            else payload.confirmed_contact.model_dump(mode="json")
            if payload.confirmed_contact
            else {}
        )
        if payload.relationship_decision in CONFIRMED and contact:
            self.distinct_contact(contact, employment, user, req)
        row.validation = {
            "factual_binding": self.factual_binding(req, employment),
            "relationship_decision": payload.relationship_decision,
            "contact_provenance": payload.contact_provenance,
            "contact": contact,
        }
        row.hr_request_id = req.id
        row.validated_at = datetime.now(UTC)
        row.status = (
            "ready_to_invite"
            if payload.relationship_decision in CONFIRMED
            and payload.contact_provenance in CONTACT_APPROVED
            and contact.get("work_email")
            else "needs_review"
        )
        self.event(row, "manager_" + payload.relationship_decision, "employer_link")
        await self.db.flush()

    async def hr_context(self, employment_id):
        employment, _ = await self.employment(employment_id)
        row = await self.active(employment_id)
        req = await self.db.scalar(
            select(EmployerVerificationRequest)
            .where(EmployerVerificationRequest.employment_id == employment_id)
            .execution_options(populate_existing=True)
        )
        stale = bool(row and row.validated_at and not self.approval_current(row, req, employment))
        return (
            None
            if row is None
            else {
                "nomination_id": row.id,
                "candidate_provided": row.nomination,
                "status": "needs_review" if stale else row.status,
                "revalidation_required": stale,
                "validation": {
                    key: row.validation[key]
                    for key in ("relationship_decision", "contact_provenance", "contact")
                    if key in row.validation and not stale
                },
                "validated_at": row.validated_at,
            }
        )

    async def send(self, employment_id, payload):
        if not self.settings.manager_reference_public_base_url:
            raise ServiceUnavailableError("Reference delivery is not configured")
        employment, user = await self.employment(employment_id)
        row = await self.active(employment_id)
        if row is None or row.id != payload.nomination_id:
            raise ConflictError("Manager nomination changed; reload before sending")
        hr = (
            await self.db.get(EmployerVerificationRequest, row.hr_request_id)
            if row.hr_request_id
            else None
        )
        if (
            not self.approval_current(row, hr, employment)
            or row.validation.get("relationship_decision") not in CONFIRMED
            or row.validation.get("contact_provenance") not in CONTACT_APPROVED
        ):
            raise ReferenceGateError(
                "Employer validation is required before invitation", "hr_validation_required"
            )
        if employment.verification_status != "verified":
            raise ReferenceGateError(
                "Employment is awaiting final verification", "employment_not_verified"
            )
        contact = row.validation.get("contact", {})
        if not contact.get("work_email"):
            raise ValidationAppError(
                "An employer-confirmed email is required", code="reference_email_required"
            )
        self.distinct_contact(contact, employment, user, hr)
        existing = await self.db.scalar(
            select(Invitation).where(
                Invitation.reference_id == row.id,
                Invitation.idempotency_key == payload.idempotency_key,
            )
        )
        if existing:
            return self.send_result(existing, True)
        if row.status in {"completed", "declined", "needs_review"}:
            raise ConflictError("This reference cannot be invited in its current state")
        now = datetime.now(UTC)
        last = await self.invitation(row.id)
        count = await self.db.scalar(
            select(func.count())
            .select_from(Invitation)
            .join(Reference)
            .where(
                Reference.employment_id == employment_id,
                Invitation.created_at > now - timedelta(days=1),
            )
        )
        if count >= 3 or (last and last.created_at > now - timedelta(minutes=15)):
            raise RateLimitError(
                "Please wait before sending another reference request", retry_after_seconds=900
            )
        await self.revoke_tokens(row)
        await self.db.flush()
        raw = secrets.token_urlsafe(32)
        invitation = Invitation(
            reference_id=row.id,
            idempotency_key=payload.idempotency_key,
            token_hash=hash_refresh_token(raw),
            expires_at=now + timedelta(hours=self.settings.employer_verification_token_ttl_hours),
            delivery_status="pending",
        )
        self.db.add(invitation)
        await self.db.flush()
        self.event(row, "invitation_reserved", "authorized_sender")
        # Durable reservation before external delivery: retries with this key never resend,
        # even if the process dies after the provider accepts the message.
        await self.db.commit()
        employment, user = await self.employment(employment_id)
        row = await self.active(employment_id)
        await self.db.refresh(invitation, with_for_update=True)
        if row is None or row.id != invitation.reference_id or invitation.revoked_at:
            raise ConflictError("Manager nomination changed before delivery")
        hr = await self.db.scalar(
            select(EmployerVerificationRequest)
            .where(EmployerVerificationRequest.id == row.hr_request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            employment.verification_status != "verified"
            or not self.approval_current(row, hr, employment)
            or row.validation.get("relationship_decision") not in CONFIRMED
            or row.validation.get("contact_provenance") not in CONTACT_APPROVED
        ):
            invitation.revoked_at = datetime.now(UTC)
            invitation.delivery_status = "cancelled"
            await self.db.commit()
            raise ReferenceGateError(
                "Reference approval changed before delivery", "hr_validation_required"
            )
        contact = row.validation.get("contact", {})
        self.distinct_contact(contact, employment, user, hr)
        link = (
            f"{self.settings.manager_reference_public_base_url}"
            f"{self.settings.api_v1_prefix.rstrip('/')}/public/manager-references/{raw}/page"
        )
        message = RenderedEmailMessage(
            template_key="employment_manager_reference",
            template_version="v1",
            to_email=contact["work_email"],
            subject="KairoID: reporting manager reference request",
            text_body=(
                f"Hello {contact['full_name']},\n\nPlease provide a short professional reference "
                f"for {employment.subject_full_name} at {employment.employer_legal_name}. "
                "The employer confirmed your reporting relationship. No account is required."
                f"\n\n{link}\n\nThis confidential link expires in "
                f"{self.settings.employer_verification_token_ttl_hours} hours. "
                "You may decline on the page."
            ),
            audit_payload={"employment_id": str(employment.id)},
        )
        provider = self.provider or get_email_provider(
            self.settings.model_copy(update={"email_dev_log_secrets": False})
        )
        delivery = "unknown"
        try:
            result = await provider.send(message)
            delivery = (
                result.status if result.status in {"sent", "failed", "skipped"} else "unknown"
            )
        except Exception:
            # An ambiguous provider failure must not prompt an automatic duplicate send.
            delivery = "unknown"
        invitation.delivery_status = delivery
        if delivery == "sent":
            invitation.sent_at = datetime.now(UTC)
            row.status = "invitation_sent"
        else:
            invitation.revoked_at = datetime.now(UTC)
            row.status = "ready_to_invite"
        self.db.add(
            EmailDeliveryLog(
                template_key=message.template_key,
                template_version="v1",
                recipient_email=contact["work_email"],
                provider=getattr(provider, "provider_name", self.settings.email_backend),
                status="sent" if delivery == "sent" else "failed",
                subject=message.subject,
                payload=message.audit_payload,
                attempt_count=1,
                sent_at=invitation.sent_at,
            )
        )
        self.event(row, "invitation_delivery_" + delivery, "system")
        await self.db.commit()
        return self.send_result(invitation, False)

    @staticmethod
    def send_result(invitation, idempotent):
        return {
            "delivery_status": invitation.delivery_status,
            "sent_at": invitation.sent_at,
            "expires_at": invitation.expires_at,
            "idempotent": idempotent,
        }

    async def token(self, raw):
        if not raw or not 32 <= len(raw) <= 128:
            raise NotFoundError("Reference link unavailable")
        invitation = await self.db.scalar(
            select(Invitation).where(Invitation.token_hash == hash_refresh_token(raw))
        )
        row = await self.db.get(Reference, invitation.reference_id) if invitation else None
        if row is None:
            raise NotFoundError("Reference link unavailable")
        employment, _ = await self.employment(row.employment_id)
        await self.db.refresh(row, with_for_update=True)
        await self.db.refresh(invitation, with_for_update=True)
        hr = (
            await self.db.get(EmployerVerificationRequest, row.hr_request_id)
            if row.hr_request_id
            else None
        )
        if hr:
            await self.db.refresh(hr)
        if (
            not row.active
            or row.kind != MANAGER
            or invitation.revoked_at
            or invitation.expires_at <= datetime.now(UTC)
            or invitation.delivery_status != "sent"
            or not self.approval_current(row, hr, employment)
            or employment.verification_status != "verified"
        ):
            raise NotFoundError("Reference link unavailable")
        return invitation, row, employment

    async def context(self, raw):
        invitation, row, employment = await self.token(raw)
        if invitation.opened_at is None:
            invitation.opened_at = datetime.now(UTC)
            if row.status == "invitation_sent":
                row.status = "opened"
            self.event(row, "invitation_opened", "manager_link")
            await self.db.commit()
        return {
            "status": row.status,
            "candidate_name": employment.subject_full_name,
            "employer_name": employment.employer_legal_name,
            "job_title": employment.job_title,
            "start_date": employment.start_date,
            "end_date": employment.end_date,
            "expires_at": invitation.expires_at,
        }

    async def respond(self, raw, payload=None, *, decline=False):
        invitation, row, _ = await self.token(raw)
        answers = {"declined": True} if decline else payload.model_dump(mode="json")
        answers["result"] = (
            "declined"
            if decline
            else "relationship_confirmed"
            if payload.directly_managed == "yes"
            else "relationship_not_confirmed"
        )
        if invitation.responded_at:
            if row.answers == answers:
                return {"status": row.status, "idempotent": True}
            raise ConflictError("This reference has already been submitted")
        row.answers = answers
        row.status = (
            "declined"
            if decline
            else "completed"
            if payload.directly_managed == "yes"
            else "needs_review"
        )
        now = datetime.now(UTC)
        invitation.responded_at = now
        row.completed_at = now if row.status == "completed" else None
        self.event(
            row,
            "relationship_not_confirmed"
            if row.status == "needs_review"
            else "reference_" + row.status,
            "manager_link",
        )
        await self.db.commit()
        return {"status": row.status, "idempotent": False}

    async def revoke(self, employment_id, nomination_id):
        await self.employment(employment_id)
        row = await self.active(employment_id)
        if row is None or row.id != nomination_id:
            raise NotFoundError("Reference not found")
        await self.revoke_tokens(row)
        if row.status in {"invitation_sent", "opened"}:
            row.status = "ready_to_invite"
        self.event(row, "invitation_revoked", "internal_reviewer")
        await self.db.commit()
        return {"revoked": True}

    async def report(self, employment_id):
        """Internal permission-gated report: no referee email or phone, even here."""
        summary = await self.summary(None, employment_id)
        rows = (
            await self.db.scalars(
                select(Reference).where(
                    Reference.employment_id == employment_id, Reference.active.is_(True)
                )
            )
        ).all()
        references = []
        for row in rows:
            invitation = await self.invitation(row.id)
            req = (
                await self.db.get(EmployerVerificationRequest, row.hr_request_id)
                if row.hr_request_id
                else None
            )
            employment = await self.db.get(Employment, employment_id)
            current = self.approval_current(row, req, employment)
            references.append(
                {
                    "kind": row.kind,
                    "status": summary.hr_reference.status
                    if row.kind == HR
                    else summary.reporting_manager.status,
                    "answers": row.answers if current else {},
                    "revalidation_required": not current,
                    "relationship_decision": row.validation.get("relationship_decision"),
                    "contact_provenance": row.validation.get("contact_provenance"),
                    "validated_at": row.validated_at,
                    "completed_at": row.completed_at,
                    "invitation": None
                    if invitation is None
                    else {
                        "delivery_status": invitation.delivery_status,
                        "sent_at": invitation.sent_at,
                        "opened_at": invitation.opened_at,
                        "expires_at": invitation.expires_at,
                        "revoked_at": invitation.revoked_at,
                        "responded_at": invitation.responded_at,
                    },
                }
            )
        return {"summary": summary, "references": references}

    async def renew_hr_link(self, employment_id, payload):
        """Renew the same employer capability without resetting its factual decision."""
        employment, _ = await self.employment(employment_id)
        row = await self.active(employment_id)
        if row is None or row.id != payload.nomination_id or row.validated_at:
            raise ConflictError("A current nomination awaiting HR validation is required")
        hr = await self.db.scalar(
            select(EmployerVerificationRequest)
            .where(EmployerVerificationRequest.employment_id == employment_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not hr or hr.response != "confirmed" or hr.revoked_at:
            raise ConflictError("An existing confirmed employer verification is required")
        renewals = row.validation.get("renewals", [])
        existing = next(
            (item for item in renewals if item["key"] == str(payload.idempotency_key)), None
        )
        if existing:
            return {"delivery_status": existing["status"], "idempotent": True}
        now = datetime.now(UTC)
        events = (
            await self.db.scalars(
                select(Event)
                .join(Reference)
                .where(
                    Reference.employment_id == employment_id,
                    Event.event == "hr_link_renewal_reserved",
                    Event.created_at > now - timedelta(days=1),
                )
            )
        ).all()
        if len(events) >= 3 or any(
            item.created_at > now - timedelta(minutes=15) for item in events
        ):
            raise RateLimitError(
                "Please wait before renewing the employer link", retry_after_seconds=900
            )
        reservation = {"key": str(payload.idempotency_key), "status": "pending"}
        row.validation = {**row.validation, "renewals": [*renewals, reservation]}
        self.event(row, "hr_link_renewal_reserved", "internal_reviewer")
        await self.db.commit()
        employment, _ = await self.employment(employment_id)
        row = await self.active(employment_id)
        if row is None or row.id != payload.nomination_id or row.validated_at:
            raise ConflictError("Nomination changed before employer-link renewal")
        await self.db.refresh(hr, with_for_update=True)
        if hr.revoked_at or hr.response != "confirmed":
            raise ConflictError("Employer capability is no longer eligible for renewal")
        raw = secrets.token_urlsafe(32)
        hr.token_hash = hash_refresh_token(raw)
        hr.expires_at = datetime.now(UTC) + timedelta(
            hours=self.settings.employer_verification_token_ttl_hours
        )
        base = (self.settings.employer_portal_base_url or self.settings.app_public_base_url).rstrip(
            "/"
        )
        message = RenderedEmailMessage(
            template_key="employment_reference_hr_revalidation",
            template_version="v1",
            to_email=hr.verifier_email,
            subject="KairoID: reporting manager confirmation requested",
            text_body=(
                f"Hello {hr.contact_name},\n\nPlease review the newly nominated reporting manager "
                f"for {employment.subject_full_name} at {employment.employer_legal_name} "
                "in your existing employer verification workspace. "
                "Your prior factual employment response is unchanged.\n\n"
                f"{base}/employer-verification/{raw}\n"
            ),
            audit_payload={"employment_id": str(employment_id)},
        )
        provider = self.provider or get_email_provider(
            self.settings.model_copy(update={"email_dev_log_secrets": False})
        )
        delivery = "unknown"
        try:
            result = await provider.send(message)
            delivery = (
                result.status if result.status in {"sent", "failed", "skipped"} else "unknown"
            )
        except Exception:
            pass
        if delivery != "sent":
            hr.expires_at = datetime.now(UTC)
        row.validation = {
            **row.validation,
            "renewals": [
                {**item, "status": delivery} if item["key"] == reservation["key"] else item
                for item in row.validation["renewals"]
            ],
        }
        self.db.add(
            EmailDeliveryLog(
                template_key=message.template_key,
                template_version="v1",
                recipient_email=hr.verifier_email,
                provider=getattr(provider, "provider_name", self.settings.email_backend),
                status="sent" if delivery == "sent" else "failed",
                subject=message.subject,
                payload=message.audit_payload,
                attempt_count=1,
            )
        )
        self.event(row, "hr_link_renewal_" + delivery, "system")
        await self.db.commit()
        return {"delivery_status": delivery, "idempotent": False}
