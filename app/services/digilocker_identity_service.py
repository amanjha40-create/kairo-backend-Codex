"""Explicit-consent, file-free identity verification. No scoring or profile writes."""

import hashlib
import logging

from sqlalchemy import select

from app.exceptions import ValidationAppError
from app.integrations.digilocker.identity import Match, match_document
from app.integrations.digilocker.provider import ProviderError
from app.models import DigiLockerIdentityVerification, User
from app.services.canonical_trust import identity_current, identity_public_reason, resolve_identity
from app.services.digilocker_document_service import DigiLockerDocumentService
from app.services.digilocker_service import transaction

logger = logging.getLogger(__name__)


def reference_fingerprint(doctype, uri):
    return hashlib.sha256(
        ("digilocker:issued_document:" + doctype + ":" + uri).encode()
    ).hexdigest()


class DigiLockerIdentityService(DigiLockerDocumentService):
    @transaction
    async def trust(self, user_id):
        await self._owner(user_id)
        user = await self.session.get(User, user_id)
        result = await resolve_identity(self.session, user, self.now())
        await self.session.rollback()
        return result

    def _public(self, row, user):
        current = identity_current(row, user, self.now().date())
        return {
            "id": str(row.id),
            "source": row.source,
            "source_type": row.source_type,
            "document_type": row.document_type,
            "integrity_result": row.integrity_result,
            "match_result": row.match_result,
            "match_reason": identity_public_reason(row),
            "verified_at": row.verified_at,
            "document_valid_until": row.document_valid_until,
            "consent_purpose": row.consent_purpose,
            "consent_version": row.consent_version,
            "consented_at": row.consented_at,
            "current": current,
        }

    async def _results(self, user):
        rows = (
            await self.session.scalars(
                select(DigiLockerIdentityVerification)
                .where(DigiLockerIdentityVerification.user_id == user.id)
                .order_by(DigiLockerIdentityVerification.created_at)
            )
        ).all()
        results = [self._public(row, user) for row in rows]
        return {"items": results, "identity_verified": any(r["current"] for r in results)}

    @transaction
    async def history(self, user_id):
        await self._owner(user_id)
        user = await self.session.get(User, user_id)
        result = await self._results(user)
        await self.session.rollback()
        return result

    @transaction
    async def verify(self, user_id, document_types, *, consent, consent_version):
        if consent is not True or consent_version != "v1":
            raise ValidationAppError("Explicit identity verification consent is required.")
        if (
            not document_types
            or len(document_types) > 2
            or len(set(document_types)) != len(document_types)
            or set(document_types) - {"PANCR", "DRVLC"}
        ):
            raise ValidationAppError("Select PAN and/or Driving Licence.")
        try:
            # Owner lock serializes concurrent verification, profile edits and account deletion.
            token, _ = await self._read_context(user_id)
            user = await self.session.get(User, user_id)
            connection = await self._connection(user_id)
            items, _ = await self.documents.issued(token)
            selected = []
            for doctype in document_types:
                candidates = {
                    item["uri"]: item
                    for item in items
                    if item["supported"] and item["doctype"] == doctype
                }
                if len(candidates) != 1:
                    raise ValidationAppError(
                        "Selected document unavailable or ambiguous.",
                        code="digilocker_selection_unavailable",
                    )
                selected.append(next(iter(candidates.values())))
            now = self.now()
            for item in selected:
                integrity = "verified"
                xml = bool(set(item["mime"]) & {"application/xml", "text/xml"})
                diagnostic = {
                    "document_type": item["doctype"],
                    "metadata_mimes": item["mime"],
                    "retrieval_endpoint": "xml" if xml else "file",
                    "response_content_type": None,
                    "response_bytes": None,
                    "hmac_result": "NOT_CHECKED",
                    "parser_selected": "none",
                    "parse_category": "PROVIDER_RESPONSE_INVALID",
                }
                try:
                    document = await self.documents.retrieve(token, item["uri"], xml=xml)
                    try:
                        diagnostic.update(
                            response_content_type=document.mime,
                            response_bytes=len(document.content),
                            hmac_result="PASS",
                            parser_selected="xml"
                            if document.mime in {"application/xml", "text/xml"}
                            else "none",
                        )
                        match = match_document(
                            document,
                            item["doctype"],
                            user.full_name,
                            user.date_of_birth,
                            now.date(),
                        )
                        diagnostic["parse_category"] = match.category
                        logger.info(
                            "digilocker_identity_match",
                            extra={
                                "document_type": item["doctype"],
                                **match.diagnostics,
                            },
                        )
                    finally:
                        del document
                except ProviderError as exc:
                    if exc.category != "integrity_failed":
                        raise
                    diagnostic["hmac_result"] = "FAIL"
                    integrity, match = (
                        "failed",
                        Match("UNABLE_TO_VERIFY", category="PROVIDER_RESPONSE_INVALID"),
                    )
                finally:
                    logger.info("digilocker_identity_format", extra=diagnostic)
                fingerprint = reference_fingerprint(item["doctype"], item["uri"])
                row = await self.session.scalar(
                    select(DigiLockerIdentityVerification).where(
                        DigiLockerIdentityVerification.user_id == user_id,
                        DigiLockerIdentityVerification.document_type == item["doctype"],
                        DigiLockerIdentityVerification.provider_reference_fingerprint
                        == fingerprint,
                    )
                )
                if row is None:
                    row = DigiLockerIdentityVerification(
                        user_id=user_id,
                        document_type=item["doctype"],
                        provider_reference_fingerprint=fingerprint,
                    )
                    self.session.add(row)
                row.source_connection_id = connection.id
                row.issuer_id, row.issuer_name = item["issuerid"], item["issuer"]
                row.consent_purpose, row.consent_version, row.consented_at = (
                    "identity_verification",
                    "v1",
                    now,
                )
                row.integrity_result, row.match_result = integrity, match.result
                row.match_reason = (
                    match.diagnostics.get("mismatch_reason")
                    if match.result != "VERIFIED_MATCH"
                    else match.diagnostics.get("name_match_reason")
                )
                row.verified_at = now if match.result == "VERIFIED_MATCH" else None
                row.document_valid_until = match.valid_until
                row.profile_revision_at = user.updated_at
                row.updated_at = now
            await self.session.flush()
            result = await self._results(user)
            await self.session.commit()
            return result
        except ProviderError as exc:
            raise self._failure(exc) from None
