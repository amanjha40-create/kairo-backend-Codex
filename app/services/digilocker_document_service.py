"""Owner-only ephemeral reads. No commits, refresh, revocation, or raw-document storage."""

from datetime import timedelta

from app.exceptions import NotFoundError, ValidationAppError
from app.integrations.digilocker.crypto import KeyConfigurationError, TokenCryptoError
from app.integrations.digilocker.documents import DigiLockerDocuments, DocumentReferences
from app.integrations.digilocker.provider import ProviderError
from app.services.digilocker_service import DigiLockerService, transaction, unavailable


class DigiLockerDocumentService(DigiLockerService):
    def __init__(self, *args, documents=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.documents = documents or DigiLockerDocuments(self.settings)

    async def _read_context(self, user_id):
        self._enabled()
        await self._owner(user_id)
        connection = await self._connection(user_id)
        if (
            connection is None
            or connection.status != "active"
            or connection.token_expires_at <= self.now() + timedelta(seconds=30)
            or (connection.consent_valid_until and connection.consent_valid_until <= self.now())
        ):
            raise ValidationAppError(
                "DigiLocker access has expired or is unavailable.",
                code="digilocker_access_unavailable",
            )
        try:
            return (
                self._decrypt(connection, "access_token"),
                DocumentReferences(self.settings, connection, self.now()),
            )
        except (TokenCryptoError, KeyConfigurationError):
            raise unavailable("storage_unavailable") from None

    @staticmethod
    def _failure(exc):
        if exc.category == "invalid_reference":
            return NotFoundError("Document reference unavailable. Load the list again.")
        if exc.category in {"invalid_token", "insufficient_scope", "document_not_found"}:
            return ValidationAppError(
                "DigiLocker document access is unavailable.", code="digilocker_" + exc.category
            )
        return unavailable(exc.category)

    @transaction
    async def issued(self, user_id):
        try:
            token, references = await self._read_context(user_id)
            items, malformed = await self.documents.issued(token)
            result = []
            for item in items:
                public = {k: v for k, v in item.items() if k != "uri"}
                public.update(
                    source="digilocker",
                    integrity="not_checked",
                    reference=references.issue(item) if item["supported"] else None,
                )
                result.append(public)
            return {"items": result, "count": len(result), "malformed_count": malformed}
        except ProviderError as exc:
            raise self._failure(exc) from None
        finally:
            await self.session.rollback()

    @transaction
    async def retrieve(self, user_id, reference):
        try:
            token, references = await self._read_context(user_id)
            item = references.open(reference)
            document = await self.documents.retrieve(token, item["uri"])
            return {
                "source": "digilocker",
                "doctype": item["doctype"],
                "issuer": item["issuer"],
                "issuerid": item["issuerid"],
                "reference": reference,
                "mime": document.mime,
                "retrieved_at": self.now().isoformat(),
                "integrity": "verified",
            }
        except ProviderError as exc:
            raise self._failure(exc) from None
        finally:
            await self.session.rollback()
