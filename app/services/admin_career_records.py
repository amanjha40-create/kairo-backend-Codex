"""Transaction-local Admin writes using the canonical Candidate domain contracts."""

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.gig_platform import GigPlatform
from app.models.portfolio import PortfolioItem
from app.models.project import Project
from app.models.skill import Skill
from app.schemas.admin_career import UPDATE_SCHEMAS, validate_payload
from app.schemas.gig_platform import GigPlatformResponse
from app.schemas.portfolio import PortfolioItemResponse
from app.schemas.project import ProjectResponse
from app.schemas.skill import SkillResponse

MODELS = {
    "portfolio": PortfolioItem,
    "project": Project,
    "skill": Skill,
    "gig_platform": GigPlatform,
}
RESPONSES = {
    "portfolio": PortfolioItemResponse,
    "project": ProjectResponse,
    "skill": SkillResponse,
    "gig_platform": GigPlatformResponse,
}


async def target(
    session: AsyncSession, user_id: UUID, kind: str, record_id: UUID, *, lock: bool = True
):
    model = MODELS[kind]
    query = select(model).where(
        model.id == record_id, model.user_id == user_id, model.deleted_at.is_(None)
    )
    record = await session.scalar(query.with_for_update() if lock else query)
    if record is None:
        raise NotFoundError("Career record not found")
    return record


async def write(
    session: AsyncSession, user_id: UUID, kind: str, payload: dict[str, Any], record=None
) -> tuple[Any, dict[str, Any]]:
    try:
        changes = validate_payload(kind, payload, update=record is not None)
        if record is not None:
            merged = {field: getattr(record, field) for field in UPDATE_SCHEMAS[kind].model_fields}
            if kind == "portfolio":
                merged["tags"] = RESPONSES[kind].model_validate(record).tags
            merged.update(changes)
            # PATCH validation must include persisted date/boolean counterparts.
            UPDATE_SCHEMAS[kind].model_validate(merged)
    except (ValueError, ValidationError) as exc:
        raise ValidationAppError("Invalid Career fields", code="invalid_career_fields") from exc
    stored = dict(changes)
    for field in ("url", "project_url", "repository_url"):
        if stored.get(field) is not None:
            stored[field] = str(stored[field])
    if kind == "portfolio" and "tags" in stored:
        stored["tags"] = ",".join(t.strip() for t in (stored["tags"] or []) if t.strip()) or None
    if kind == "skill":
        normalized = changes["name"].casefold()
        duplicate = select(Skill.id).where(
            Skill.user_id == user_id, Skill.normalized_name == normalized
        )
        if record is not None:
            duplicate = duplicate.where(Skill.id != record.id)
        if await session.scalar(duplicate) is not None:
            raise ConflictError("This skill has already been added")
        stored["normalized_name"] = normalized
    if record is None:
        record = MODELS[kind](user_id=user_id, **stored)
        session.add(record)
    else:
        for field, value in stored.items():
            setattr(record, field, value)
    return record, changes
