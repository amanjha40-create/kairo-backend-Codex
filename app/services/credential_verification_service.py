"""Generic credential confirmation — magic-link email and public verifier responses.

Polymorphic over internship / freelance-contract subjects. Mirrors the employer
confirmation flow but without documents or the employment state machine.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import hash_refresh_token
from app.config import Settings, get_settings
from app.employment.enums import CredentialSubjectType, EmployerVerificationDecision
from app.exceptions import NotFoundError
from app.integrations.email.employer_verification_pages import render_result_page, render_review_page
from app.integrations.email.sender import get_email_sender
from app.models.credential_verification_request import CredentialVerificationRequest
from app.models.freelance_contract import FreelanceContract
from app.models.freelance_contract_document import FreelanceContractDocument
from app.models.internship import Internship
from app.models.internship_document import InternshipDocument
from app.models.user import User
from app.repositories.credential_verification import CredentialVerificationRepository
from app.repositories.freelance_contract import FreelanceContractRepository
from app.repositories.internship import InternshipRepository
from app.schemas.credential_verification import (
    CredentialVerificationRequestBody,
    CredentialVerificationRequestResponse,
)

logger = logging.getLogger(__name__)

# Per-credential verification status strings (these tables don't use the
# employment state machine — plain strings the frontend maps to chips).
_STATUS_VERIFIED = "verified"
_STATUS_REJECTED = "rejected"
_STATUS_ON_HOLD = "on_hold"


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    if len(local) <= 1:
        masked_local = "*"
    elif len(local) == 2:
        masked_local = f"{local[0]}*"
    else:
        masked_local = f"{local[0]}***{local[-1]}"
    return f"{masked_local}@{domain}"


def _normalize_verifier_email(email: str) -> str:
    return email.strip().lower()


@dataclass
class _SubjectView:
    """Normalized display fields for any verifiable credential subject."""

    primary_name: str          # company / client
    secondary_name: str        # role / project
    start_date: str
    end_date: str | None
    headline: str
    intro_noun: str
    details_title: str
    primary_label: str         # "Company" / "Client"
    secondary_label: str       # "Role" / "Project"


class CredentialVerificationService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._requests = CredentialVerificationRepository(session)
        self._internships = InternshipRepository(session)
        self._freelance = FreelanceContractRepository(session)
        self._email = get_email_sender(self._settings)

    def _review_link(self, token: str) -> str:
        base = self._settings.app_public_base_url.rstrip("/")
        prefix = self._settings.api_v1_prefix.rstrip("/")
        return f"{base}{prefix}/public/credential-verification/{token}"

    async def _load_subject(self, subject_type: str, subject_id: UUID, user_id: UUID | None):
        """Return the owned subject row, or None. Pass user_id=None for public (token) loads."""
        if subject_type == CredentialSubjectType.INTERNSHIP.value:
            if user_id is not None:
                return await self._internships.get_owned(subject_id, user_id)
            return (await self._session.execute(
                select(Internship).where(Internship.id == subject_id, Internship.deleted_at.is_(None))
            )).scalar_one_or_none()
        if subject_type == CredentialSubjectType.FREELANCE_CONTRACT.value:
            if user_id is not None:
                return await self._freelance.get_owned(subject_id, user_id)
            return (await self._session.execute(
                select(FreelanceContract).where(
                    FreelanceContract.id == subject_id, FreelanceContract.deleted_at.is_(None)
                )
            )).scalar_one_or_none()
        return None

    def _view(self, subject_type: str, subject, subject_full_name: str) -> _SubjectView:
        if subject_type == CredentialSubjectType.INTERNSHIP.value:
            return _SubjectView(
                primary_name=subject.company_name,
                secondary_name=subject.role,
                start_date=str(subject.start_date),
                end_date=None if subject.is_ongoing else (str(subject.end_date) if subject.end_date else None),
                headline="Internship Verification",
                intro_noun="internship",
                details_title="Internship Details",
                primary_label="Company",
                secondary_label="Role",
            )
        return _SubjectView(
            primary_name=subject.client_name,
            secondary_name=subject.project_title,
            start_date=str(subject.start_date),
            end_date=None if subject.is_ongoing else (str(subject.end_date) if subject.end_date else None),
            headline="Engagement Verification",
            intro_noun="freelance engagement",
            details_title="Engagement Details",
            primary_label="Client",
            secondary_label="Project",
        )

    async def _user_full_name(self, user_id: UUID) -> str:
        user = (await self._session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:
            return "A Kairo user"
        return user.full_name or user.email

    async def request_verification(
        self,
        user_id: UUID,
        subject_type: str,
        subject_id: UUID,
        payload: CredentialVerificationRequestBody,
    ) -> CredentialVerificationRequestResponse:
        subject = await self._load_subject(subject_type, subject_id, user_id)
        if subject is None:
            raise NotFoundError("Record not found")

        subject_full_name = await self._user_full_name(user_id)
        view = self._view(subject_type, subject, subject_full_name)

        verifier_email = _normalize_verifier_email(str(payload.verifier_email))
        now = datetime.now(tz=UTC)
        ttl = timedelta(hours=self._settings.employer_verification_token_ttl_hours)
        raw_token = secrets.token_urlsafe(32)
        token_hash = hash_refresh_token(raw_token)

        existing = await self._requests.get_by_subject(subject_type, subject_id)
        if existing is None:
            req = CredentialVerificationRequest(
                subject_type=subject_type,
                subject_id=subject_id,
                contact_name=payload.contact_name,
                verifier_email=verifier_email,
                relationship_to_subject=payload.relationship,
                token_hash=token_hash,
                expires_at=now + ttl,
                sent_at=now,
                responded_at=None,
                response=EmployerVerificationDecision.PENDING.value,
            )
            await self._requests.create(req)
        else:
            existing.contact_name = payload.contact_name
            existing.verifier_email = verifier_email
            existing.relationship_to_subject = payload.relationship
            existing.token_hash = token_hash
            existing.expires_at = now + ttl
            existing.sent_at = now
            existing.responded_at = None
            existing.response = EmployerVerificationDecision.PENDING.value
            existing.remarks = None
            await self._requests.update(existing)

        await self._email.send_employer_verification(
            to_email=verifier_email,
            contact_name=payload.contact_name,
            subject_full_name=subject_full_name,
            employer_name=view.primary_name,
            job_title=view.secondary_name,
            relationship=payload.relationship,
            review_url=self._review_link(raw_token),
            ttl_hours=self._settings.employer_verification_token_ttl_hours,
        )

        await self._session.commit()
        logger.info(
            "credential_verification.requested",
            extra={
                "subject_type": subject_type,
                "subject_id": str(subject_id),
                "verifier_email_domain": verifier_email.split("@")[-1],
            },
        )
        return CredentialVerificationRequestResponse(
            subject_id=subject_id,
            verifier_email_masked=mask_email(verifier_email),
            expires_at=now + ttl,
        )

    async def _load_by_token(self, raw_token: str) -> CredentialVerificationRequest:
        if not raw_token or len(raw_token) < 16:
            raise NotFoundError("This verification link is invalid or has expired")
        req = await self._requests.get_by_token_hash(hash_refresh_token(raw_token))
        if req is None:
            raise NotFoundError("This verification link is invalid or has expired")
        return req

    async def render_review_page(self, raw_token: str) -> str:
        req = await self._load_by_token(raw_token)
        subject = await self._load_subject(req.subject_type, req.subject_id, None)
        if subject is None:
            raise NotFoundError("This verification link is invalid or has expired")
        subject_full_name = await self._user_full_name(subject.user_id)
        view = self._view(req.subject_type, subject, subject_full_name)

        already = req.response != EmployerVerificationDecision.PENDING.value
        return render_review_page(
            contact_name=req.contact_name,
            subject_full_name=subject_full_name,
            subject_email=None,
            employer_name=view.primary_name,
            job_title=view.secondary_name,
            start_date=view.start_date,
            end_date=view.end_date,
            relationship=req.relationship_to_subject,
            documents=[],
            token=raw_token,
            base_url=self._settings.app_public_base_url,
            already_responded=already,
            existing_response=req.response,
            verification_kind="credential-verification",
            headline=view.headline,
            intro_noun=view.intro_noun,
            details_title=view.details_title,
            primary_label=view.primary_label,
            secondary_label=view.secondary_label,
        )

    async def respond_with_action(self, raw_token: str, action: str, remarks: str | None) -> str:
        try:
            decision = EmployerVerificationDecision(action)
        except ValueError:
            return render_result_page(
                title="Invalid action",
                message="The action you submitted is not recognised. Please use the form buttons.",
                success=False,
            )
        if decision == EmployerVerificationDecision.PENDING:
            return render_result_page(title="Invalid action", message="Unknown response type.", success=False)

        req = await self._load_by_token(raw_token)
        subject = await self._load_subject(req.subject_type, req.subject_id, None)
        if subject is None:
            raise NotFoundError("This verification link is invalid or has expired")
        now = datetime.now(tz=UTC)

        if req.response != EmployerVerificationDecision.PENDING.value:
            label = {"confirmed": "Approved", "declined": "Declined", "on_hold": "On Hold"}.get(
                req.response, "responded"
            )
            return render_result_page(
                title="Already responded",
                message=f"Your response ({label}) has already been recorded. No further action needed.",
                success=True,
            )

        if now > req.expires_at:
            raise NotFoundError("This verification link has expired")

        req.response = decision.value
        req.responded_at = now
        req.remarks = remarks or None

        if decision == EmployerVerificationDecision.CONFIRMED:
            subject.verification_status = _STATUS_VERIFIED
            subject.verifier_remarks = None
            title, message = "Verified", "Thank you. This credential has been confirmed."
            if req.subject_type == CredentialSubjectType.INTERNSHIP.value:
                await self._session.execute(
                    sa_update(InternshipDocument)
                    .where(InternshipDocument.internship_id == req.subject_id)
                    .values(verification_status="approved")
                )
            elif req.subject_type == CredentialSubjectType.FREELANCE_CONTRACT.value:
                await self._session.execute(
                    sa_update(FreelanceContractDocument)
                    .where(FreelanceContractDocument.freelance_contract_id == req.subject_id)
                    .values(verification_status="approved")
                )
        elif decision == EmployerVerificationDecision.ON_HOLD:
            subject.verification_status = _STATUS_ON_HOLD
            subject.verifier_remarks = remarks or None
            title, message = "Placed on hold", "Your response has been recorded. The applicant will be notified."
            if req.subject_type == CredentialSubjectType.INTERNSHIP.value:
                await self._session.execute(
                    sa_update(InternshipDocument)
                    .where(InternshipDocument.internship_id == req.subject_id)
                    .values(verification_status="on_hold")
                )
            elif req.subject_type == CredentialSubjectType.FREELANCE_CONTRACT.value:
                await self._session.execute(
                    sa_update(FreelanceContractDocument)
                    .where(FreelanceContractDocument.freelance_contract_id == req.subject_id)
                    .values(verification_status="on_hold")
                )
        else:
            subject.verification_status = _STATUS_REJECTED
            subject.verifier_remarks = remarks or None
            title, message = (
                "Response recorded",
                "You indicated this could not be confirmed as described. The applicant has been notified.",
            )
            if req.subject_type == CredentialSubjectType.INTERNSHIP.value:
                await self._session.execute(
                    sa_update(InternshipDocument)
                    .where(InternshipDocument.internship_id == req.subject_id)
                    .values(verification_status="rejected")
                )
            elif req.subject_type == CredentialSubjectType.FREELANCE_CONTRACT.value:
                await self._session.execute(
                    sa_update(FreelanceContractDocument)
                    .where(FreelanceContractDocument.freelance_contract_id == req.subject_id)
                    .values(verification_status="rejected")
                )

        await self._session.commit()
        logger.info(
            f"credential_verification.{decision.value}",
            extra={"subject_type": req.subject_type, "subject_id": str(req.subject_id)},
        )
        return render_result_page(title=title, message=message, success=True)
