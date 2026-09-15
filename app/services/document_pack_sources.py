"""Owner-only live source catalog. Historical verification evidence is never selectable."""

import hashlib
import hmac
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import exists, select

from app.exceptions import NotFoundError, ValidationAppError
from app.models import (
    Certification,
    Education,
    EducationDocument,
    Employment,
    EmploymentDocument,
    PortfolioItem,
    UserDocument,
    VerificationRequestEvidence,
)
from app.schemas.document_share_pack import SelectableDocument
from app.services.document_pack_storage import DocumentPackStorage, ObjectBinding

IDENTITY_LABELS = {
    "aadhaar": "Aadhaar",
    "pan": "PAN",
    "passport": "Passport",
    "driving_license": "Driving Licence",
    "voter_id": "Voter ID",
    "birth_certificate": "Birth Certificate",
    "address_proof": "Address Proof",
    "government_id": "Identity document",
    "identity": "Identity document",
    "other": "Personal document",
}


@dataclass
class Source:
    kind: str
    row: object
    category: str
    title: str
    context: str | None = None


class DocumentPackSources:
    def __init__(self, session, settings, storage: DocumentPackStorage):
        self.session, self.settings, self.storage = session, settings, storage

    def queries(self, owner: UUID):
        evidence = VerificationRequestEvidence
        return {
            "vault": select(UserDocument).where(
                UserDocument.user_id == owner,
                UserDocument.deleted_at.is_(None),
                UserDocument.superseded_at.is_(None),
                ~exists().where(evidence.document_id == UserDocument.id),
            ),
            "employment": select(EmploymentDocument, Employment)
            .join(Employment, Employment.id == EmploymentDocument.employment_id)
            .where(
                Employment.created_by_user_id == owner,
                Employment.deleted_at.is_(None),
                EmploymentDocument.uploaded_by_user_id == owner,
                EmploymentDocument.deleted_at.is_(None),
                ~exists().where(evidence.employment_document_id == EmploymentDocument.id),
            ),
            "education": select(EducationDocument, Education)
            .join(Education, Education.id == EducationDocument.education_id)
            .where(
                Education.user_id == owner,
                Education.deleted_at.is_(None),
                EducationDocument.uploaded_by_user_id == owner,
                EducationDocument.deleted_at.is_(None),
                ~exists().where(evidence.education_document_id == EducationDocument.id),
            ),
            "certification": select(Certification).where(
                Certification.user_id == owner, Certification.deleted_at.is_(None)
            ),
            "portfolio": select(PortfolioItem).where(
                PortfolioItem.user_id == owner, PortfolioItem.deleted_at.is_(None)
            ),
        }

    def source(self, kind, values):
        row = values[0]
        if not row.object_key or not row.original_filename or not row.byte_size:
            return None
        if kind == "portfolio":
            if not row.upload_completed_at:
                return None
        elif not row.checksum_sha256 or row.checksum_sha256 == "0" * 64:
            return None
        if kind == "vault":
            return Source(
                kind, row, "identity", IDENTITY_LABELS.get(row.document_type, "Identity document")
            )
        if kind == "employment":
            return Source(
                kind,
                row,
                "employment",
                str(row.document_type).replace("_", " ").title(),
                values[1].employer_legal_name,
            )
        if kind == "education":
            return Source(
                kind,
                row,
                "education",
                str(row.document_type).replace("_", " ").title(),
                values[1].institution_name,
            )
        return Source(
            kind, row, "certifications" if kind == "certification" else "projects", row.title
        )

    def version(self, source: Source, binding: ObjectBinding) -> str:
        message = "\0".join(
            [
                source.kind,
                str(source.row.id),
                binding.key,
                binding.version or "",
                binding.etag,
                str(binding.size),
            ]
        )
        return hmac.new(
            self.settings.jwt_secret_key.encode(),
            ("document-selection\0" + message).encode(),
            hashlib.sha256,
        ).hexdigest()

    async def describe(self, source: Source):
        binding = await self.storage.inspect(source.row.object_key)
        if (
            binding.size != source.row.byte_size
            or binding.content_type != source.row.content_type.split(";")[0].lower()
        ):
            raise ValidationAppError("Selected file no longer matches its upload")
        dto = SelectableDocument(
            source_type=source.kind,
            source_id=source.row.id,
            selection_version=self.version(source, binding),
            category=source.category,
            title=source.title[:512],
            context=source.context[:512] if source.context else None,
            filename=source.row.original_filename,
            content_type=binding.content_type,
            byte_size=binding.size,
        )
        return dto, binding

    async def list(self, owner, *, offset=0, limit=50):
        sources = []
        for kind, query in self.queries(owner).items():
            for values in (await self.session.execute(query)).all():
                source = self.source(kind, values)
                if source:
                    sources.append(source)
        sources.sort(key=lambda s: (s.category, s.title, str(s.row.id)))
        items = []
        for source in sources[offset : offset + limit]:
            try:
                dto, _ = await self.describe(source)
                items.append(dto)
            except (NotFoundError, ValidationAppError):
                continue
        return items, len(sources)

    async def resolve(self, owner, selection):
        model = {
            "vault": UserDocument,
            "employment": EmploymentDocument,
            "education": EducationDocument,
            "certification": Certification,
            "portfolio": PortfolioItem,
        }[selection.source_type]
        query = self.queries(owner)[selection.source_type].where(model.id == selection.source_id)
        values = (await self.session.execute(query.with_for_update())).first()
        source = self.source(selection.source_type, values) if values else None
        if source is None:
            raise NotFoundError("Selected document is unavailable")
        dto, binding = await self.describe(source)
        if not hmac.compare_digest(dto.selection_version, selection.selection_version):
            raise ValidationAppError("Document changed. Select it again before sharing.")
        return source, dto, binding
