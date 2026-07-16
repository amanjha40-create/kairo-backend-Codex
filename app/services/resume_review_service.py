from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.employment.enums import EmploymentType, VerificationMethod, VerificationStatus
from app.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.certification import Certification
from app.models.education import Education
from app.models.employment import Employment
from app.models.freelance_contract import FreelanceContract
from app.models.gig_platform import GigPlatform
from app.models.internship import Internship
from app.models.portfolio import PortfolioItem
from app.models.resume_document import ResumeDocument
from app.models.resume_import_batch import ResumeImportBatch
from app.models.resume_import_result import ResumeImportResult
from app.models.resume_parsed_result import ResumeParsedResult
from app.models.resume_processing_job import ResumeProcessingJob
from app.models.resume_record_provenance import ResumeRecordProvenance
from app.models.resume_review_item import ResumeReviewItem
from app.models.resume_review_session import ResumeReviewSession
from app.models.user import User
from app.models.verification_request import VerificationRequest
from app.resumes.normalization import payload_hash, stable_claim_id
from app.resumes.review_enums import ResumeImportAction, ResumeReviewStatus
from app.resumes.review_schemas import (
    ImportBatchResponse,
    ImportResultResponse,
    ReviewImportRequest,
    ReviewItemResponse,
    ReviewItemUpdateRequest,
    ReviewPlanItem,
    ReviewPlanResponse,
    ReviewSessionResponse,
    ReviewSessionUpdateRequest,
    ReviewValidateRequest,
    review_claim_adapter,
)
from app.resumes.schemas import ParsedResumeResult
from app.services.resume_duplicate_service import ResumeDuplicateService

logger = logging.getLogger(__name__)
SUPPORTED_IMPORT_TYPES = {"profile", "employment", "education", "internship", "freelance", "gig_platform", "certification", "portfolio"}


class ResumeReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.duplicates = ResumeDuplicateService(session)

    async def create(self, user_id: UUID, resume_id: UUID) -> ReviewSessionResponse:
        document = await self._owned_resume(user_id, resume_id, for_update=True)
        job = await self.session.scalar(
            select(ResumeProcessingJob).where(
                ResumeProcessingJob.resume_document_id == resume_id,
                ResumeProcessingJob.user_id == user_id,
                ResumeProcessingJob.status == "needs_review",
            ).order_by(ResumeProcessingJob.created_at.desc())
        )
        if not job:
            raise ConflictError("Resume is not ready for candidate review")
        parsed = await self.session.scalar(select(ResumeParsedResult).where(ResumeParsedResult.job_id == job.id, ResumeParsedResult.user_id == user_id))
        if not parsed:
            raise ConflictError("Parsed resume result is unavailable")
        existing = await self.session.scalar(select(ResumeReviewSession).where(ResumeReviewSession.parsed_result_id == parsed.id, ResumeReviewSession.user_id == user_id))
        if existing:
            return await self._session_response(existing)

        validated = ParsedResumeResult.model_validate(parsed.structured_result)
        review = ResumeReviewSession(
            user_id=user_id,
            resume_document_id=document.id,
            processing_job_id=job.id,
            parsed_result_id=parsed.id,
            schema_version=parsed.schema_version,
            status=ResumeReviewStatus.DRAFT.value,
        )
        self.session.add(review)
        await self.session.flush()
        for ordinal, (claim_type, raw) in enumerate(self._claims(validated)):
            payload = self._review_payload(claim_type, raw)
            assessment = await self.duplicates.assess(user_id, claim_type, payload)
            source_claim_id = stable_claim_id(parsed.id, claim_type, ordinal, payload)
            exact = next((candidate for candidate in assessment.candidates if candidate["classification"] == "exact_match"), None)
            supported = claim_type in SUPPORTED_IMPORT_TYPES
            item = ResumeReviewItem(
                review_session_id=review.id,
                user_id=user_id,
                claim_type=claim_type,
                source_claim_id=source_claim_id,
                original_payload=payload,
                edited_payload=payload,
                selected=supported and assessment.status == "no_match",
                review_status="selected" if supported and assessment.status == "no_match" else "deselected",
                duplicate_status=assessment.status,
                duplicate_candidates=assessment.candidates,
                conflict_warnings=assessment.warnings,
                import_action="link_existing" if exact else ("create_new" if supported and assessment.status == "no_match" else "skip"),
                target_record_id=UUID(exact["record_id"]) if exact else None,
                source_reference=raw.get("source_text_reference"),
                confidence=raw.get("confidence"),
            )
            self.session.add(item)
        await self.session.commit()
        logger.info("resume_review_created", extra={"resume_id": str(resume_id), "review_session_id": str(review.id), "user_id": str(user_id)})
        return await self._session_response(review)

    async def get_by_resume(self, user_id: UUID, resume_id: UUID) -> ReviewSessionResponse:
        await self._owned_resume(user_id, resume_id)
        review = await self.session.scalar(select(ResumeReviewSession).where(ResumeReviewSession.resume_document_id == resume_id, ResumeReviewSession.user_id == user_id).order_by(ResumeReviewSession.created_at.desc()))
        if not review:
            raise NotFoundError("Resume review session not found")
        return await self._session_response(review)

    async def get(self, user_id: UUID, review_id: UUID) -> ReviewSessionResponse:
        return await self._session_response(await self._owned_review(user_id, review_id))

    async def update_session(self, user_id: UUID, review_id: UUID, payload: ReviewSessionUpdateRequest) -> ReviewSessionResponse:
        review = await self._owned_review(user_id, review_id, for_update=True)
        self._check_version(review.version, payload.expected_version)
        self._ensure_mutable(review)
        review.status = payload.status
        review.version += 1
        await self.session.commit()
        return await self._session_response(review)

    async def update_item(self, user_id: UUID, review_id: UUID, item_id: UUID, payload: ReviewItemUpdateRequest) -> ReviewItemResponse:
        review = await self._owned_review(user_id, review_id, for_update=True)
        self._ensure_mutable(review)
        item = await self.session.scalar(select(ResumeReviewItem).where(ResumeReviewItem.id == item_id, ResumeReviewItem.review_session_id == review_id, ResumeReviewItem.user_id == user_id))
        if not item:
            raise NotFoundError("Resume review item not found")
        self._check_version(item.version, payload.expected_version)
        edited = payload.edited_payload if payload.edited_payload is not None else item.edited_payload
        try:
            claim = review_claim_adapter.validate_python(edited)
        except ValidationError as exc:
            raise ValidationAppError("Review item contains invalid fields", code="invalid_review_item") from exc
        if claim.claim_type != item.claim_type:
            raise ValidationAppError("Claim type cannot be changed", code="claim_type_immutable")
        normalized = review_claim_adapter.dump_python(claim, mode="json")
        assessment = await self.duplicates.assess(user_id, item.claim_type, normalized)
        item.edited_payload = normalized
        item.duplicate_status = assessment.status
        item.duplicate_candidates = assessment.candidates
        item.conflict_warnings = assessment.warnings
        if payload.selected is not None:
            item.selected = payload.selected
        if payload.import_action is not None:
            item.import_action = payload.import_action.value
        if payload.target_record_id is not None or payload.import_action == ResumeImportAction.CREATE_NEW:
            item.target_record_id = payload.target_record_id
        item.review_status = "edited" if normalized != item.original_payload else ("selected" if item.selected else "deselected")
        item.version += 1
        review.status = ResumeReviewStatus.REVIEWING.value
        review.version += 1
        await self.session.commit()
        logger.info("resume_review_item_updated", extra={"review_session_id": str(review.id), "review_item_id": str(item.id), "user_id": str(user_id), "claim_type": item.claim_type, "selected": item.selected})
        return ReviewItemResponse.model_validate(item)

    async def validate(self, user_id: UUID, review_id: UUID, payload: ReviewValidateRequest) -> ReviewPlanResponse:
        review = await self._owned_review(user_id, review_id, for_update=True)
        self._check_version(review.version, payload.expected_version)
        self._ensure_mutable(review)
        plan = await self._build_plan(review)
        review.status = ResumeReviewStatus.READY_TO_IMPORT.value if plan.ready else ResumeReviewStatus.REVIEWING.value
        review.reviewed_at = datetime.now(UTC)
        review.version += 1
        await self.session.commit()
        plan.version = review.version
        logger.info("resume_import_plan_validated", extra={"review_session_id": str(review.id), "user_id": str(user_id), "ready": plan.ready})
        return plan

    async def import_review(self, user_id: UUID, review_id: UUID, payload: ReviewImportRequest) -> ImportBatchResponse:
        review = await self._owned_review(user_id, review_id, for_update=True)
        existing = await self.session.scalar(select(ResumeImportBatch).where(ResumeImportBatch.user_id == user_id, ResumeImportBatch.idempotency_key == payload.idempotency_key))
        if existing:
            if existing.review_session_id != review_id:
                raise ConflictError("Idempotency key is already in use")
            return await self._batch_response(existing)
        self._check_version(review.version, payload.expected_version)
        self._ensure_mutable(review)
        plan = await self._build_plan(review)
        if not plan.ready:
            raise ValidationAppError("Review contains blocking items", code="review_not_importable")
        now = datetime.now(UTC)
        batch = ResumeImportBatch(user_id=user_id, review_session_id=review.id, idempotency_key=payload.idempotency_key, status="processing", started_at=now, total_count=len(plan.items))
        self.session.add(batch)
        review.status = ResumeReviewStatus.IMPORTING.value
        await self.session.flush()
        logger.info("resume_import_started", extra={"review_session_id": str(review.id), "import_batch_id": str(batch.id), "user_id": str(user_id)})
        items = (await self.session.scalars(select(ResumeReviewItem).where(ResumeReviewItem.review_session_id == review.id, ResumeReviewItem.selected.is_(True)).order_by(ResumeReviewItem.created_at))).all()
        for item in items:
            try:
                async with self.session.begin_nested():
                    outcome, record_type, record_id, warnings = await self._import_item(user_id, review, batch, item, now)
                    self.session.add(ResumeImportResult(import_batch_id=batch.id, review_item_id=item.id, outcome=outcome, record_type=record_type, record_id=record_id, warnings=warnings))
                    if outcome == "imported": batch.imported_count += 1
                    elif outcome == "linked": batch.linked_count += 1
                    else: batch.skipped_count += 1
                    logger.info("resume_import_item_completed", extra={"review_session_id": str(review.id), "review_item_id": str(item.id), "user_id": str(user_id), "claim_type": item.claim_type, "outcome": outcome, "target_record_id": str(record_id) if record_id else None})
            except Exception:
                logger.warning("resume_import_item_failed", extra={"review_session_id": str(review.id), "review_item_id": str(item.id), "user_id": str(user_id), "sanitized_failure_code": "item_import_failed"})
                batch.failed_count += 1
                item.review_status = "failed"
                self.session.add(ResumeImportResult(import_batch_id=batch.id, review_item_id=item.id, outcome="failed", sanitized_error_code="item_import_failed", warnings=[]))
        batch.status = "completed" if batch.failed_count == 0 else "partially_completed"
        batch.completed_at = datetime.now(UTC)
        review.status = ResumeReviewStatus.IMPORTED.value if batch.failed_count == 0 else ResumeReviewStatus.PARTIALLY_IMPORTED.value
        review.confirmed_at = now
        review.version += 1
        await self.session.commit()
        logger.info("resume_import_completed", extra={"review_session_id": str(review.id), "import_batch_id": str(batch.id), "user_id": str(user_id), "status": batch.status})
        return await self._batch_response(batch)

    async def import_status(self, user_id: UUID, review_id: UUID, batch_id: UUID) -> ImportBatchResponse:
        batch = await self.session.scalar(select(ResumeImportBatch).where(ResumeImportBatch.id == batch_id, ResumeImportBatch.review_session_id == review_id, ResumeImportBatch.user_id == user_id))
        if not batch:
            raise NotFoundError("Resume import batch not found")
        return await self._batch_response(batch)

    async def latest_import_status(self, user_id: UUID, review_id: UUID) -> ImportBatchResponse:
        await self._owned_review(user_id, review_id)
        batch = await self.session.scalar(select(ResumeImportBatch).where(
            ResumeImportBatch.review_session_id == review_id,
            ResumeImportBatch.user_id == user_id,
        ).order_by(ResumeImportBatch.created_at.desc()))
        if not batch:
            raise NotFoundError("Resume import batch not found")
        return await self._batch_response(batch)

    async def cancel(self, user_id: UUID, review_id: UUID) -> ReviewSessionResponse:
        review = await self._owned_review(user_id, review_id, for_update=True)
        self._ensure_mutable(review)
        review.status = ResumeReviewStatus.CANCELLED.value
        review.cancelled_at = datetime.now(UTC)
        review.version += 1
        await self.session.commit()
        logger.info("resume_review_cancelled", extra={"review_session_id": str(review.id), "user_id": str(user_id)})
        return await self._session_response(review)

    async def _build_plan(self, review: ResumeReviewSession) -> ReviewPlanResponse:
        items = (await self.session.scalars(select(ResumeReviewItem).where(ResumeReviewItem.review_session_id == review.id).order_by(ResumeReviewItem.created_at))).all()
        plans: list[ReviewPlanItem] = []
        for item in items:
            if not item.selected:
                continue
            blockers = self._required_blockers(item.claim_type, item.edited_payload)
            if item.claim_type not in SUPPORTED_IMPORT_TYPES:
                blockers.append("unsupported_import_target")
            verified_protected = False
            if item.import_action in {"link_existing", "update_existing"} and not item.target_record_id:
                blockers.append("target_record_required")
            elif item.import_action in {"link_existing", "update_existing"} and item.target_record_id:
                try:
                    target = await self._target(review.user_id, item.claim_type, item.target_record_id)
                    if item.import_action == "update_existing" and await self._is_protected_target(review.user_id, item.claim_type, target):
                        blockers.append("protected_record")
                        verified_protected = True
                except NotFoundError:
                    blockers.append("target_record_not_found")
            if item.duplicate_status in {"probable_match", "possible_match", "conflict"} and item.import_action == "create_new":
                blockers.append("duplicate_requires_candidate_resolution")
            plans.append(ReviewPlanItem(
                item_id=item.id,
                claim_type=item.claim_type,
                action=item.import_action,
                target_model=item.claim_type if item.claim_type in SUPPORTED_IMPORT_TYPES else None,
                duplicate_status=item.duplicate_status,
                target_record_id=item.target_record_id,
                fields_to_create=sorted(key for key, value in item.edited_payload.items() if key != "claim_type" and value is not None),
                fields_ignored=self._ignored_fields(item.claim_type, item.edited_payload),
                blockers=sorted(set(blockers)),
                warnings=item.conflict_warnings,
                verified_record_protected=verified_protected,
            ))
        if not plans:
            plans.append(ReviewPlanItem(item_id=review.id, claim_type="none", action="none", target_model=None, duplicate_status="no_match", target_record_id=None, fields_to_create=[], fields_ignored=[], blockers=["select_at_least_one_item"], warnings=[], verified_record_protected=False))
        return ReviewPlanResponse(session_id=review.id, ready=not any(item.blockers for item in plans), version=review.version, items=plans)

    async def _import_item(self, user_id: UUID, review: ResumeReviewSession, batch: ResumeImportBatch, item: ResumeReviewItem, now: datetime) -> tuple[str, str | None, UUID | None, list[str]]:
        prior = await self.session.scalar(select(ResumeRecordProvenance).where(
            ResumeRecordProvenance.review_item_id == item.id,
            ResumeRecordProvenance.user_id == user_id,
        ))
        if prior:
            item.review_status = "imported"
            item.imported_record_type = prior.record_type
            item.imported_record_id = prior.record_id
            return "linked", prior.record_type, prior.record_id, ["already_imported"]
        action = item.import_action
        typed_payload = review_claim_adapter.dump_python(
            review_claim_adapter.validate_python(item.edited_payload),
            mode="python",
        )
        if action == "skip":
            item.review_status = "skipped"
            return "skipped", None, None, []
        if action == "link_existing":
            record = await self._target(user_id, item.claim_type, item.target_record_id)
            await self._add_provenance(user_id, review, batch, item, item.claim_type, record.id, now)
            item.review_status, item.imported_record_type, item.imported_record_id = "imported", item.claim_type, record.id
            return "linked", item.claim_type, record.id, []
        if action == "update_existing":
            record = await self._target(user_id, item.claim_type, item.target_record_id)
            if await self._is_protected_target(user_id, item.claim_type, record):
                raise ValidationAppError("Verified or active records cannot be overwritten", code="protected_record")
            self._apply_update(record, item.claim_type, typed_payload)
        else:
            record = await self._create_record(user_id, item.claim_type, typed_payload)
            self.session.add(record)
        await self.session.flush()
        await self._add_provenance(user_id, review, batch, item, item.claim_type, record.id, now)
        item.review_status, item.imported_record_type, item.imported_record_id = "imported", item.claim_type, record.id
        return "imported", item.claim_type, record.id, self._mapping_warnings(item.claim_type, item.edited_payload)

    async def _create_record(self, user_id: UUID, claim_type: str, p: dict[str, Any]) -> Any:
        if claim_type == "profile":
            user = await self.session.get(User, user_id)
            if p.get("full_name") and not user.full_name: user.full_name = p["full_name"]
            if p.get("professional_headline") and not user.headline: user.headline = p["professional_headline"]
            if p.get("summary") and not user.bio: user.bio = p["summary"][:500]
            if p.get("location") and not user.location: user.location = self._location_text(p["location"])
            return user
        if claim_type == "employment":
            user = await self.session.get(User, user_id)
            if not user or not user.full_name:
                raise ValidationAppError("Complete the candidate profile before importing employment", code="candidate_profile_incomplete")
            return Employment(created_by_user_id=user_id, subject_full_name=user.full_name, subject_email=user.email, employer_legal_name=p["company_name"], job_title=p["role_title"], employment_type=p.get("employment_type") if p.get("employment_type") in {v.value for v in EmploymentType} else EmploymentType.OTHER.value, start_date=p["start_date"], end_date=p.get("end_date"), work_location_country=p["location"]["country"].upper(), work_location_region=p.get("location", {}).get("region"), verification_method=VerificationMethod.DOCUMENT.value, verification_status=VerificationStatus.DRAFT.value)
        if claim_type == "education":
            return Education(user_id=user_id, institution_name=p["institution_name"], degree=p["degree"], field_of_study=p.get("field_of_study"), education_level=p["education_level"], grade=p.get("grade"), start_date=p["start_date"], end_date=p.get("end_date"), is_currently_studying=bool(p.get("is_current")), verification_status="draft")
        if claim_type == "internship":
            return Internship(user_id=user_id, company_name=p["company_name"], role=p["role"], description=p.get("description"), start_date=p["start_date"], end_date=p.get("end_date"), is_ongoing=bool(p.get("is_current")), is_paid=False, stipend_currency="INR", verification_status="pending")
        if claim_type == "freelance":
            return FreelanceContract(user_id=user_id, client_name=p["client_name"], project_title=p["project_title"], description=p.get("description"), start_date=p["start_date"], end_date=p.get("end_date"), is_ongoing=bool(p.get("is_current")), verification_status="pending")
        if claim_type == "gig_platform":
            return GigPlatform(user_id=user_id, platform_name=p["platform_name"], partner_role=p["partner_role"], partner_id=p.get("partner_id"), started_at=p["start_date"], ended_at=p.get("end_date"), is_active=bool(p.get("is_current")), verification_status="pending")
        if claim_type == "certification":
            return Certification(user_id=user_id, title=p["title"], issuing_organization=p["issuing_organization"], issued_date=p["issued_date"], expiry_date=p.get("expiry_date"), does_not_expire=p.get("expiry_date") is None, credential_id=p.get("credential_id"), credential_url=str(p["credential_url"]) if p.get("credential_url") else None, verification_status="pending")
        if claim_type == "portfolio":
            return PortfolioItem(user_id=user_id, title=p["title"], description=p.get("description"), url=str(p["url"]) if p.get("url") else None, tags=",".join(p.get("tags", [])) or None, verification_status="pending")
        raise ValidationAppError("Claim type is not importable", code="unsupported_import_target")

    def _apply_update(self, record: Any, claim_type: str, p: dict[str, Any]) -> None:
        mappings = {
            "employment": {"company_name": "employer_legal_name", "role_title": "job_title", "start_date": "start_date", "end_date": "end_date", "employment_type": "employment_type"},
            "education": {"institution_name": "institution_name", "degree": "degree", "field_of_study": "field_of_study", "education_level": "education_level", "grade": "grade", "start_date": "start_date", "end_date": "end_date"},
            "internship": {"company_name": "company_name", "role": "role", "description": "description", "start_date": "start_date", "end_date": "end_date"},
            "freelance": {"client_name": "client_name", "project_title": "project_title", "description": "description", "start_date": "start_date", "end_date": "end_date"},
            "gig_platform": {"platform_name": "platform_name", "partner_role": "partner_role", "partner_id": "partner_id", "start_date": "started_at", "end_date": "ended_at"},
            "certification": {"title": "title", "issuing_organization": "issuing_organization", "issued_date": "issued_date", "expiry_date": "expiry_date", "credential_id": "credential_id", "credential_url": "credential_url"},
            "portfolio": {"title": "title", "description": "description", "url": "url"},
        }
        if claim_type == "profile":
            if p.get("full_name") and not record.full_name: record.full_name = p["full_name"]
            if p.get("professional_headline"): record.headline = p["professional_headline"]
            if p.get("summary"): record.bio = p["summary"][:500]
            if p.get("location"): record.location = self._location_text(p["location"])
            return
        for source, target in mappings[claim_type].items():
            if source in p:
                value = p[source]
                if source in {"url", "credential_url"} and value is not None:
                    value = str(value)
                setattr(record, target, value)

    async def _target(self, user_id: UUID, claim_type: str, record_id: UUID | None) -> Any:
        if not record_id:
            raise ValidationAppError("Target record is required", code="target_record_required")
        model, owner = self._target_model(claim_type)
        record = await self.session.scalar(select(model).where(model.id == record_id, getattr(model, owner) == user_id, model.deleted_at.is_(None))) if claim_type != "profile" else await self.session.get(User, user_id)
        if not record or record.id != record_id:
            raise NotFoundError("Import target not found")
        return record

    async def _add_provenance(self, user_id: UUID, review: ResumeReviewSession, batch: ResumeImportBatch, item: ResumeReviewItem, record_type: str, record_id: UUID, now: datetime) -> None:
        self.session.add(ResumeRecordProvenance(user_id=user_id, record_type=record_type, record_id=record_id, resume_document_id=review.resume_document_id, parsed_result_id=review.parsed_result_id, review_session_id=review.id, review_item_id=item.id, import_batch_id=batch.id, original_payload_hash=payload_hash(item.original_payload), edited_payload_hash=payload_hash(item.edited_payload), confirmed_at=now))

    async def _owned_resume(self, user_id: UUID, resume_id: UUID, *, for_update: bool = False) -> ResumeDocument:
        statement = select(ResumeDocument).where(ResumeDocument.id == resume_id, ResumeDocument.user_id == user_id, ResumeDocument.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update()
        document = await self.session.scalar(statement)
        if not document:
            raise NotFoundError("Resume not found")
        return document

    async def _owned_review(self, user_id: UUID, review_id: UUID, *, for_update: bool = False) -> ResumeReviewSession:
        statement = select(ResumeReviewSession).where(ResumeReviewSession.id == review_id, ResumeReviewSession.user_id == user_id)
        if for_update:
            statement = statement.with_for_update()
        review = await self.session.scalar(statement)
        if not review:
            raise NotFoundError("Resume review session not found")
        return review

    async def _session_response(self, review: ResumeReviewSession) -> ReviewSessionResponse:
        review = await self.session.scalar(select(ResumeReviewSession).where(ResumeReviewSession.id == review.id))
        items = (await self.session.scalars(select(ResumeReviewItem).where(ResumeReviewItem.review_session_id == review.id).order_by(ResumeReviewItem.created_at))).all()
        return ReviewSessionResponse(id=review.id, resume_id=review.resume_document_id, parsed_result_id=review.parsed_result_id, status=review.status, schema_version=review.schema_version, version=review.version, items=[ReviewItemResponse.model_validate(item) for item in items], created_at=review.created_at, updated_at=review.updated_at)

    async def _batch_response(self, batch: ResumeImportBatch) -> ImportBatchResponse:
        batch = await self.session.scalar(select(ResumeImportBatch).where(ResumeImportBatch.id == batch.id))
        results = (await self.session.scalars(select(ResumeImportResult).where(ResumeImportResult.import_batch_id == batch.id).order_by(ResumeImportResult.created_at))).all()
        return ImportBatchResponse(id=batch.id, review_session_id=batch.review_session_id, status=batch.status, total_count=batch.total_count, imported_count=batch.imported_count, linked_count=batch.linked_count, skipped_count=batch.skipped_count, failed_count=batch.failed_count, blocked_count=batch.blocked_count, results=[ImportResultResponse.model_validate(result) for result in results], created_at=batch.created_at, updated_at=batch.updated_at)

    @staticmethod
    def _claims(parsed: ParsedResumeResult) -> list[tuple[str, dict[str, Any]]]:
        output: list[tuple[str, dict[str, Any]]] = []
        profile = parsed.candidate_profile.model_dump(mode="json", exclude={"email", "phone"})
        if any(value for value in profile.values()): output.append(("profile", profile))
        for source, kind in ((parsed.employments, "employment"), (parsed.education, "education"), (parsed.internships, "internship"), (parsed.freelance, "freelance"), (parsed.gig_platforms, "gig_platform"), (parsed.certifications, "certification"), (parsed.projects, "project"), (parsed.skills, "skill")):
            output.extend((kind, item.model_dump(mode="json")) for item in source)
        output.extend(("portfolio", {"url": url, "title": url}) for url in parsed.portfolio_links)
        return output

    @staticmethod
    def _review_payload(claim_type: str, raw: dict[str, Any]) -> dict[str, Any]:
        metadata = {"source_type", "source_text_reference", "confidence", "warnings", "selected_for_import"}
        value = {key: val for key, val in raw.items() if key not in metadata}
        value["claim_type"] = claim_type
        return review_claim_adapter.dump_python(review_claim_adapter.validate_python(value), mode="json")

    @staticmethod
    def _required_blockers(claim_type: str, p: dict[str, Any]) -> list[str]:
        required = {
            "employment": ("company_name", "role_title", "start_date", "location"),
            "education": ("institution_name", "degree", "education_level", "start_date"),
            "internship": ("company_name", "role", "start_date"),
            "freelance": ("client_name", "project_title", "start_date"),
            "gig_platform": ("platform_name", "partner_role", "start_date"),
            "certification": ("title", "issuing_organization", "issued_date"),
            "portfolio": ("title", "url"),
        }
        blockers = [f"missing_{field}" for field in required.get(claim_type, ()) if not p.get(field)]
        if claim_type == "employment" and p.get("location"):
            country = p["location"].get("country")
            if not country:
                blockers.append("missing_work_location_country")
            elif len(country) != 2 or not country.isalpha():
                blockers.append("invalid_work_location_country")
        return blockers

    @staticmethod
    def _target_model(claim_type: str) -> tuple[Any, str]:
        return {"profile": (User, "id"), "employment": (Employment, "created_by_user_id"), "education": (Education, "user_id"), "internship": (Internship, "user_id"), "freelance": (FreelanceContract, "user_id"), "gig_platform": (GigPlatform, "user_id"), "certification": (Certification, "user_id"), "portfolio": (PortfolioItem, "user_id")}[claim_type]

    @staticmethod
    def _protected(record: Any) -> bool:
        return getattr(record, "verification_status", None) in {"submitted", "under_review", "approved", "verified"} or getattr(record, "verified_at", None) is not None

    async def _is_protected_target(self, user_id: UUID, claim_type: str, record: Any) -> bool:
        if self._protected(record):
            return True
        if claim_type != "employment":
            return False
        terminal = {"verified", "rejected", "cancelled", "expired"}
        active = await self.session.scalar(select(VerificationRequest.id).where(
            VerificationRequest.employment_id == record.id,
            VerificationRequest.subject_user_id == user_id,
            VerificationRequest.status.not_in(terminal),
        ).limit(1))
        return active is not None

    @staticmethod
    def _mapping_warnings(claim_type: str, payload: dict[str, Any]) -> list[str]:
        return ["work_arrangement_not_persisted"] if claim_type == "employment" and payload.get("work_arrangement") else []

    @staticmethod
    def _ignored_fields(claim_type: str, payload: dict[str, Any]) -> list[str]:
        ignored: list[str] = []
        if claim_type == "employment":
            ignored.extend(field for field in ("work_arrangement", "description") if payload.get(field) is not None)
            if payload.get("location", {}).get("city"):
                ignored.append("location.city")
        if claim_type == "profile" and payload.get("profile_links"):
            ignored.append("profile_links")
        return ignored

    @staticmethod
    def _location_text(location: dict[str, Any]) -> str:
        return ", ".join(value for value in (location.get("city"), location.get("region"), location.get("country")) if value)

    @staticmethod
    def _check_version(actual: int, expected: int) -> None:
        if actual != expected:
            raise ConflictError("Review was changed by another request")

    @staticmethod
    def _ensure_mutable(review: ResumeReviewSession) -> None:
        if review.status in {"importing", "imported", "cancelled"}:
            raise ConflictError("Resume review is no longer editable")
