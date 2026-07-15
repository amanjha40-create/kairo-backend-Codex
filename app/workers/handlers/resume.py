from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.workers.registry import register_handler


@register_handler("resume.process")
async def process_resume(data: dict[str, Any], session: AsyncSession) -> None:
    from app.services.resume_service import ResumeService

    await ResumeService(session, get_settings()).process_job(UUID(str(data["resume_id"])), UUID(str(data["job_id"])))
