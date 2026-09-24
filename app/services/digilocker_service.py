"""Candidate-owned requester connections; no document or verification side effects."""

import logging
from datetime import UTC, datetime, timedelta
from functools import wraps
from uuid import uuid4

from pydantic import SecretStr
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies.rate_limit import _check_rate
from app.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationAppError,
)
from app.infrastructure.redis.keys import RedisKeys
from app.integrations.digilocker.crypto import KeyConfigurationError, TokenCipher, TokenCryptoError
from app.integrations.digilocker.provider import DigiLockerProvider, ProviderError
from app.integrations.digilocker.transactions import StateError, TransactionStore
from app.models.digilocker_connection import DigiLockerConnection
from app.services.private_owner_guard import lock_private_owner

logger = logging.getLogger(__name__)


def flow_error(category):
    return ValidationAppError(
        "DigiLocker connection could not be completed. Please connect again.",
        code="digilocker_" + category,
    )


def unavailable(category="provider_unavailable"):
    error = ServiceUnavailableError("DigiLocker is temporarily unavailable. Please try again.")
    error.code = "digilocker_" + category
    return error


def transaction(method):
    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        try:
            return await method(self, *args, **kwargs)
        except (SQLAlchemyError, RedisError):
            await self.session.rollback()
            logger.warning("digilocker_connect_failed", extra={"category": "storage_unavailable"})
            raise unavailable("storage_unavailable") from None
        except Exception:
            await self.session.rollback()
            raise

    return wrapped


class DigiLockerService:
    def __init__(self, session, settings, redis, *, provider=None, clock=None):
        self.session = session
        self.settings = settings
        self.store = TransactionStore(redis, settings)
        self.provider = provider or DigiLockerProvider(settings)
        self.now = clock or (lambda: datetime.now(UTC))

    def _enabled(self):
        if not self.settings.digilocker_enabled:
            raise unavailable("not_configured")

    async def _owner(self, user_id):
        user = await lock_private_owner(self.session, user_id)
        if user.role != "user" or user.email_verified_at is None:
            raise ForbiddenError("Only authenticated Candidates can connect DigiLocker")

    async def _connection(self, user_id):
        return await self.session.scalar(
            select(DigiLockerConnection)
            .where(DigiLockerConnection.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def _cipher(self):
        return TokenCipher(
            self.settings.digilocker_token_encryption_keys,
            self.settings.digilocker_token_encryption_active_key_id,
            environment=self.settings.app_env.value,
        )

    @staticmethod
    def _context(connection, purpose):
        return dict(
            user_id=connection.user_id,
            connection_id=connection.id,
            purpose=purpose,
            provider="digilocker",
        )

    def _encrypt(self, connection, purpose, value):
        return self._cipher().encrypt_secret(value, **self._context(connection, purpose))

    def _decrypt(self, connection, purpose):
        return self._cipher().decrypt_secret(
            getattr(connection, "encrypted_" + purpose), **self._context(connection, purpose)
        )

    @staticmethod
    def _erase(connection, status):
        connection.encrypted_access_token = None
        connection.encrypted_refresh_token = None
        connection.token_expires_at = None
        connection.consent_valid_until = None
        connection.granted_scopes = []
        connection.pending_attempt_id = None
        connection.pending_expires_at = None
        connection.status = status

    async def _clear_state(self, user_id):
        try:
            await self.store.clear(user_id)
        except RedisError:
            # DB fencing and the owner tombstone still reject callbacks; TTL bounds remnants.
            logger.warning(
                "digilocker_connect_failed", extra={"category": "state_cleanup_deferred"}
            )

    @transaction
    async def connect(self, user_id):
        self._enabled()
        await self._owner(user_id)
        await _check_rate(
            self.store.redis,
            RedisKeys(self.settings).cache(domain="digilocker-rate", key=str(user_id)),
            window_seconds=600,
            max_requests=5,
        )
        connection = await self._connection(user_id)
        if connection is not None and connection.status == "active":
            if not self._credentials_expired(connection):
                raise ConflictError("Disconnect the existing DigiLocker connection first")
        if connection is None:
            connection = DigiLockerConnection(id=uuid4(), user_id=user_id)
            self.session.add(connection)
        self._erase(connection, "pending")
        attempt = uuid4()
        tx = await self.store.create(user_id, connection.id, attempt, self.now())
        connection.pending_attempt_id = attempt
        connection.pending_expires_at = tx.expires_at
        await self.session.commit()
        logger.info("digilocker_connect_started")
        return {
            "authorization_url": self.provider.build_authorization_url(
                state=tx.state.get_secret_value(), challenge=tx.challenge, now=self.now()
            ),
            "expires_at": tx.expires_at,
            "connection_state": "pending",
        }

    async def _revoke(self, tokens):
        for token, purpose in tokens:
            if token is not None:
                try:
                    await self.provider.revoke_token(token, purpose)
                except ProviderError:
                    logger.warning(
                        "digilocker_disconnected", extra={"category": "revoke_unavailable"}
                    )

    @transaction
    async def callback(self, *, state, code=None, error=None):
        self._enabled()
        try:
            tx = await self.store.consume(state, self.now())
        except StateError as exc:
            logger.info("digilocker_connect_failed", extra={"category": exc.category})
            raise flow_error(exc.category) from None
        try:
            await self._owner(tx.user_id)
        except (NotFoundError, ForbiddenError):
            raise flow_error("callback_invalid") from None
        connection = await self._connection(tx.user_id)
        if (
            connection is None
            or connection.id != tx.connection_id
            or connection.status != "pending"
            or connection.pending_attempt_id != tx.attempt_id
            or connection.pending_expires_at is None
            or connection.pending_expires_at <= self.now()
        ):
            raise flow_error("callback_invalid")
        if error is not None or not isinstance(code, str) or not 1 <= len(code) <= 4096:
            self._erase(connection, "disconnected")
            await self.session.commit()
            category = (
                "consent_denied"
                if error == "access_denied" and code is None
                else "callback_invalid"
            )
            logger.info("digilocker_connect_failed", extra={"category": category})
            raise flow_error(category)
        try:
            grant = await self.provider.exchange_authorization_code(
                SecretStr(code), tx.verifier, now=self.now()
            )
        except ProviderError as exc:
            self._erase(connection, "disconnected")
            await self.session.commit()
            logger.info("digilocker_connect_failed", extra={"category": exc.category})
            if exc.category == "invalid_grant":
                raise flow_error("callback_invalid") from None
            raise unavailable() from None
        try:
            self._apply_grant(connection, grant, initial=True)
            await self.session.commit()
        except (SQLAlchemyError, TokenCryptoError, KeyConfigurationError):
            await self.session.rollback()
            await self._revoke(
                [(grant.refresh_token, "refresh_token"), (grant.access_token, "access_token")]
            )
            raise unavailable("storage_unavailable") from None
        logger.info("digilocker_connected")
        return {"connection_state": "active"}

    def _credentials_expired(self, connection):
        return bool(
            (connection.consent_valid_until and connection.consent_valid_until <= self.now())
            # Status/connect must reflect usable access without implicitly refreshing credentials.
            or connection.token_expires_at <= self.now() + timedelta(seconds=30)
        )

    def _apply_grant(self, connection, grant, *, initial=False):
        connection.encrypted_access_token = self._encrypt(
            connection, "access_token", grant.access_token
        )
        if grant.refresh_token is not None:
            connection.encrypted_refresh_token = self._encrypt(
                connection, "refresh_token", grant.refresh_token
            )
        connection.token_expires_at = grant.expires_at
        if grant.consent_valid_until is not None or initial:
            connection.consent_valid_until = grant.consent_valid_until
        if grant.scopes is not None or initial:
            connection.granted_scopes = grant.scopes or []
        connection.status = "active"
        connection.pending_attempt_id = None
        connection.pending_expires_at = None
        connection.revoked_at = None
        if initial:
            connection.connected_at = self.now()
            connection.refreshed_at = None
        else:
            connection.refreshed_at = self.now()

    @transaction
    async def status(self, user_id):
        await self._owner(user_id)
        connection = await self._connection(user_id)
        state = connection.status if connection else "disconnected"
        if connection:
            if state == "pending" and (
                connection.pending_expires_at is None or connection.pending_expires_at <= self.now()
            ):
                state = "disconnected"
            if state == "active" and self._credentials_expired(connection):
                state = "reconnect_required"
        result = {
            "connected": state == "active",
            "status": state,
            "connected_at": connection.connected_at if connection else None,
            "consent_valid_until": connection.consent_valid_until if connection else None,
            "scopes": connection.granted_scopes if connection and state == "active" else [],
        }
        await self.session.rollback()  # Release read locks, without changing lifecycle metadata.
        return result

    async def _reconnect_required(self, connection):
        self._erase(connection, "reconnect_required")
        await self.session.commit()
        raise flow_error("reconnect_required")

    @transaction
    async def access_token(self, user_id) -> SecretStr:
        """Internal only. Never serialize the returned SecretStr into a client response."""
        self._enabled()
        await self._owner(user_id)
        connection = await self._connection(user_id)
        if connection is None or connection.status != "active":
            raise flow_error("reconnect_required")
        if connection.consent_valid_until and connection.consent_valid_until <= self.now():
            await self._reconnect_required(connection)
        try:
            if connection.token_expires_at > self.now() + timedelta(seconds=60):
                token = self._decrypt(connection, "access_token")
                await self.session.rollback()
                return token
            if connection.encrypted_refresh_token is None:
                await self._reconnect_required(connection)
            token = self._decrypt(connection, "refresh_token")
        except (TokenCryptoError, KeyConfigurationError):
            await self._reconnect_required(connection)
        try:
            grant = await self.provider.refresh_access_token(token, now=self.now())
        except ProviderError as exc:
            if exc.category == "invalid_grant":
                await self._reconnect_required(connection)
            raise unavailable() from None
        try:
            self._apply_grant(connection, grant)
            await self.session.commit()
        except (SQLAlchemyError, TokenCryptoError, KeyConfigurationError):
            await self.session.rollback()
            await self._revoke(
                [(grant.refresh_token, "refresh_token"), (grant.access_token, "access_token")]
            )
            raise unavailable("storage_unavailable") from None
        logger.info("digilocker_token_refreshed")
        return grant.access_token

    @transaction
    async def disconnect(self, user_id):
        await self._owner(user_id)
        connection = await self._connection(user_id)
        if connection:
            tokens = []
            if self.settings.digilocker_enabled:
                for purpose in ("refresh_token", "access_token"):
                    if getattr(connection, "encrypted_" + purpose) is not None:
                        try:
                            tokens.append((self._decrypt(connection, purpose), purpose))
                        except (TokenCryptoError, KeyConfigurationError):
                            logger.warning(
                                "digilocker_disconnected", extra={"category": "unreadable_token"}
                            )
                await self._revoke(tokens)
            self._erase(connection, "disconnected")
            connection.revoked_at = self.now()
        # Clear Redis under the owner lock so it cannot erase a subsequent connect.
        await self._clear_state(user_id)
        await self.session.commit()
        logger.info("digilocker_disconnected")
