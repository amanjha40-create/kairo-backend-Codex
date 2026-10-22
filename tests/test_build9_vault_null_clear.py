from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import engine
from app.models.user import User
from app.models.user_document import UserDocument
from app.schemas.user_document import UserDocumentUpdateRequest
from app.services.user_document_service import UserDocumentService


@pytest.mark.asyncio
async def test_optional_fields_omit_set_change_clear_and_refetch():
    async with engine.connect() as conn:
        outer = await conn.begin()
        async with AsyncSession(bind=conn, expire_on_commit=False,
                                join_transaction_mode="create_savepoint") as session:
            user = User(email=f"{uuid4()}@example.test", role="user", is_active=True)
            session.add(user)
            await session.flush()
            row = UserDocument(user_id=user.id, document_type="driving_license",
                               object_key=f"synthetic/{uuid4()}", original_filename="synthetic.pdf",
                               content_type="application/pdf", byte_size=10, checksum_sha256="a" * 64)
            session.add(row)
            await session.flush()
            service = UserDocumentService(session, get_settings())
            for payload, number, expiry in [
                ({}, None, None),
                ({"document_number": "SYNTHETIC-A", "expires_at": "2030-01-01"},
                 "SYNTHETIC-A", date(2030, 1, 1)),
                ({}, "SYNTHETIC-A", date(2030, 1, 1)),
                ({"document_number": "SYNTHETIC-B"}, "SYNTHETIC-B", date(2030, 1, 1)),
                ({"document_number": None}, None, date(2030, 1, 1)),
                ({"expires_at": None}, None, None),
                ({}, None, None),
            ]:
                await service.update(user.id, row.id, UserDocumentUpdateRequest(**payload))
                await session.refresh(row)
                assert row.document_number == number and row.expires_at == expiry
                assert row.original_filename == "synthetic.pdf" and row.checksum_sha256 == "a" * 64
                assert row.user_id == user.id and row.deleted_at is None
        await outer.rollback()
