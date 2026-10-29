"""Durable DigiLocker state for the Candidate Home dashboard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.exceptions import AppException
from app.integrations.digilocker.provider import ProviderError
from app.models import DigiLockerConnection, DigiLockerIdentityVerification, Education
from app.schemas.passport_engine import DashboardDigiLockerSummary
from app.services.digilocker_discovery_service import DigiLockerDiscoveryService
from app.services.digilocker_verification_projection import education_verification_projections


class DigiLockerHomeSummaryService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        redis: Redis | None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._redis = redis

    async def build(self, user_id: UUID) -> DashboardDigiLockerSummary:
        now = datetime.now(tz=UTC)
        connection = await self._session.scalar(
            select(DigiLockerConnection).where(DigiLockerConnection.user_id == user_id)
        )
        connection_status = self._connection_status(connection, now)
        verified_records_count = await self._verified_records_count(user_id)
        summary = DashboardDigiLockerSummary(
            connection_status=connection_status,
            verified_records_count=verified_records_count,
            new_records_available_count=None,
            needs_review_count=None,
            last_synced_at=None,
            discovery_status="not_connected"
            if connection_status == "never_connected"
            else "reconnect_required"
            if connection_status == "reconnect_required"
            else "unavailable",
        )
        if connection_status != "connected" or self._redis is None:
            return summary

        try:
            discovery = await DigiLockerDiscoveryService(
                self._session,
                self._settings,
                self._redis,
            ).available_records(user_id)
        except (AppException, ProviderError):
            return summary

        records = [*discovery["identity"], *discovery["education"]]
        return summary.model_copy(
            update={
                "new_records_available_count": sum(
                    record["import_status"] == "available" for record in records
                ),
                "needs_review_count": sum(
                    record["import_status"] == "needs_review" for record in records
                ),
                "last_synced_at": discovery["discovered_at"],
                "discovery_status": "fresh",
            }
        )

    @staticmethod
    def _connection_status(
        connection: DigiLockerConnection | None,
        now: datetime,
    ) -> str:
        if connection is None or connection.connected_at is None:
            return "never_connected"
        credentials_current = bool(
            connection.status == "active"
            and connection.encrypted_access_token is not None
            and connection.token_expires_at is not None
            and connection.token_expires_at > now + timedelta(seconds=60)
            and (
                connection.consent_valid_until is None
                or connection.consent_valid_until > now
            )
        )
        return "connected" if credentials_current else "reconnect_required"

    async def _verified_records_count(self, user_id: UUID) -> int:
        identity_count = int(
            await self._session.scalar(
                select(func.count(func.distinct(DigiLockerIdentityVerification.document_type))).where(
                    DigiLockerIdentityVerification.user_id == user_id,
                    DigiLockerIdentityVerification.integrity_result == "verified",
                    DigiLockerIdentityVerification.match_result == "VERIFIED_MATCH",
                    DigiLockerIdentityVerification.verified_at.is_not(None),
                )
            )
            or 0
        )
        educations = list(
            (
                await self._session.scalars(
                    select(Education).where(
                        Education.user_id == user_id,
                        Education.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        projections = await education_verification_projections(self._session, educations)
        education_count = sum(
            projection.status == "verified" and projection.source == "digilocker"
            for projection in projections.values()
        )
        return identity_count + education_count
