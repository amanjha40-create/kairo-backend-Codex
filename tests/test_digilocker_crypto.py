import base64
import json
import secrets
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.integrations.digilocker.crypto import KeyConfigurationError, TokenCipher, TokenCryptoError


def key():
    return base64.b64encode(secrets.token_bytes(32)).decode()


def cipher(keys=None, active="test-v1", environment="test"):
    return TokenCipher(
        SecretStr(json.dumps(keys or {active: key()})), active, environment=environment
    )


@pytest.fixture
def context():
    return dict(
        user_id=uuid4(), connection_id=uuid4(), purpose="access_token", provider="digilocker"
    )


def test_roundtrip_nonce_and_no_plaintext(context, caplog):
    crypt = cipher()
    token = SecretStr("synthetic-token-" + secrets.token_urlsafe(32))
    one = crypt.encrypt_secret(token, **context)
    two = crypt.encrypt_secret(token, **context)
    assert one["nonce"] != two["nonce"] and one["ciphertext"] != two["ciphertext"]
    assert len(base64.b64decode(one["nonce"])) == 12
    assert crypt.decrypt_secret(one, **context) == token
    assert token.get_secret_value() not in json.dumps(one) + repr(crypt) + repr(token) + caplog.text


@pytest.mark.parametrize(
    "change",
    [
        {"user_id": uuid4()},
        {"connection_id": uuid4()},
        {"purpose": "refresh_token"},
        {"provider": "other"},
    ],
)
def test_transplant_fails(context, change):
    crypt = cipher()
    value = crypt.encrypt_secret(SecretStr("synthetic"), **context)
    with pytest.raises(TokenCryptoError) as error:
        crypt.decrypt_secret(value, **(context | change))
    assert error.value.category == "authentication_failed"


@pytest.mark.parametrize("field", ["nonce", "ciphertext"])
def test_tampering_fails(context, field, caplog):
    crypt = cipher()
    value = crypt.encrypt_secret(SecretStr("synthetic-sensitive"), **context)
    raw = bytearray(base64.b64decode(value[field]))
    raw[0] ^= 1
    value[field] = base64.b64encode(raw).decode()
    with pytest.raises(TokenCryptoError) as error:
        crypt.decrypt_secret(value, **context)
    assert error.value.category == "authentication_failed"
    assert "synthetic-sensitive" not in str(error.value) + caplog.text
    assert value[field] not in str(error.value) + caplog.text


@pytest.mark.parametrize(
    "change,category",
    [
        ({"version": 2}, "unknown_version"),
        ({"version": True}, "unknown_version"),
        ({"key_id": "unknown"}, "unknown_key_id"),
        ({"key_id": []}, "unknown_key_id"),
        ({"nonce": "***"}, "malformed_envelope"),
        ({"ciphertext": "***"}, "malformed_envelope"),
        ({"nonce": ""}, "malformed_envelope"),
        ({"ciphertext": ""}, "malformed_envelope"),
        ({"extra": "not-allowed"}, "malformed_envelope"),
    ],
)
def test_bad_envelope(context, change, category):
    crypt = cipher()
    value = crypt.encrypt_secret(SecretStr("synthetic"), **context)
    with pytest.raises(TokenCryptoError) as error:
        crypt.decrypt_secret(value | change, **context)
    assert error.value.category == category


@pytest.mark.parametrize("value", [None, [], "plaintext", {}, {"version": 1}])
def test_malformed_envelope(context, value):
    with pytest.raises(TokenCryptoError):
        cipher().decrypt_secret(value, **context)


def test_rotation_and_wrong_key(context):
    old, new = key(), key()
    one = cipher({"test-v1": old}).encrypt_secret(SecretStr("synthetic"), **context)
    rotated = cipher({"test-v1": old, "test-v2": new}, "test-v2")
    assert rotated.decrypt_secret(one, **context).get_secret_value() == "synthetic"
    assert rotated.encrypt_secret(SecretStr("synthetic"), **context)["key_id"] == "test-v2"
    with pytest.raises(TokenCryptoError):
        cipher({"test-v1": new}).decrypt_secret(one, **context)
    with pytest.raises(TokenCryptoError):
        rotated.decrypt_secret(one | {"key_id": "test-v2"}, **context)


def test_environment_is_bound(context):
    shared_test_key = {"test-v1": key()}
    value = cipher(shared_test_key).encrypt_secret(SecretStr("synthetic"), **context)
    with pytest.raises(TokenCryptoError):
        cipher(shared_test_key, environment="development").decrypt_secret(value, **context)


@pytest.mark.parametrize("size", [0, 16, 24, 31, 33, 64])
def test_key_size(size):
    with pytest.raises(KeyConfigurationError):
        cipher({"test-v1": base64.b64encode(secrets.token_bytes(size)).decode()})


@pytest.mark.parametrize(
    "raw,active",
    [
        ("{}", "test-v1"),
        ("not-json", "test-v1"),
        ("[]", "test-v1"),
        ('{"test-v1":"bad","test-v1":"bad"}', "test-v1"),
        ('{"bad id":"bad"}', "bad id"),
        ('{"test-v1":123}', "test-v1"),
        ('{"test-v1":"bad"}', None),
    ],
)
def test_keyring_errors_are_safe(raw, active, caplog):
    with pytest.raises(KeyConfigurationError) as error:
        TokenCipher(SecretStr(raw), active, environment="test")
    assert raw not in str(error.value) + caplog.text


def test_active_and_environment_key_ids():
    with pytest.raises(KeyConfigurationError):
        cipher({"test-old": key()})
    with pytest.raises(KeyConfigurationError):
        cipher(environment="staging")
    same = key()
    with pytest.raises(KeyConfigurationError):
        cipher({"test-v1": same, "test-v2": same})


@pytest.mark.parametrize(
    "value",
    [SecretStr(""), SecretStr(" "), "raw", None, SecretStr("x" * 16385), SecretStr("\ud800")],
)
def test_invalid_plaintext(context, value):
    with pytest.raises(TokenCryptoError):
        cipher().encrypt_secret(value, **context)


def test_settings_enabled_requires_valid_ring():
    from digilocker_helpers import config_values

    with pytest.raises(KeyConfigurationError):
        Settings(digilocker_enabled=True)
    settings = Settings(**config_values())
    assert settings.digilocker_token_encryption_keys.get_secret_value() not in repr(settings)
    assert Settings().digilocker_enabled is False


@pytest.mark.parametrize(
    "change",
    [{"purpose": []}, {"user_id": "not-a-uuid"}, {"connection_id": None}, {"provider": ""}],
)
def test_invalid_context_is_sanitized(context, change):
    with pytest.raises(TokenCryptoError):
        cipher().encrypt_secret(SecretStr("synthetic"), **(context | change))
