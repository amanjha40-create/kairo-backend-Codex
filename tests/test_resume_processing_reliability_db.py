import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from sqlalchemy import delete, func, select, update

from app.config import get_settings
from app.db.session import async_session_factory
from app.models.employment import Employment
from app.models.resume_document import ResumeDocument
from app.models.resume_import_batch import ResumeImportBatch
from app.models.resume_parsed_result import ResumeParsedResult
from app.models.resume_processing_job import ResumeProcessingJob
from app.models.user import User
from app.resumes.providers import ResumeModelOutputTruncated
from app.resumes.schemas import ParsedResumeResult
from app.services.resume_service import ResumeService

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture
async def sample(monkeypatch):
    monkeypatch.setattr(get_settings(), "bedrock_model_id", "synthetic-no-provider-calls")
    monkeypatch.setattr(ResumeService, "_read_object", AsyncMock(return_value=b"%PDF-synthetic"))
    monkeypatch.setattr(
        "app.services.resume_service.JobDispatcher.dispatch_resume_processing", AsyncMock()
    )
    async with async_session_factory() as s:
        u = User(
            email=f"reliability-{uuid4()}@example.invalid",
            full_name="Synthetic",
            role="user",
            is_active=True,
        )
        s.add(u)
        await s.flush()
        d = ResumeDocument(
            user_id=u.id,
            storage_bucket="synthetic",
            storage_key="synthetic",
            original_filename="synthetic.pdf",
            normalized_filename="synthetic.pdf",
            content_type="application/pdf",
            file_size_bytes=128,
            upload_status="uploaded",
            processing_status="queued",
            consent_at=datetime.now(UTC),
            consent_version="test",
        )
        s.add(d)
        await s.flush()
        j = ResumeProcessingJob(
            user_id=u.id, resume_document_id=d.id, idempotency_key=str(uuid4()), status="queued"
        )
        s.add(j)
        await s.commit()
        ids = (u.id, d.id, j.id)
    yield ids
    async with async_session_factory() as s:
        await s.execute(delete(User).where(User.id == ids[0]))
        await s.commit()


async def run(sample):
    async with async_session_factory() as s:
        await ResumeService(s, get_settings()).process_job(sample[1], sample[2])
        await s.commit()


async def job_state(sample):
    async with async_session_factory() as s:
        j = await s.get(ResumeProcessingJob, sample[2])
        return j.status, j.sanitized_failure_code


async def test_pdf_stages_are_committed_and_duplicate_delivery_has_one_result(sample, monkeypatch):
    async def extract(*args, **kwargs):
        assert (await job_state(sample))[0] == "extracting"
        return "Synthetic finance resume"

    async def parse(*args, **kwargs):
        assert (await job_state(sample))[0] == "parsing"
        return ParsedResumeResult(schema_version="1")

    extraction = AsyncMock(side_effect=extract)
    parsing = AsyncMock(side_effect=parse)
    monkeypatch.setattr("app.services.resume_service.TextractDocumentExtractor.extract", extraction)
    monkeypatch.setattr("app.resumes.providers.NovaResumeParser.parse", parsing)
    await run(sample)
    await run(sample)
    assert (await job_state(sample))[0] == "needs_review"
    assert extraction.await_count == parsing.await_count == 1
    async with async_session_factory() as s:
        assert (
            await s.scalar(
                select(func.count())
                .select_from(ResumeParsedResult)
                .where(ResumeParsedResult.job_id == sample[2])
            )
            == 1
        )


@pytest.mark.parametrize(
    "error,code",
    [
        (ResumeModelOutputTruncated("bounded"), "model_output_truncated"),
        (
            ClientError({"Error": {"Code": "ThrottlingException"}}, "InvokeModel"),
            "provider_transient",
        ),
        (
            ClientError({"Error": {"Code": "AccessDeniedException"}}, "InvokeModel"),
            "provider_rejected",
        ),
    ],
)
async def test_failure_then_manual_retry_safely_reuses_object(sample, monkeypatch, error, code):
    monkeypatch.setattr(
        "app.services.resume_service.TextractDocumentExtractor.extract",
        AsyncMock(return_value="synthetic"),
    )
    parse = AsyncMock(side_effect=error)
    monkeypatch.setattr("app.resumes.providers.NovaResumeParser.parse", parse)
    await run(sample)
    assert await job_state(sample) == ("failed", code)
    async with async_session_factory() as s:
        service = ResumeService(s, get_settings())
        response = await service.process(sample[0], sample[1])
        assert (await s.get(ResumeDocument, sample[1])).failure_code is None
    async with async_session_factory() as s:
        duplicate = await ResumeService(s, get_settings()).process(sample[0], sample[1])
        assert duplicate.job_id == response.job_id
    parse.side_effect = None
    parse.return_value = ParsedResumeResult(schema_version="1")
    await run((sample[0], sample[1], response.job_id))
    assert (await job_state((sample[0], sample[1], response.job_id)))[0] == "needs_review"
    async with async_session_factory() as s:
        assert (
            await s.scalar(
                select(func.count())
                .select_from(ResumeParsedResult)
                .where(ResumeParsedResult.user_id == sample[0])
            )
            == 1
        )
        assert (
            await s.scalar(
                select(func.count())
                .select_from(Employment)
                .where(Employment.created_by_user_id == sample[0])
            )
            == 0
        )
        assert (
            await s.scalar(
                select(func.count())
                .select_from(ResumeImportBatch)
                .where(ResumeImportBatch.user_id == sample[0])
            )
            == 0
        )


async def test_status_expires_stuck_queue_without_provider_call(sample):
    async with async_session_factory() as s:
        await s.execute(
            update(ResumeProcessingJob)
            .where(ResumeProcessingJob.id == sample[2])
            .values(updated_at=datetime.now(UTC) - timedelta(hours=3))
        )
        await s.commit()
    async with async_session_factory() as s:
        response = await ResumeService(s, get_settings()).status(sample[0], sample[1])
        assert response.status == "failed"
    assert await job_state(sample) == ("failed", "processing_stale")


async def test_concurrent_retry_double_tap_creates_one_new_job(sample):
    async with async_session_factory() as s:
        j = await s.get(ResumeProcessingJob, sample[2])
        j.status = "failed"
        await s.commit()

    async def retry():
        async with async_session_factory() as s:
            return await ResumeService(s, get_settings()).process(sample[0], sample[1])

    a, b = await asyncio.gather(retry(), retry())
    assert a.job_id == b.job_id != sample[2]
    async with async_session_factory() as s:
        assert (
            await s.scalar(
                select(func.count())
                .select_from(ResumeProcessingJob)
                .where(ResumeProcessingJob.resume_document_id == sample[1])
            )
            == 2
        )


async def test_deleted_resume_cannot_publish_inflight_result(sample, monkeypatch):
    monkeypatch.setattr(
        "app.services.resume_service.TextractDocumentExtractor.extract",
        AsyncMock(return_value="synthetic"),
    )

    async def parse(*args):
        async with async_session_factory() as s:
            row = await s.get(ResumeDocument, sample[1])
            row.deleted_at = datetime.now(UTC)
            row.processing_status = "deleted"
            await s.commit()
        return ParsedResumeResult(schema_version="1")

    monkeypatch.setattr(
        "app.resumes.providers.NovaResumeParser.parse", AsyncMock(side_effect=parse)
    )
    await run(sample)
    async with async_session_factory() as s:
        assert (await s.get(ResumeDocument, sample[1])).processing_status == "deleted"
        assert (
            await s.scalar(
                select(func.count())
                .select_from(ResumeParsedResult)
                .where(ResumeParsedResult.user_id == sample[0])
            )
            == 0
        )


@pytest.mark.parametrize("late_error", [False, True])
async def test_old_attempt_cannot_overwrite_new_success(sample, monkeypatch, late_error):
    monkeypatch.setattr(
        "app.services.resume_service.TextractDocumentExtractor.extract",
        AsyncMock(return_value="synthetic"),
    )

    async def parse(*args):
        async with async_session_factory() as s:
            old = await s.get(ResumeProcessingJob, sample[2])
            old.status = "failed"
            new = ResumeProcessingJob(
                user_id=sample[0],
                resume_document_id=sample[1],
                idempotency_key=str(uuid4()),
                status="needs_review",
                created_at=datetime.now(UTC) + timedelta(seconds=1),
            )
            s.add(new)
            await s.flush()
            s.add(
                ResumeParsedResult(
                    job_id=new.id,
                    user_id=sample[0],
                    schema_version="1",
                    structured_result={"schema_version": "1"},
                    parser_metadata={},
                    warnings=[],
                )
            )
            doc = await s.get(ResumeDocument, sample[1])
            doc.processing_status = "needs_review"
            await s.commit()
        if late_error:
            raise TimeoutError("synthetic late failure")
        return ParsedResumeResult(schema_version="1")

    monkeypatch.setattr(
        "app.resumes.providers.NovaResumeParser.parse", AsyncMock(side_effect=parse)
    )
    await run(sample)
    assert (await job_state(sample))[0] == "failed"
    async with async_session_factory() as s:
        assert (await s.get(ResumeDocument, sample[1])).processing_status == "needs_review"
        assert (
            await s.scalar(
                select(func.count())
                .select_from(ResumeParsedResult)
                .where(ResumeParsedResult.user_id == sample[0])
            )
            == 1
        )
