"""Read-only DigiLocker discovery and explicit, idempotent record import."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.education.entity_resolution import resolve_education_entity
from app.exceptions import AppException, ServiceUnavailableError, ValidationAppError
from app.infrastructure.s3.client import get_s3_client
from app.integrations.digilocker.crypto import parse_keyring
from app.integrations.digilocker.education import (
    ParsedEducation,
    parse_driving_licence_address_result,
    parse_education_xml,
)
from app.integrations.digilocker.identity import match_document
from app.integrations.digilocker.provider import ProviderError
from app.integrations.digilocker.registry import DOCUMENT_ROUTES, DocumentRoute
from app.models import (
    DigiLockerIdentityVerification,
    Education,
    EducationDocument,
    PermanentAddressVersion,
    User,
)
from app.resumes.normalization import normalize_text
from app.services.canonical_trust import identity_current
from app.services.digilocker_document_service import DigiLockerDocumentService
from app.services.digilocker_identity_service import (
    DigiLockerIdentityService,
    reference_fingerprint,
)
from app.services.digilocker_service import transaction

logger = logging.getLogger(__name__)


@dataclass(slots=True, repr=False)
class DiscoveredItem:
    candidate_id: str
    item: dict[str, Any]
    route: DocumentRoute
    xml_available: bool
    pdf_available: bool
    document: Any | None = None
    parser_status: str = "not_available"
    parsed_education: ParsedEducation | None = None
    match_result: str | None = None
    existing_evidence_id: UUID | None = None


@dataclass(slots=True, repr=False)
class EducationGroupState:
    candidate_id: str
    items: list[DiscoveredItem]
    record_type: str
    display_type: str
    resolution: str
    education_id: UUID | None
    review_state: str


class DigiLockerEvidenceStorage:
    """Selected evidence only; uses the existing private documents bucket."""

    def __init__(self, settings):
        self.settings = settings

    async def put_private(self, *, object_key: str, content: bytes, content_type: str) -> None:
        bucket = self.settings.s3_documents_bucket
        if not bucket:
            raise ServiceUnavailableError("Document storage is not configured")

        def put() -> None:
            get_s3_client(self.settings).put_object(
                Bucket=bucket,
                Key=object_key,
                Body=content,
                ContentType=content_type,
                ContentDisposition="attachment",
                ServerSideEncryption="AES256",
                Metadata={"source": "digilocker"},
                Tagging="data-class=education-evidence&source=digilocker",
            )

        try:
            await asyncio.to_thread(put)
        except (BotoCoreError, ClientError):
            raise ServiceUnavailableError("Document storage is temporarily unavailable") from None

    async def delete_best_effort(self, *, object_key: str) -> None:
        bucket = self.settings.s3_documents_bucket
        if not bucket:
            return

        def delete() -> None:
            get_s3_client(self.settings).delete_object(Bucket=bucket, Key=object_key)

        try:
            await asyncio.to_thread(delete)
        except Exception:
            logger.warning("digilocker_evidence_cleanup_deferred")


class DigiLockerDiscoveryService(DigiLockerDocumentService):
    def __init__(self, *args, storage=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.storage = storage or DigiLockerEvidenceStorage(self.settings)

    def _candidate_id(self, connection, item: dict[str, Any], kind: str) -> str:
        keys = parse_keyring(
            self.settings.digilocker_token_encryption_keys,
            self.settings.digilocker_token_encryption_active_key_id,
            self.settings.app_env.value,
        )
        payload = "\x1f".join(
            (
                "kairoid:digilocker-candidate:v1",
                self.settings.app_env.value,
                str(connection.user_id),
                str(connection.id),
                kind,
                item["doctype"],
                item["uri"],
            )
        ).encode()
        digest = hmac.new(
            keys[self.settings.digilocker_token_encryption_active_key_id], payload, hashlib.sha256
        ).hexdigest()
        return "dl1_" + digest

    def _group_id(self, connection, candidate_ids: list[str]) -> str:
        keys = parse_keyring(
            self.settings.digilocker_token_encryption_keys,
            self.settings.digilocker_token_encryption_active_key_id,
            self.settings.app_env.value,
        )
        payload = "\x1f".join(
            (
                "kairoid:digilocker-education-group:v1",
                self.settings.app_env.value,
                str(connection.user_id),
                str(connection.id),
                *sorted(candidate_ids),
            )
        ).encode()
        digest = hmac.new(
            keys[self.settings.digilocker_token_encryption_active_key_id], payload, hashlib.sha256
        ).hexdigest()
        return "dlg1_" + digest

    @staticmethod
    def _education_resolution(
        parsed: ParsedEducation | None, educations: list[Education]
    ) -> tuple[str, UUID | None]:
        if parsed is None or parsed.parser_status != "parsed":
            return "NO_MATCH", None
        resolution = resolve_education_entity(
            institution_name=parsed.institution_name,
            qualification=parsed.qualification,
            education_level=parsed.education_level,
            completion_year_value=parsed.completion_year,
            educations=educations,
        )
        return resolution.state, resolution.education_id

    @staticmethod
    def _education_group_key(item: DiscoveredItem) -> str:
        route, parsed = item.route, item.parsed_education
        if route.group_strategy in {"class_x", "class_xii"}:
            return route.group_strategy
        if parsed and parsed.parser_status == "parsed":
            return "|".join(
                (
                    route.group_strategy or route.record_type,
                    normalize_text(parsed.institution_name),
                    normalize_text(parsed.qualification),
                    str(parsed.completion_year or ""),
                )
            )
        # Never merge incomplete qualifications merely because they share an issuer.
        return "unresolved:" + item.candidate_id

    @staticmethod
    def _evidence_fingerprints(documents: list[EducationDocument]) -> dict[str, UUID]:
        result = {}
        for document in documents:
            payload = document.extracted_payload or {}
            metadata = payload.get("digilocker") if isinstance(payload, dict) else None
            fingerprint = (
                metadata.get("reference_fingerprint") if isinstance(metadata, dict) else None
            )
            if isinstance(fingerprint, str) and len(fingerprint) == 64:
                result[fingerprint] = document.id
        return result

    async def _snapshot(self, user_id: UUID):
        token, _ = await self._read_context(user_id)
        connection = await self._connection(user_id)
        user = await self.session.get(User, user_id)
        issued, malformed = await self.documents.issued(token)
        supported = [item for item in issued if item["supported"]]

        identity_rows = (
            await self.session.scalars(
                select(DigiLockerIdentityVerification).where(
                    DigiLockerIdentityVerification.user_id == user_id
                )
            )
        ).all()
        identity_by_fingerprint = {row.provider_reference_fingerprint: row for row in identity_rows}
        educations = list(
            (
                await self.session.scalars(
                    select(Education).where(
                        Education.user_id == user_id, Education.deleted_at.is_(None)
                    )
                )
            ).all()
        )
        education_documents = list(
            (
                await self.session.scalars(
                    select(EducationDocument)
                    .join(Education, Education.id == EducationDocument.education_id)
                    .where(
                        Education.user_id == user_id,
                        Education.deleted_at.is_(None),
                        EducationDocument.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        evidence_by_fingerprint = self._evidence_fingerprints(education_documents)
        has_permanent_address = (
            await self.session.scalar(
                select(PermanentAddressVersion.id)
                .where(
                    PermanentAddressVersion.user_id == user_id,
                    PermanentAddressVersion.invalidated_at.is_(None),
                )
                .limit(1)
            )
            is not None
        )

        discovered: list[DiscoveredItem] = []
        parse_failures = 0
        for raw in supported:
            route = DOCUMENT_ROUTES[raw["doctype"]]
            item = DiscoveredItem(
                candidate_id=self._candidate_id(connection, raw, route.domain),
                item=raw,
                route=route,
                xml_available=bool(set(raw["mime"]) & {"application/xml", "text/xml"}),
                pdf_available="application/pdf" in raw["mime"],
            )
            fingerprint = reference_fingerprint(raw["doctype"], raw["uri"])
            item.existing_evidence_id = evidence_by_fingerprint.get(fingerprint)
            if item.xml_available:
                try:
                    item.document = await self.documents.retrieve(token, raw["uri"], xml=True)
                    if route.domain == "identity":
                        match = match_document(
                            item.document,
                            raw["doctype"],
                            user.full_name,
                            user.date_of_birth,
                            self.now().date(),
                        )
                        item.match_result = match.result
                        item.parser_status = (
                            "parsed"
                            if match.category not in {"MALFORMED_XML", "UNSUPPORTED_MIME"}
                            else "parse_failed"
                        )
                    else:
                        item.parsed_education = parse_education_xml(
                            item.document.content,
                            doctype=raw["doctype"],
                            route=route,
                            issuer_name=raw["issuer"],
                        )
                        item.parser_status = item.parsed_education.parser_status
                except ProviderError:
                    item.parser_status = "parse_failed"
            if item.parser_status == "parse_failed":
                parse_failures += 1
            logger.info(
                "digilocker_document_discovered",
                extra={
                    "doctype": raw["doctype"],
                    "domain": route.domain,
                    "parser_status": item.parser_status,
                    "xml_available": item.xml_available,
                },
            )
            discovered.append(item)

        identity_public = []
        address_public = []
        address_prefill_public = []
        address_results = []
        identity_internal: dict[str, DiscoveredItem] = {}
        address_internal: dict[str, DiscoveredItem] = {}
        for item in discovered:
            if item.route.domain != "identity":
                continue
            fingerprint = reference_fingerprint(item.item["doctype"], item.item["uri"])
            existing = identity_by_fingerprint.get(fingerprint)
            current = bool(existing and identity_current(existing, user, self.now().date()))
            review = (
                "already_added"
                if current
                else "parse_failed"
                if item.parser_status == "parse_failed"
                else "ready"
                if item.match_result == "VERIFIED_MATCH"
                else "needs_review"
            )
            identity_public.append(
                self._public_record(item, review, "ALREADY_ADDED" if current else "NO_MATCH")
            )
            identity_internal[item.candidate_id] = item
            if item.item["doctype"] == "DRVLC" and item.document is not None:
                parsed_address = parse_driving_licence_address_result(item.document.content)
                logger.info(
                    "digilocker_drvlc_address_parsed",
                    extra={
                        "classification": parsed_address.classification,
                        "address_node_count": parsed_address.address_node_count,
                        "document_address_type": parsed_address.document_address_type,
                        "missing_fields": parsed_address.missing_fields,
                    },
                )
                address_results.append((item, parsed_address))

        address_discovery_state = "NO_ADDRESS_AVAILABLE"
        meaningful_address_results = [
            pair
            for pair in address_results
            if pair[1].classification != "NO_ADDRESS_AVAILABLE"
        ]
        if len(meaningful_address_results) > 1:
            address_discovery_state = "ADDRESS_AMBIGUOUS"
        elif meaningful_address_results:
            item, parsed_address = meaningful_address_results[0]
            address_discovery_state = parsed_address.classification
            candidate_id = self._candidate_id(connection, item.item, "address")
            common = {
                "candidate_id": candidate_id,
                "doctype": "DRVLC",
                "display_type": "Driving Licence address",
                "source": "digilocker_driving_licence",
                "review_state": "ready",
                "document_address_type": parsed_address.document_address_type,
                "requires_permanent_confirmation": True,
                "requires_replacement_confirmation": has_permanent_address,
            }
            if (
                parsed_address.classification == "STRUCTURED_ADDRESS_CANDIDATE"
                and parsed_address.address is not None
            ):
                structured_address = asdict(parsed_address.address)
                address_public.append(
                    {
                        **common,
                        "candidate_type": "structured",
                        "address_state": "STRUCTURED_ADDRESS_CANDIDATE",
                        "address": structured_address,
                        "structured_address": structured_address,
                    }
                )
                address_internal[candidate_id] = item
            elif (
                parsed_address.classification == "ADDRESS_PREFILL_CANDIDATE"
                and parsed_address.prefill_text is not None
            ):
                address_prefill_public.append(
                    {
                        **common,
                        "candidate_type": "prefill",
                        "address_state": "ADDRESS_PREFILL_CANDIDATE",
                        "prefill_text": parsed_address.prefill_text,
                        "structured_address": None,
                    }
                )

        education_items = [item for item in discovered if item.route.domain == "education"]
        grouped: dict[str, list[DiscoveredItem]] = {}
        for item in education_items:
            grouped.setdefault(self._education_group_key(item), []).append(item)
        education_public = []
        education_internal: dict[str, EducationGroupState] = {}
        for items in grouped.values():
            parsed = next((item.parsed_education for item in items if item.parsed_education), None)
            resolution, education_id = self._education_resolution(parsed, educations)
            all_added = all(item.existing_evidence_id is not None for item in items)
            if all_added:
                resolution, review = "ALREADY_ADDED", "already_added"
            elif (
                resolution in {"AMBIGUOUS", "CONFLICT"}
                or not parsed
                or parsed.parser_status != "parsed"
            ):
                review = (
                    "parse_failed"
                    if any(i.parser_status == "parse_failed" for i in items)
                    else "needs_review"
                )
            else:
                review = "ready"
            group_id = self._group_id(connection, [item.candidate_id for item in items])
            state = EducationGroupState(
                candidate_id=group_id,
                items=items,
                record_type=items[0].route.record_type,
                display_type=(
                    parsed.qualification
                    if parsed and parsed.qualification
                    else items[0].route.display_type
                ),
                resolution=resolution,
                education_id=education_id,
                review_state=review,
            )
            education_internal[group_id] = state
            education_public.append(self._public_group(state))

        counts = {
            "total_issued": len(issued),
            "supported": len(supported),
            "unsupported": len(issued) - len(supported),
            "identity": len(identity_public),
            "education": len(education_public),
            "address_candidates": len(address_public),
            "address_prefill_candidates": len(address_prefill_public),
            "xml_available": sum(item.xml_available for item in discovered),
            "pdf_only": sum(item.pdf_available and not item.xml_available for item in discovered),
            "parse_failures": parse_failures,
            "malformed": malformed,
        }
        return {
            "public": {
                "identity": identity_public,
                "education": education_public,
                "address_candidates": address_public,
                "address_prefill_candidates": address_prefill_public,
                "address_discovery_state": address_discovery_state,
                "counts": counts,
                "discovered_at": self.now(),
            },
            "identity": identity_internal,
            "education": education_internal,
            "address": address_internal,
            "token": token,
            "connection": connection,
        }

    @staticmethod
    def _public_record(item: DiscoveredItem, review: str, resolution: str) -> dict[str, Any]:
        return {
            "candidate_id": item.candidate_id,
            "doctype": item.item["doctype"],
            "record_type": item.route.record_type,
            "display_type": item.route.display_type,
            "description": item.item["description"],
            "issuer_name": item.item["issuer"],
            "source": "digilocker",
            "xml_available": item.xml_available,
            "pdf_available": item.pdf_available,
            "parsed_data_available": item.parser_status == "parsed",
            "import_status": "already_added"
            if review == "already_added"
            else "needs_review"
            if review in {"needs_review", "parse_failed"}
            else "available",
            "possible_existing_record_match": resolution,
            "review_state": review,
        }

    def _public_group(self, group: EducationGroupState) -> dict[str, Any]:
        return {
            "candidate_id": group.candidate_id,
            "record_type": group.record_type,
            "display_type": group.display_type,
            "source": "digilocker",
            "possible_existing_record_match": group.resolution,
            "import_status": "already_added"
            if group.review_state == "already_added"
            else "needs_review"
            if group.review_state in {"needs_review", "parse_failed"}
            else "available",
            "review_state": group.review_state,
            "evidence": [
                {
                    **self._public_record(
                        item,
                        "already_added"
                        if item.existing_evidence_id
                        else item.parser_status
                        if item.parser_status == "parse_failed"
                        else group.review_state,
                        "ALREADY_ADDED" if item.existing_evidence_id else group.resolution,
                    ),
                    "evidence_type": item.route.evidence_type,
                }
                for item in group.items
            ],
        }

    @transaction
    async def available_records(self, user_id: UUID):
        try:
            snapshot = await self._snapshot(user_id)
            return snapshot["public"]
        finally:
            # Discovery must never alter Candidate or provider-derived domain state.
            await self.session.rollback()

    async def _import_education_group(
        self,
        user_id: UUID,
        group: EducationGroupState,
        token,
        *,
        target_education_id: UUID | None = None,
    ) -> dict[str, Any]:
        if group.review_state == "already_added":
            return self._outcome(group.candidate_id, "education", "already_added", group)
        if target_education_id is None and (
            group.review_state != "ready" or group.resolution in {"AMBIGUOUS", "CONFLICT"}
        ):
            return self._outcome(group.candidate_id, "education", "needs_review", group)

        created = False
        if target_education_id is not None:
            education = await self.session.get(Education, target_education_id)
            if (
                education is None
                or education.user_id != user_id
                or education.deleted_at is not None
            ):
                return self._outcome(group.candidate_id, "education", "needs_review", group)
        elif group.education_id is None:
            parsed = next(item.parsed_education for item in group.items if item.parsed_education)
            education = Education(
                id=uuid4(),
                user_id=user_id,
                institution_name=parsed.institution_name,
                degree=parsed.qualification,
                field_of_study=parsed.field_of_study,
                education_level=parsed.education_level,
                end_date=date(parsed.completion_year, 12, 31) if parsed.completion_year else None,
                end_date_precision="year" if parsed.completion_year else None,
                is_currently_studying=False,
                verification_status="draft",
            )
            self.session.add(education)
            await self.session.flush()
            created = True
        else:
            education = await self.session.get(Education, group.education_id)
            if (
                education is None
                or education.user_id != user_id
                or education.deleted_at is not None
            ):
                return self._outcome(group.candidate_id, "education", "needs_review", group)

        uploaded: list[str] = []
        evidence_count = 0
        accepted_at = self.now()
        try:
            for item in group.items:
                if item.existing_evidence_id is not None:
                    continue
                document = None
                if item.pdf_available:
                    try:
                        document = await self.documents.retrieve(token, item.item["uri"], xml=False)
                    except ProviderError:
                        document = None
                if document is None:
                    document = item.document
                if document is None:
                    continue
                fingerprint = reference_fingerprint(item.item["doctype"], item.item["uri"])
                document_id = uuid4()
                extension = "xml" if document.mime in {"application/xml", "text/xml"} else "pdf"
                prefix = self.settings.s3_document_key_prefix.rstrip("/")
                object_key = (
                    f"{prefix}/education-documents/{education.id}/{document_id}/"
                    f"digilocker-{item.item['doctype'].lower()}.{extension}"
                )
                await self.storage.put_private(
                    object_key=object_key,
                    content=document.content,
                    content_type=document.mime,
                )
                uploaded.append(object_key)
                self.session.add(
                    EducationDocument(
                        id=document_id,
                        education_id=education.id,
                        uploaded_by_user_id=user_id,
                        document_type=item.route.evidence_type,
                        object_key=object_key,
                        original_filename=f"digilocker-{item.item['doctype'].lower()}.{extension}",
                        content_type=document.mime,
                        byte_size=len(document.content),
                        checksum_sha256=hashlib.sha256(document.content).hexdigest(),
                        verification_status="verified",
                        verified_at=accepted_at,
                        extracted_payload={
                            "digilocker": {
                                "source": "digilocker",
                                "doctype": item.item["doctype"],
                                "evidence_type": item.route.evidence_type,
                                "issuer_id": item.item["issuerid"],
                                "issuer_name": item.item["issuer"],
                                "reference_fingerprint": fingerprint,
                                "retrieved_at": accepted_at.isoformat(),
                                "parser_status": item.parser_status,
                                "safe_preview": {
                                    "qualification": (
                                        item.parsed_education.qualification
                                        if item.parsed_education
                                        else None
                                    ),
                                    "completion_year": (
                                        item.parsed_education.completion_year
                                        if item.parsed_education
                                        else None
                                    ),
                                },
                            }
                        },
                    )
                )
                evidence_count += 1
            if evidence_count == 0 and not all(
                item.existing_evidence_id is not None for item in group.items
            ):
                await self.session.rollback()
                for object_key in uploaded:
                    await self.storage.delete_best_effort(object_key=object_key)
                return self._outcome(group.candidate_id, "education", "needs_review", group)
            if education.verification_status != "verified" or education.verified_at is None:
                education.verification_status = "verified"
                education.verified_at = accepted_at
            await self.session.commit()
        except (SQLAlchemyError, ServiceUnavailableError):
            await self.session.rollback()
            for object_key in uploaded:
                await self.storage.delete_best_effort(object_key=object_key)
            raise

        status = "imported" if created else "linked"
        return {
            "candidate_id": group.candidate_id,
            "domain": "education",
            "status": status,
            "record_id": education.id,
            "verification_id": None,
            "evidence_count": evidence_count,
            "review_state": "ready",
        }

    @staticmethod
    def _outcome(candidate_id, domain, status, group=None):
        return {
            "candidate_id": candidate_id,
            "domain": domain,
            "status": status,
            "record_id": group.education_id if group else None,
            "verification_id": None,
            "evidence_count": 0,
            "review_state": "already_added" if status == "already_added" else "needs_review",
        }

    @transaction
    async def import_records(
        self,
        user_id: UUID,
        candidate_ids: list[str],
        *,
        education_targets: dict[str, UUID] | None = None,
        consent: bool,
        consent_version: str,
    ):
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValidationAppError("Select each DigiLocker record only once.")
        snapshot = await self._snapshot(user_id)
        education_targets = education_targets or {}
        if set(education_targets) - set(snapshot["education"]):
            await self.session.rollback()
            raise ValidationAppError(
                "Education targets must refer to available Education groups.",
                code="digilocker_selection_unavailable",
            )
        known = set(snapshot["identity"]) | set(snapshot["education"]) | set(snapshot["address"])
        if set(candidate_ids) - known:
            await self.session.rollback()
            raise ValidationAppError(
                "One or more DigiLocker records are no longer available. Refresh the list.",
                code="digilocker_selection_unavailable",
            )
        identity_ids = [
            candidate_id for candidate_id in candidate_ids if candidate_id in snapshot["identity"]
        ]
        if identity_ids and (consent is not True or consent_version != "v1"):
            await self.session.rollback()
            raise ValidationAppError("Explicit identity verification consent is required.")

        outcomes = []
        for candidate_id in identity_ids:
            item = snapshot["identity"][candidate_id]
            try:
                identity = DigiLockerIdentityService(
                    self.session, self.settings, self.store.redis, documents=self.documents
                )
                result = await identity.verify(
                    user_id,
                    [item.item["doctype"]],
                    consent=True,
                    consent_version="v1",
                    selected_references={item.item["doctype"]: item.item["uri"]},
                )
                provider_outcome = result["document_outcomes"][0]
                status = (
                    "already_added"
                    if provider_outcome["status"] == "already_verified"
                    else "imported"
                    if provider_outcome["status"] == "verified"
                    else "needs_review"
                )
                outcomes.append(
                    {
                        "candidate_id": candidate_id,
                        "domain": "identity",
                        "status": status,
                        "record_id": None,
                        "verification_id": provider_outcome.get("verification_id"),
                        "evidence_count": 1 if status in {"imported", "already_added"} else 0,
                        "review_state": "already_added"
                        if status == "already_added"
                        else "ready"
                        if status == "imported"
                        else "needs_review",
                    }
                )
            except AppException:
                await self.session.rollback()
                outcomes.append(self._outcome(candidate_id, "identity", "needs_review"))

        for candidate_id in candidate_ids:
            if candidate_id in snapshot["education"]:
                outcomes.append(
                    await self._import_education_group(
                        user_id,
                        snapshot["education"][candidate_id],
                        snapshot["token"],
                        target_education_id=education_targets.get(candidate_id),
                    )
                )
            elif candidate_id in snapshot["address"]:
                outcomes.append(
                    {
                        "candidate_id": candidate_id,
                        "domain": "address",
                        "status": "use_address_save",
                        "record_id": None,
                        "verification_id": None,
                        "evidence_count": 0,
                        "review_state": "ready",
                    }
                )
        return {"outcomes": outcomes, "completed_at": self.now()}
