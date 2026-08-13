from __future__ import annotations

from app.config import Settings
from app.exceptions import ServiceUnavailableError
from app.schemas.public_contact import PublicContactAcceptedResponse, PublicContactRequest
from app.services.public_contact_service import PublicContactService


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
        "email_backend": "console",
    }
    base.update(overrides)
    return Settings(**base)


class _FakeEmailDeliveryService:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.calls: list[dict[str, object]] = []
        self.should_fail = should_fail

    async def queue_template_email(self, **kwargs: object):
        self.calls.append(kwargs)
        if self.should_fail:
            raise ServiceUnavailableError("Unable to send email")

        class _Log:
            provider = "brevo"
            public_id = "public-log-id"
            status = "queued"

        return _Log()


async def test_honeypot_submission_is_accepted_without_sending() -> None:
    delivery = _FakeEmailDeliveryService()
    service = PublicContactService(delivery, _settings())

    response = await service.submit(
        PublicContactRequest(
            first_name="Aman",
            last_name="Jha",
            work_email="aman@example.com",
            company="Kairo",
            hires_per_month="25",
            message="We want to learn more about Kairo for hiring.",
            website="https://spam.example.com",
        ),
        request_id="req-123",
        client_host="127.0.0.1",
    )

    assert response == PublicContactAcceptedResponse()
    assert delivery.calls == []


async def test_valid_submission_queues_shared_template_email() -> None:
    delivery = _FakeEmailDeliveryService()
    service = PublicContactService(delivery, _settings())

    response = await service.submit(
        PublicContactRequest(
            first_name="Aman",
            last_name="Jha",
            work_email="aman@example.com",
            company="Kairo",
            hires_per_month="25",
            message="We want to learn more about Kairo for hiring.",
            website="",
        ),
        request_id="req-456",
        client_host="127.0.0.1",
    )

    assert response == PublicContactAcceptedResponse()
    assert len(delivery.calls) == 1
    call = delivery.calls[0]
    assert call["template_key"] == "contact_form_submission"
    assert call["to_email"] == "contact@kairoid.com"
    assert call["raise_on_dispatch_failure"] is True
    template_data = call["template_data"]
    assert isinstance(template_data, dict)
    assert template_data["work_email"] == "aman@example.com"
    assert template_data["company"] == "Kairo"
    assert template_data["request_id"] == "req-456"


async def test_provider_failure_bubbles_up() -> None:
    delivery = _FakeEmailDeliveryService(should_fail=True)
    service = PublicContactService(delivery, _settings())

    try:
        await service.submit(
            PublicContactRequest(
                first_name="Aman",
                last_name="Jha",
                work_email="aman@example.com",
                company="Kairo",
                hires_per_month="25",
                message="We want to learn more about Kairo for hiring.",
                website="",
            ),
            request_id="req-789",
            client_host="127.0.0.1",
        )
    except ServiceUnavailableError as exc:
        assert exc.message == "Unable to send email"
    else:
        raise AssertionError("Expected ServiceUnavailableError")
