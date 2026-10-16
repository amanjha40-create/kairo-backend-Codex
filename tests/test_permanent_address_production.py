"""Production-capable, default-OFF configuration; synthetic values only."""

import base64
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.config.permanent_address import PermanentAddressConfigurationError
from app.exceptions import NotFoundError, ServiceUnavailableError
from app.services.permanent_address_geocoder import TargetCipher
from app.services.permanent_address_service import PermanentAddressService
from tests.test_production_configuration_safety import production_settings


def configuration(**changes):
    values = dict(
        permanent_address_enabled=True,
        permanent_address_key_id="production-address-v1",
        permanent_address_keys=json.dumps({
            "production-address-v1": base64.b64encode(b"x" * 32).decode(),
        }),
        s3_documents_bucket="synthetic-prod-documents",
    )
    values.update(changes)
    return production_settings(**values)


@pytest.mark.parametrize("complete", [False, True])
@pytest.mark.asyncio
async def test_production_off_never_touches_database_or_provider(complete, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("disabled feature attempted AWS access")

    monkeypatch.setattr("boto3.client", forbidden)
    settings = configuration(permanent_address_enabled=False) if complete else production_settings()
    service = PermanentAddressService(None, settings)
    result = await service.state(uuid4())
    assert not result.enabled and result.status == "NOT_STARTED"
    assert result.successful_gps_checks == 0
    with pytest.raises(NotFoundError):
        service.require_enabled()


@pytest.mark.asyncio
async def test_complete_production_on_exposes_normal_empty_state_without_provider(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("state read attempted provider access")

    monkeypatch.setattr("boto3.client", forbidden)
    service = PermanentAddressService(
        AsyncMock(scalar=AsyncMock(return_value=None)), configuration()
    )
    result = await service.state(uuid4())
    assert result.enabled and result.status == "NOT_STARTED"
    assert result.required_gps_checks == 3 and result.successful_gps_checks == 0
    assert service.geocoder.region == "us-east-1"


@pytest.mark.parametrize("changes", [
    {"permanent_address_keys": None},
    {"permanent_address_key_id": None},
    {"permanent_address_keys": "private-invalid-keyring"},
    {"permanent_address_keys": {"private": "sensitive"}},
    {"permanent_address_key_id": "staging-address-v1"},
    {"permanent_address_keys": json.dumps({"production-address-v1": "c2hvcnQ="})},
    {"s3_documents_bucket": None},
    {"s3_documents_bucket": "synthetic-staging-documents"},
    {"s3_documents_bucket": "synthetic.stage.documents"},
    {"s3_documents_bucket": "synthetic-dev-documents"},
    {"s3_document_key_prefix": "../documents"},
    {"s3_document_key_prefix": "/documents"},
    {"s3_document_key_prefix": "documents/*"},
    {"aws_region": None},
    {"aws_region": "ap-south-1"},
    {"aws_endpoint_url": "https://example.test"},
    {"permanent_address_places_region": "ap-south-1"},
])
def test_production_on_fails_closed_with_sanitized_error(changes):
    with pytest.raises(PermanentAddressConfigurationError) as error:
        configuration(**changes)
    assert str(error.value) == "Permanent Address configuration is incomplete or invalid"
    assert "private" not in str(error.value)
    assert "sensitive" not in str(error.value)


def test_off_accepts_unprovisioned_address_config():
    settings = configuration(
        permanent_address_enabled=False, permanent_address_key_id=None,
        permanent_address_keys="not-provisioned", s3_documents_bucket=None,
    )
    assert not PermanentAddressService(None, settings).enabled()


def test_environment_alias_and_staging_key_separation(monkeypatch):
    monkeypatch.setenv("PERMANENT_ADDRESS_ENABLED", "true")
    monkeypatch.setenv("PERMANENT_ADDRESS_PLACES_REGION", "us-east-1")
    monkeypatch.setenv("PERMANENT_ADDRESS_KEY_ID", "staging-address-v1")
    monkeypatch.setenv("PERMANENT_ADDRESS_KEYS", json.dumps({
        "staging-address-v1": base64.b64encode(b"s" * 32).decode(),
    }))
    settings = Settings(app_env="staging", aws_region="us-east-1",
                        s3_documents_bucket="synthetic-staging-documents", _env_file=None)
    assert PermanentAddressService(None, settings).enabled()
    with pytest.raises(PermanentAddressConfigurationError):
        invalid = settings.model_copy(update={"app_env": "production"})
        PermanentAddressService(None, invalid).enabled()


def test_runtime_gate_rechecks_bypassed_settings_validation():
    settings = configuration().model_copy(update={"permanent_address_keys": None})
    with pytest.raises(PermanentAddressConfigurationError):
        PermanentAddressService(None, settings).enabled()


def test_production_cipher_rotation_and_context_binding():
    owner, version = uuid4(), uuid4()
    first = TargetCipher(configuration())
    target = {"position": [77.0, 12.0]}
    ciphertext = first.encrypt(target, owner, version)
    assert b"position" not in ciphertext
    rotated = configuration(
        permanent_address_key_id="production-address-v2",
        permanent_address_keys=json.dumps({
            "production-address-v1": base64.b64encode(b"x" * 32).decode(),
            "production-address-v2": base64.b64encode(b"y" * 32).decode(),
        }),
    )
    cipher = TargetCipher(rotated)
    assert cipher.decrypt(ciphertext, first.active, owner, version) == target
    assert cipher.active == "production-address-v2"
    for wrong_owner, wrong_version in [(uuid4(), version), (owner, uuid4())]:
        with pytest.raises(ServiceUnavailableError):
            cipher.decrypt(ciphertext, first.active, wrong_owner, wrong_version)
    assert isinstance(rotated.permanent_address_keys, SecretStr)
    assert base64.b64encode(b"y" * 32).decode() not in repr(rotated)
