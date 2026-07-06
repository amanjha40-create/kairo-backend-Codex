"""Public vault endpoints — read-only, no authentication required.

Returns employment records and document metadata for a given profile slug so
that recruiters can view a candidate's verified career history without logging in.
Download URLs are intentionally excluded — private S3 presign requires auth.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.exceptions import NotFoundError
from app.models import User
from app.models.employment import Employment
from app.models.employment_document import EmploymentDocument
from app.models.freelance_contract import FreelanceContract
from app.models.gig_platform import GigPlatform
from app.models.internship import Internship
from app.models.user_document import UserDocument

router = APIRouter(prefix="/public/vault", tags=["public"])


# ---------- Response schemas ----------

class PublicDoc(BaseModel):
    id: uuid.UUID
    document_type: str
    original_filename: str
    byte_size: int
    verification_status: str


class PublicEmployment(BaseModel):
    id: uuid.UUID
    employer_legal_name: str
    job_title: str
    start_date: date
    end_date: date | None
    verification_status: str
    verification_method: str
    documents: list[PublicDoc]


class PublicInternship(BaseModel):
    id: uuid.UUID
    company_name: str
    role: str
    start_date: date
    end_date: date | None
    is_ongoing: bool
    verification_status: str


class PublicFreelance(BaseModel):
    id: uuid.UUID
    client_name: str
    project_title: str
    start_date: date
    end_date: date | None
    is_ongoing: bool
    verification_status: str


class PublicGigPlatform(BaseModel):
    id: uuid.UUID
    platform_name: str
    partner_role: str
    started_at: date
    ended_at: date | None
    is_active: bool
    rating: float | None
    verification_status: str


class PublicUserDoc(BaseModel):
    id: uuid.UUID
    document_type: str
    original_filename: str
    byte_size: int
    verification_status: str


class PublicVaultResponse(BaseModel):
    employments: list[PublicEmployment]
    internships: list[PublicInternship]
    freelance: list[PublicFreelance]
    gig_platforms: list[PublicGigPlatform]
    user_documents: list[PublicUserDoc]


# ---------- Helpers ----------

async def _resolve_user(slug: str, session: AsyncSession) -> User:
    stmt = select(User).where(
        User.profile_slug == slug,
        User.deleted_at.is_(None),
    )
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user:
        raise NotFoundError("Profile not found")
    return user


# ---------- Route ----------

@router.get("/{slug}", response_model=PublicVaultResponse)
async def get_public_vault(
    slug: str,
    session: AsyncSession = Depends(get_session),
) -> PublicVaultResponse:
    """Return the vault contents for a public profile — no auth required.

    Documents are returned without download URLs (those require auth).
    """
    user = await _resolve_user(slug, session)
    uid = user.id

    # Employments
    emp_rows = (await session.execute(
        select(Employment)
        .where(Employment.created_by_user_id == uid, Employment.deleted_at.is_(None))
        .order_by(Employment.start_date.desc())
    )).scalars().all()

    # Employment documents keyed by employment_id
    emp_ids = [e.id for e in emp_rows]
    doc_rows: list[EmploymentDocument] = []
    if emp_ids:
        doc_rows = (await session.execute(
            select(EmploymentDocument)
            .where(
                EmploymentDocument.employment_id.in_(emp_ids),
                EmploymentDocument.deleted_at.is_(None),
            )
        )).scalars().all()

    docs_by_emp: dict[uuid.UUID, list[PublicDoc]] = {e.id: [] for e in emp_rows}
    for d in doc_rows:
        if d.employment_id in docs_by_emp:
            docs_by_emp[d.employment_id].append(
                PublicDoc(
                    id=d.id,
                    document_type=d.document_type,
                    original_filename=d.original_filename,
                    byte_size=d.byte_size,
                    verification_status=d.verification_status,
                )
            )

    employments = [
        PublicEmployment(
            id=e.id,
            employer_legal_name=e.employer_legal_name,
            job_title=e.job_title,
            start_date=e.start_date,
            end_date=e.end_date,
            verification_status=e.verification_status,
            verification_method=e.verification_method,
            documents=docs_by_emp.get(e.id, []),
        )
        for e in emp_rows
    ]

    # Internships
    int_rows = (await session.execute(
        select(Internship)
        .where(Internship.user_id == uid, Internship.deleted_at.is_(None))
        .order_by(Internship.start_date.desc())
    )).scalars().all()

    internships = [
        PublicInternship(
            id=i.id,
            company_name=i.company_name,
            role=i.role,
            start_date=i.start_date,
            end_date=i.end_date,
            is_ongoing=i.end_date is None,
            verification_status=i.verification_status,
        )
        for i in int_rows
    ]

    # Freelance contracts
    free_rows = (await session.execute(
        select(FreelanceContract)
        .where(FreelanceContract.user_id == uid, FreelanceContract.deleted_at.is_(None))
        .order_by(FreelanceContract.start_date.desc())
    )).scalars().all()

    freelance = [
        PublicFreelance(
            id=f.id,
            client_name=f.client_name,
            project_title=f.project_title,
            start_date=f.start_date,
            end_date=f.end_date,
            is_ongoing=f.end_date is None,
            verification_status=f.verification_status,
        )
        for f in free_rows
    ]

    # Gig platforms
    gig_rows = (await session.execute(
        select(GigPlatform)
        .where(GigPlatform.user_id == uid, GigPlatform.deleted_at.is_(None))
        .order_by(GigPlatform.started_at.desc())
    )).scalars().all()

    gig_platforms = [
        PublicGigPlatform(
            id=g.id,
            platform_name=g.platform_name,
            partner_role=g.partner_role,
            started_at=g.started_at,
            ended_at=g.ended_at,
            is_active=g.is_active,
            rating=float(g.rating) if g.rating is not None else None,
            verification_status=g.verification_status,
        )
        for g in gig_rows
    ]

    # User documents (gig/identity docs)
    udoc_rows = (await session.execute(
        select(UserDocument)
        .where(UserDocument.user_id == uid, UserDocument.deleted_at.is_(None))
        .order_by(UserDocument.created_at.desc())
    )).scalars().all()

    user_documents = [
        PublicUserDoc(
            id=d.id,
            document_type=d.document_type,
            original_filename=d.original_filename,
            byte_size=d.byte_size,
            verification_status=d.verification_status,
        )
        for d in udoc_rows
    ]

    return PublicVaultResponse(
        employments=employments,
        internships=internships,
        freelance=freelance,
        gig_platforms=gig_platforms,
        user_documents=user_documents,
    )
