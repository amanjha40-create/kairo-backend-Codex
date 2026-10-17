"""Explicit-consent dedicated Aadhaar verification; no file, score or address writes."""

from sqlalchemy import select

from app.exceptions import NotFoundError, ValidationAppError
from app.integrations.digilocker.eaadhaar import DigiLockerEAadhaar, provenance_fingerprint
from app.integrations.digilocker.provider import ProviderError
from app.models import DigiLockerIdentityVerification, User
from app.services.digilocker_identity_service import DigiLockerIdentityService
from app.services.digilocker_service import transaction, unavailable


class DigiLockerEAadhaarService(DigiLockerIdentityService):
    def __init__(self, *args, aadhaar=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.aadhaar = aadhaar or DigiLockerEAadhaar(self.settings)

    def _aadhaar_enabled(self):
        self._enabled()
        if not self.settings.digilocker_eaadhaar_enabled:
            raise NotFoundError("e-Aadhaar is unavailable")
        if (
            self.settings.app_env.value == "production"
            and not self.settings.digilocker_eaadhaar_entitlement_certified
        ):
            raise NotFoundError("e-Aadhaar is unavailable")

    async def _provider_failure(self, user_id, exc):
        if exc.category == "invalid_token":
            connection = await self._connection(user_id)
            await self._reconnect_required(connection)
        if exc.category in {
            "invalid_token",
            "insufficient_scope",
            "aadhaar_not_linked",
            "account_unavailable",
        }:
            return ValidationAppError(
                "e-Aadhaar access is unavailable.", code="digilocker_" + exc.category
            )
        return unavailable(exc.category)

    @transaction
    async def availability(self, user_id):
        self._aadhaar_enabled()
        try:
            token, _ = await self._read_context(user_id)
            available = await self.aadhaar.availability(token)
            return {"available": available, "entitlement_confirmed": False}
        except ProviderError as exc:
            raise await self._provider_failure(user_id, exc) from None
        finally:
            await self.session.rollback()

    @transaction
    async def verify_aadhaar(self, user_id, *, consent, consent_version):
        self._aadhaar_enabled()
        return await self._verify_with_consent(
            user_id, consent=consent, consent_version=consent_version
        )

    async def _verify_with_consent(
        self, user_id, *, consent, consent_version, expected_connection_id=None
    ):
        """Shared single-fetch pipeline; callers must enforce their own entry gate."""
        if consent is not True or consent_version != "v1":
            raise ValidationAppError(
                "Explicit e-Aadhaar identity verification consent is required."
            )
        try:
            token, _ = await self._read_context(user_id)
            user = await self.session.get(User, user_id)
            connection = await self._connection(user_id)
            if expected_connection_id is not None and connection.id != expected_connection_id:
                raise ValidationAppError("Controlled connection changed.", code="connection_changed")
            if not await self.aadhaar.availability(token):
                raise ValidationAppError(
                    "e-Aadhaar is not available for this account.",
                    code="digilocker_aadhaar_not_linked",
                )
            match = await self.aadhaar.verify(
                token, name=user.full_name, dob=user.date_of_birth, today=self.now().date()
            )
            fingerprint = provenance_fingerprint(user_id)
            row = await self.session.scalar(
                select(DigiLockerIdentityVerification).where(
                    DigiLockerIdentityVerification.user_id == user_id,
                    DigiLockerIdentityVerification.document_type == "EAADHAAR",
                    DigiLockerIdentityVerification.provider_reference_fingerprint == fingerprint,
                )
            )
            if row is None:
                row = DigiLockerIdentityVerification(
                    user_id=user_id,
                    document_type="EAADHAAR",
                    source="digilocker",
                    source_type="eaadhaar",
                    provider_reference_fingerprint=fingerprint,
                )
                self.session.add(row)
            row.source_connection_id = connection.id
            row.consent_purpose, row.consent_version, row.consented_at = (
                "identity_verification",
                "v1",
                self.now(),
            )
            row.integrity_result, row.match_result = "verified", match.result
            row.match_reason = (
                match.diagnostics.get("name_match_reason")
                if match.result == "VERIFIED_MATCH"
                else match.diagnostics.get("mismatch_reason", "OTHER")
            )
            row.verified_at = self.now() if match.result == "VERIFIED_MATCH" else None
            row.profile_revision_at = user.updated_at
            await self.session.commit()
            return self._public(row, user)
        except ProviderError as exc:
            raise await self._provider_failure(user_id, exc) from None
