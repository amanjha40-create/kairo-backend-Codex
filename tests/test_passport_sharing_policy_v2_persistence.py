"""Real transaction checks using the repository's disposable PostgreSQL test DB."""

import asyncio
import hashlib
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.exceptions import ConflictError, NotFoundError
from app.models import User
from app.models.passport_share_link import PassportShareLink
from app.schemas.passport_share import PassportShareCreateRequest, PassportShareUpdateRequest
from app.services.passport_share_service import PassportShareService


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_narrowing_owner_isolation_and_hashed_storage():
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = SimpleNamespace(app_public_base_url="https://passport.example.test")
    owner = uuid4()
    try:
        async with factory() as session:
            session.add(User(id=owner, email=f"policy-{owner}@example.test", role="user"))
            await session.commit()
            service = PassportShareService(session, settings)
            created = await service.create(owner, PassportShareCreateRequest(label="QA policy"))
            assert created.policy_version == 2 and created.sharing_mode == "verified_only"
            raw = created.share_url.rsplit("/", 1)[-1]
            stored = await session.get(PassportShareLink, created.id)
            assert stored.token_hash == hashlib.sha256(raw.encode()).hexdigest()
            assert raw not in repr(stored.permissions)
            assert "share_url" not in (await service.get_owned(owner, created.id)).model_dump()

        for action in ("get_owned", "update", "revoke"):
            async with factory() as session:
                service = PassportShareService(session, settings)
                with pytest.raises(NotFoundError):
                    args = [uuid4(), created.id]
                    if action == "update":
                        args.append(
                            PassportShareUpdateRequest(permissions={"include_employments": False})
                        )
                    await getattr(service, action)(*args)

        async def narrow(key):
            async with factory() as session:
                return await PassportShareService(session, settings).update(
                    owner,
                    created.id,
                    PassportShareUpdateRequest(permissions={key: False}),
                )

        await asyncio.gather(narrow("include_employments"), narrow("include_educations"))
        async with factory() as session:
            service = PassportShareService(session, settings)
            current = await service.get_owned(owner, created.id)
            assert not current.permissions.include_employments
            assert not current.permissions.include_educations
            assert current.label == "QA policy" and current.permissions.show_employer_names
            with pytest.raises(ConflictError):
                await service.update(
                    owner,
                    created.id,
                    PassportShareUpdateRequest(permissions={"include_employments": True}),
                )
            await session.rollback()
            await service.revoke(owner, created.id)
            assert (await service.get_owned(owner, created.id)).state == "revoked"
            assert (
                len(
                    (
                        await session.execute(
                            select(PassportShareLink).where(
                                PassportShareLink.owner_user_id == owner
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                == 1
            )
    finally:
        async with factory() as session:
            await session.execute(
                delete(PassportShareLink).where(PassportShareLink.owner_user_id == owner)
            )
            await session.execute(delete(User).where(User.id == owner))
            await session.commit()
        await engine.dispose()
