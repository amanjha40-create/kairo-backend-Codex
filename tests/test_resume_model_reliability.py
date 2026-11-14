import asyncio
import io
import json
import threading
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from app.resumes.providers import (
    NOVA_RESUME_MAX_OUTPUT_TOKENS,
    NovaResumeParser,
    ResumeModelOutputRejected,
    ResumeModelOutputTruncated,
    _parse_model_json,
)


@pytest.mark.parametrize("text", ['{"employments":[', '{"schema_version":"1"}'])
def test_truncated_output_never_becomes_review_ready(text):
    with pytest.raises(ResumeModelOutputTruncated):
        _parse_model_json(
            {"stopReason": "max_tokens", "output": {"message": {"content": [{"text": text}]}}}
        )


@pytest.mark.parametrize(
    "reason", ["content_filtered", "malformed_model_output", "service_unavailable"]
)
def test_noncompletion_is_rejected_without_exposing_output(reason):
    with pytest.raises(ResumeModelOutputRejected) as error:
        _parse_model_json(
            {
                "stopReason": reason,
                "output": {"message": {"content": [{"text": "PRIVATE DOCUMENT CONTENT"}]}},
            }
        )
    assert "PRIVATE" not in str(error.value)


@pytest.mark.asyncio
async def test_nova_has_bounded_larger_budget_and_does_not_block_event_loop(monkeypatch):
    main_thread = threading.get_ident()
    calls = []
    body = io.BytesIO(
        json.dumps(
            {
                "stopReason": "end_turn",
                "output": {"message": {"content": [{"text": '{"schema_version":"1"}'}]}},
            }
        ).encode()
    )

    class Client:
        def invoke_model(self, **kwargs):
            assert threading.get_ident() != main_thread
            calls.append(json.loads(kwargs["body"]))
            return {"body": body}

    monkeypatch.setattr("app.resumes.providers._bedrock_client", lambda settings: Client())
    result = await asyncio.wait_for(
        NovaResumeParser(
            SimpleNamespace(
                bedrock_model_id="us.amazon.nova-2-lite-v1:0",
            )
        ).parse("Synthetic finance resume"),
        timeout=5,
    )
    assert result.schema_version == "1"
    assert len(calls) == 1
    assert calls[0]["inferenceConfig"]["maxTokens"] == NOVA_RESUME_MAX_OUTPUT_TOKENS == 10_000
    assert body.closed


@pytest.mark.asyncio
async def test_truncation_does_not_automatically_repeat_provider_call(monkeypatch, caplog):
    calls = []

    class Client:
        def invoke_model(self, **kwargs):
            calls.append(1)
            return {"body": io.BytesIO(json.dumps({"stopReason": "max_tokens"}).encode())}

    monkeypatch.setattr("app.resumes.providers._bedrock_client", lambda settings: Client())
    parser = NovaResumeParser(SimpleNamespace(bedrock_model_id="synthetic"))
    with caplog.at_level("INFO"), pytest.raises(ResumeModelOutputTruncated):
        await parser.parse("PRIVATE SYNTHETIC CONTENT")
    assert len(calls) == 1
    assert parser.safe_metadata == {"output_token_limit": 10_000, "stop_reason": "max_tokens"}
    assert "PRIVATE SYNTHETIC CONTENT" not in caplog.text
    event = next(record for record in caplog.records if record.message == "resume.parser.stop")
    assert event.provider == "nova"
    assert event.stop_reason == "max_tokens"
    assert event.output_token_limit == 10_000


@pytest.mark.asyncio
async def test_nova_enforces_configured_token_bounds_before_inference(monkeypatch):
    calls: list[str] = []

    class Client:
        def count_tokens(self, **kwargs):
            calls.append("count")
            assert kwargs["modelId"] == "us.amazon.nova-2-lite-v1:0"
            return {"inputTokens": 12_001}

        def invoke_model(self, **kwargs):
            calls.append("invoke")
            raise AssertionError("Inference must not run above the configured input limit")

    monkeypatch.setattr("app.resumes.providers._bedrock_client", lambda settings: Client())
    parser = NovaResumeParser(
        SimpleNamespace(
            bedrock_model_id="us.amazon.nova-2-lite-v1:0",
            resume_model_max_input_tokens=12_000,
            resume_model_max_output_tokens=5_000,
        )
    )

    with pytest.raises(ValueError, match="configured token limit"):
        await parser.parse("Synthetic resume")

    assert calls == ["count"]
    assert parser.safe_metadata["inputTokens"] == 12_001
    assert parser.safe_metadata["output_token_limit"] == 5_000


@pytest.mark.asyncio
async def test_nova_uses_bounded_request_when_count_tokens_is_unsupported(monkeypatch):
    calls: list[str] = []
    response = io.BytesIO(
        json.dumps(
            {
                "stopReason": "end_turn",
                "output": {"message": {"content": [{"text": '{"schema_version":"1"}'}]}},
            }
        ).encode()
    )

    class Client:
        def count_tokens(self, **kwargs):
            calls.append("count")
            raise ClientError(
                {
                    "Error": {
                        "Code": "ValidationException",
                        "Message": "The provided model doesn't support counting tokens.",
                    }
                },
                "CountTokens",
            )

        def invoke_model(self, **kwargs):
            calls.append("invoke")
            return {"body": response}

    monkeypatch.setattr("app.resumes.providers._bedrock_client", lambda settings: Client())
    parser = NovaResumeParser(
        SimpleNamespace(
            bedrock_model_id="us.amazon.nova-2-lite-v1:0",
            resume_model_max_input_tokens=12_000,
            resume_model_max_request_bytes=25_000,
            resume_model_max_output_tokens=4_400,
        )
    )

    result = await parser.parse("Synthetic resume")

    assert result.schema_version == "1"
    assert calls == ["count", "invoke"]
    assert parser.safe_metadata["input_limit_mode"] == "request_bytes"
    assert 0 < parser.safe_metadata["requestBytes"] <= 25_000


@pytest.mark.asyncio
async def test_nova_rejects_oversized_request_when_count_tokens_is_unsupported(monkeypatch):
    calls: list[str] = []

    class Client:
        def count_tokens(self, **kwargs):
            calls.append("count")
            raise ClientError(
                {
                    "Error": {
                        "Code": "ValidationException",
                        "Message": "The provided model doesn't support counting tokens.",
                    }
                },
                "CountTokens",
            )

        def invoke_model(self, **kwargs):
            calls.append("invoke")
            raise AssertionError("Inference must not run above the configured byte limit")

    monkeypatch.setattr("app.resumes.providers._bedrock_client", lambda settings: Client())
    parser = NovaResumeParser(
        SimpleNamespace(
            bedrock_model_id="us.amazon.nova-2-lite-v1:0",
            resume_model_max_input_tokens=12_000,
            resume_model_max_request_bytes=10_000,
            resume_model_max_output_tokens=4_400,
        )
    )

    with pytest.raises(ValueError, match="configured byte limit"):
        await parser.parse("Synthetic resume")

    assert calls == ["count"]


@pytest.mark.asyncio
async def test_nova_does_not_mask_other_count_tokens_errors(monkeypatch):
    class Client:
        def count_tokens(self, **kwargs):
            raise ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
                "CountTokens",
            )

    monkeypatch.setattr("app.resumes.providers._bedrock_client", lambda settings: Client())
    parser = NovaResumeParser(
        SimpleNamespace(
            bedrock_model_id="us.amazon.nova-2-lite-v1:0",
            resume_model_max_input_tokens=12_000,
            resume_model_max_request_bytes=25_000,
            resume_model_max_output_tokens=4_400,
        )
    )

    with pytest.raises(ClientError) as error:
        await parser.parse("Synthetic resume")

    assert error.value.response["Error"]["Code"] == "AccessDeniedException"
