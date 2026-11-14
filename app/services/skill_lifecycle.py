"""Transaction-local lifecycle rules for Candidate skills."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill
from app.services.private_owner_guard import lock_private_owner


def normalize_skill_name(name: str) -> tuple[str, str]:
    display_name = " ".join(name.split())
    return display_name, display_name.casefold()


def deleted_skill_key(skill_id: UUID) -> str:
    return f"__deleted__:{skill_id.hex}"


async def reserve_skill_name(
    session: AsyncSession,
    user_id: UUID,
    name: str,
    *,
    exclude_skill_id: UUID | None = None,
) -> tuple[str, str, Skill | None]:
    """Serialize a logical name and retire legacy soft-delete key collisions."""
    await lock_private_owner(session, user_id)
    display_name, normalized_name = normalize_skill_name(name)
    rows = (
        await session.scalars(
            select(Skill)
            .where(
                Skill.user_id == user_id,
                Skill.normalized_name == normalized_name,
            )
            .with_for_update()
        )
    ).all()
    active: Skill | None = None
    for row in rows:
        if row.id == exclude_skill_id:
            continue
        if row.deleted_at is None:
            active = row
        else:
            # Preserve the deleted row and its audit/provenance identity while
            # releasing the user-visible logical name for a genuinely new record.
            row.normalized_name = deleted_skill_key(row.id)
    await session.flush()
    return display_name, normalized_name, active


async def soft_delete_skill(session: AsyncSession, user_id: UUID, skill_id: UUID) -> Skill | None:
    await lock_private_owner(session, user_id)
    row = await session.scalar(
        select(Skill)
        .where(
            Skill.id == skill_id,
            Skill.user_id == user_id,
            Skill.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        return None
    row.normalized_name = deleted_skill_key(row.id)
    row.deleted_at = datetime.now(tz=UTC)
    await session.flush()
    return row
