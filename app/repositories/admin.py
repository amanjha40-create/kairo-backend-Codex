"""Admin-facing repository facade — composes employment, document, and verification repos."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employment import Employment
from app.repositories.employment import EmploymentRepository
from app.repositories.employment_document import EmploymentDocumentRepository
from app.repositories.verification import VerificationRepository


class AdminRepository:
    """Privileged read paths with optimized eager-loading helpers — services enforce RBAC."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._employment = EmploymentRepository(session)
        self._documents = EmploymentDocumentRepository(session)
        self._verification = VerificationRepository(session)

    @property
    def session(self) -> AsyncSession:
        return self._session

    def employments(self) -> EmploymentRepository:
        return self._employment

    def documents(self) -> EmploymentDocumentRepository:
        return self._documents

    def verification(self) -> VerificationRepository:
        return self._verification

    async def list_employment_queue(
        self,
        *,
        offset: int,
        limit: int,
        statuses: list[str] | None = None,
        employer_ilike: str | None = None,
        created_after: date | None = None,
        created_before: date | None = None,
    ) -> tuple[list[Employment], int]:
        """Operational queue — same filters as applicant admin list endpoint."""

        return await self._employment.list_admin(
            offset=offset,
            limit=limit,
            statuses=statuses,
            employer_ilike=employer_ilike,
            created_after=created_after,
            created_before=created_before,
        )

    async def get_employment_detail(self, employment_id: UUID, *, load_documents: bool = False) -> Employment | None:
        """Single case — optionally hydrates active documents via selectinload."""

        if load_documents:
            return await self._employment.get_active_by_id_with_documents(employment_id)
        return await self._employment.get_active_by_id(employment_id)

    async def get_pending_verifications(
        self,
        *,
        offset: int,
        limit: int,
        statuses: list[str] | None = None,
        employer_ilike: str | None = None,
        submitted_after: date | None = None,
        submitted_before: date | None = None,
    ) -> tuple[list[Employment], int]:
        """Reviewer-actionable cases (submitted / under_review by default)."""

        return await self._verification.get_pending_verifications(
            offset=offset,
            limit=limit,
            statuses=statuses,
            employer_ilike=employer_ilike,
            submitted_after=submitted_after,
            submitted_before=submitted_before,
        )
