"""Admin communications operational audit service."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.exceptions import ConflictError, NotFoundError
from app.models.email_delivery_log import EmailDeliveryLog
from app.models.notification import Notification
from app.models.notification_delivery import NotificationDelivery
from app.models.notification_event import NotificationEvent
from app.schemas.admin_communication import (
    AdminCommunicationAttemptResponse,
    AdminCommunicationAuditEventResponse,
    AdminCommunicationFullDetailResponse,
    AdminCommunicationListItemResponse,
    AdminCommunicationListParams,
    AdminCommunicationNotificationSummaryResponse,
    AdminCommunicationRelatedObjectResponse,
    AdminCommunicationResendResponse,
    AdminCommunicationSummaryResponse,
    AdminCommunicationTimelineEventResponse,
)
from app.schemas.pagination import Page
from app.services.notification_service import NotificationService


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    if len(local) <= 2:
        masked_local = f"{local[:1]}***"
    else:
        masked_local = f"{local[:2]}***{local[-1:]}"
    return f"{masked_local}@{domain}"


def _abbreviate_provider_message_id(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 16:
        return value
    return f"{value[:8]}...{value[-6:]}"


def _coerce_datetime(value: datetime | date | None, *, end_of_day: bool) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.max if end_of_day else time.min)


class AdminCommunicationService:
    """Projects canonical delivery logs into an admin-safe operations console."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_communications(
        self,
        params: AdminCommunicationListParams,
    ) -> Page[AdminCommunicationListItemResponse]:
        filters = self._build_filters(params)
        total = await self._session.scalar(
            select(func.count())
            .select_from(EmailDeliveryLog)
            .outerjoin(
                NotificationDelivery,
                NotificationDelivery.email_delivery_log_id == EmailDeliveryLog.id,
            )
            .outerjoin(Notification, Notification.id == NotificationDelivery.notification_id)
            .where(*filters)
        )
        rows = await self._session.execute(
            select(EmailDeliveryLog)
            .outerjoin(
                NotificationDelivery,
                NotificationDelivery.email_delivery_log_id == EmailDeliveryLog.id,
            )
            .outerjoin(Notification, Notification.id == NotificationDelivery.notification_id)
            .where(*filters)
            .order_by(EmailDeliveryLog.created_at.desc(), EmailDeliveryLog.id.desc())
            .offset(params.slice_start)
            .limit(params.limit or 20)
        )
        logs = list(rows.scalars().unique().all())
        linked = await self._load_notification_links(logs)
        return Page[AdminCommunicationListItemResponse].create(
            items=[self._to_list_item(log, linked.get(log.id)) for log in logs],
            total=int(total or 0),
            params=params,
        )

    async def get_detail(
        self,
        communication_public_id: UUID,
    ) -> AdminCommunicationFullDetailResponse:
        log = await self._require_communication_log(communication_public_id)
        linked = await self._load_notification_links([log])
        return await self._to_detail(log, linked.get(log.id))

    async def get_summary(self) -> AdminCommunicationSummaryResponse:
        now = datetime.now(tz=UTC)
        last_24h = now - timedelta(hours=24)
        # Keep the query logic explicit rather than inferring retry infrastructure
        # that does not exist today.
        total = int(
            (
                await self._session.scalar(
                    select(func.count()).select_from(EmailDeliveryLog)
                )
            )
            or 0
        )
        queued = int(
            (
                await self._session.scalar(
                    select(func.count())
                    .select_from(EmailDeliveryLog)
                    .where(EmailDeliveryLog.status == "queued")
                )
            )
            or 0
        )
        sent = int(
            (
                await self._session.scalar(
                    select(func.count())
                    .select_from(EmailDeliveryLog)
                    .where(EmailDeliveryLog.status == "sent")
                )
            )
            or 0
        )
        failed = int(
            (
                await self._session.scalar(
                    select(func.count())
                    .select_from(EmailDeliveryLog)
                    .where(EmailDeliveryLog.status == "failed")
                )
            )
            or 0
        )
        recent_failures_24h = int(
            (
                await self._session.scalar(
                    select(func.count())
                    .select_from(EmailDeliveryLog)
                    .where(
                        EmailDeliveryLog.status == "failed",
                        EmailDeliveryLog.failed_at.is_not(None),
                        EmailDeliveryLog.failed_at >= last_24h,
                    )
                )
            )
            or 0
        )
        resendable_failed = int(
            (
                await self._session.scalar(
                    select(func.count())
                    .select_from(EmailDeliveryLog)
                    .outerjoin(
                        NotificationDelivery,
                        NotificationDelivery.email_delivery_log_id == EmailDeliveryLog.id,
                    )
                    .outerjoin(
                        Notification,
                        Notification.id == NotificationDelivery.notification_id,
                    )
                    .where(
                        EmailDeliveryLog.status == "failed",
                        Notification.id.is_not(None),
                        Notification.channel == "email",
                    )
                )
            )
            or 0
        )
        return AdminCommunicationSummaryResponse(
            total=total,
            queued=queued,
            sent=sent,
            failed=failed,
            recent_failures_24h=recent_failures_24h,
            resendable_failed=resendable_failed,
        )

    async def resend(
        self,
        communication_public_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> AdminCommunicationResendResponse:
        log = await self._require_communication_log(communication_public_id)
        linked = await self._load_notification_links([log])
        linked_delivery = linked.get(log.id)
        notification = linked_delivery.notification if linked_delivery is not None else None
        if linked_delivery is None or notification is None:
            raise ConflictError(
                "This communication is not linked to a canonical notification and cannot be resent."
            )
        if notification.channel != "email":
            raise ConflictError("Only email communications can be resent from this view.")
        notification_service = NotificationService(self._session)
        await notification_service.resend(notification.public_id, actor_user_id=actor_user_id)
        latest_log = await self._latest_log_for_notification(notification.id)
        if latest_log is None:
            raise ConflictError("No communication record was created for the resend attempt.")
        return AdminCommunicationResendResponse(
            communication=await self.get_detail(latest_log.public_id)
        )

    def _build_filters(self, params: AdminCommunicationListParams) -> list[Any]:
        filters: list[Any] = []
        if params.status:
            accepted = [part.strip().lower() for part in params.status.split(",") if part.strip()]
            if accepted:
                filters.append(EmailDeliveryLog.status.in_(accepted))
        if params.channel and params.channel != "email":
            filters.append(EmailDeliveryLog.id.is_(None))
        if params.template_key:
            accepted = [
                part.strip().lower()
                for part in params.template_key.split(",")
                if part.strip()
            ]
            if accepted:
                filters.append(EmailDeliveryLog.template_key.in_(accepted))
        if params.provider:
            accepted = [part.strip().lower() for part in params.provider.split(",") if part.strip()]
            if accepted:
                filters.append(func.lower(EmailDeliveryLog.provider).in_(accepted))
        if params.related_candidate_public_id:
            candidate_public_id = params.related_candidate_public_id
            filters.append(
                or_(
                    Notification.metadata_payload["candidate_public_id"].astext
                    == candidate_public_id,
                    Notification.payload["candidate_public_id"].astext == candidate_public_id,
                    Notification.payload["subject_id"].astext == candidate_public_id,
                    EmailDeliveryLog.payload["candidate_public_id"].astext == candidate_public_id,
                    EmailDeliveryLog.payload["subject_id"].astext == candidate_public_id,
                )
            )
        if params.related_verification_public_id:
            verification_public_id = params.related_verification_public_id
            filters.append(
                or_(
                    Notification.metadata_payload["verification_request_public_id"].astext
                    == verification_public_id,
                    Notification.payload["verification_request_public_id"].astext
                    == verification_public_id,
                    EmailDeliveryLog.payload["verification_request_public_id"].astext
                    == verification_public_id,
                    EmailDeliveryLog.payload["employer_verification_request_public_id"].astext
                    == verification_public_id,
                    EmailDeliveryLog.payload["credential_verification_request_public_id"].astext
                    == verification_public_id,
                )
            )
        if params.related_organization_public_id:
            organization_public_id = params.related_organization_public_id
            filters.append(
                or_(
                    Notification.metadata_payload["organization_public_id"].astext
                    == organization_public_id,
                    Notification.payload["organization_public_id"].astext == organization_public_id,
                    EmailDeliveryLog.payload["organization_public_id"].astext
                    == organization_public_id,
                )
            )
        if params.search:
            pattern = f"%{params.search.strip()}%"
            filters.append(
                or_(
                    EmailDeliveryLog.recipient_email.ilike(pattern),
                    EmailDeliveryLog.subject.ilike(pattern),
                    EmailDeliveryLog.provider.ilike(pattern),
                    EmailDeliveryLog.provider_message_id.ilike(pattern),
                    EmailDeliveryLog.template_key.ilike(pattern),
                    Notification.event_type.ilike(pattern),
                    Notification.title.ilike(pattern),
                )
            )
        if params.created_after:
            created_after = _coerce_datetime(params.created_after, end_of_day=False)
            if created_after is not None:
                filters.append(EmailDeliveryLog.created_at >= created_after)
        if params.created_before:
            created_before = _coerce_datetime(params.created_before, end_of_day=True)
            if created_before is not None:
                filters.append(EmailDeliveryLog.created_at <= created_before)
        return filters

    async def _require_communication_log(self, communication_public_id: UUID) -> EmailDeliveryLog:
        log = (
            await self._session.execute(
                select(EmailDeliveryLog).where(
                    EmailDeliveryLog.public_id == communication_public_id
                )
            )
        ).scalar_one_or_none()
        if log is None:
            raise NotFoundError("Communication not found")
        return log

    async def _load_notification_links(
        self,
        logs: list[EmailDeliveryLog],
    ) -> dict[UUID, NotificationDelivery]:
        if not logs:
            return {}
        rows = await self._session.execute(
            select(NotificationDelivery)
            .options(joinedload(NotificationDelivery.notification))
            .where(
                NotificationDelivery.email_delivery_log_id.in_([log.id for log in logs]),
            )
            .order_by(NotificationDelivery.created_at.desc(), NotificationDelivery.id.desc())
        )
        mapped: dict[UUID, NotificationDelivery] = {}
        for delivery in rows.scalars().all():
            if (
                delivery.email_delivery_log_id is not None
                and delivery.email_delivery_log_id not in mapped
            ):
                mapped[delivery.email_delivery_log_id] = delivery
        return mapped

    async def _load_notification_context(
        self,
        notification_id: UUID,
    ) -> tuple[list[NotificationDelivery], list[NotificationEvent]]:
        deliveries = list(
            (
                await self._session.execute(
                    select(NotificationDelivery)
                    .options(joinedload(NotificationDelivery.email_delivery_log))
                    .where(NotificationDelivery.notification_id == notification_id)
                    .order_by(NotificationDelivery.created_at.asc(), NotificationDelivery.id.asc())
                )
            )
            .scalars()
            .all()
        )
        history = list(
            (
                await self._session.execute(
                    select(NotificationEvent)
                    .where(NotificationEvent.notification_id == notification_id)
                    .order_by(NotificationEvent.created_at.asc(), NotificationEvent.id.asc())
                )
            )
            .scalars()
            .all()
        )
        return deliveries, history

    def _to_list_item(
        self,
        log: EmailDeliveryLog,
        linked_delivery: NotificationDelivery | None,
    ) -> AdminCommunicationListItemResponse:
        notification = linked_delivery.notification if linked_delivery is not None else None
        retryable, retry_policy = self._retry_policy(log, linked_delivery, notification)
        return AdminCommunicationListItemResponse(
            public_id=log.public_id,
            channel="email",
            event_type=notification.event_type if notification is not None else log.template_key,
            template_key=log.template_key,
            template_version=log.template_version,
            status=log.status,
            recipient_masked=_mask_email(log.recipient_email),
            provider=log.provider,
            provider_message_id=log.provider_message_id,
            provider_message_id_display=_abbreviate_provider_message_id(log.provider_message_id),
            subject=log.subject,
            failure_reason=self._failure_reason(log),
            queued_at=log.queued_at,
            sent_at=log.sent_at,
            failed_at=log.failed_at,
            created_at=log.created_at,
            updated_at=log.updated_at,
            retryable=retryable,
            retry_policy=retry_policy,
            related_object=self._related_object(log, notification),
            notification=self._notification_summary(notification),
        )

    async def _to_detail(
        self,
        log: EmailDeliveryLog,
        linked_delivery: NotificationDelivery | None,
    ) -> AdminCommunicationFullDetailResponse:
        item = self._to_list_item(log, linked_delivery)
        notification = linked_delivery.notification if linked_delivery is not None else None
        timeline = self._delivery_timeline(log, linked_delivery)
        deliveries: list[NotificationDelivery] = []
        history: list[NotificationEvent] = []
        if notification is not None:
            deliveries, history = await self._load_notification_context(notification.id)
        return AdminCommunicationFullDetailResponse(
            **item.model_dump(),
            payload_summary=self._payload_summary(log.payload, notification),
            delivery_timeline=timeline,
            notification_public_id=notification.public_id if notification is not None else None,
            delivery_attempts=self._delivery_attempts(deliveries),
            audit_history=self._audit_history(history),
        )

    def _notification_summary(
        self,
        notification: Notification | None,
    ) -> AdminCommunicationNotificationSummaryResponse | None:
        if notification is None:
            return None
        return AdminCommunicationNotificationSummaryResponse(
            public_id=notification.public_id,
            event_type=notification.event_type,
            category=notification.category,
            title=notification.title,
            status=notification.status,
            read_at=notification.read_at,
            created_at=notification.created_at,
        )

    def _related_object(
        self,
        log: EmailDeliveryLog,
        notification: Notification | None,
    ) -> AdminCommunicationRelatedObjectResponse | None:
        metadata = notification.metadata_payload if notification is not None else {}
        payload = log.payload or {}
        if metadata.get("verification_request_public_id"):
            return AdminCommunicationRelatedObjectResponse(
                kind="verification_request",
                public_id=str(metadata["verification_request_public_id"]),
                label="Verification request",
            )
        if metadata.get("trust_invitation_public_id"):
            return AdminCommunicationRelatedObjectResponse(
                kind="trust_invitation",
                public_id=str(metadata["trust_invitation_public_id"]),
                label="Trust invitation",
            )
        if payload.get("employer_verification_request_public_id"):
            return AdminCommunicationRelatedObjectResponse(
                kind="employer_verification_request",
                public_id=str(payload["employer_verification_request_public_id"]),
                label="Employer verification outreach",
            )
        if payload.get("credential_verification_request_public_id"):
            return AdminCommunicationRelatedObjectResponse(
                kind="credential_verification_request",
                public_id=str(payload["credential_verification_request_public_id"]),
                label="Credential verification outreach",
            )
        return None

    def _failure_reason(self, log: EmailDeliveryLog) -> str | None:
        if not log.error_message and not log.error_code:
            return None
        parts = [part for part in (log.error_code, log.error_message) if part]
        message = " — ".join(parts)
        return message[:240]

    def _payload_summary(
        self,
        payload: dict[str, Any],
        notification: Notification | None,
    ) -> dict[str, Any]:
        allowed_keys = {
            "organization_name",
            "subject_name",
            "request_type",
            "completed_at_iso",
            "purpose",
            "contact_name",
            "subject_full_name",
            "employer_name",
            "job_title",
            "relationship",
            "ttl_hours",
            "ttl_minutes",
            "subject_type",
            "subject_id",
            "verifier_outcome",
            "verification_request_public_id",
            "employer_verification_request_public_id",
            "credential_verification_request_public_id",
        }
        summary = {
            key: value
            for key, value in (payload or {}).items()
            if key in allowed_keys and value is not None
        }
        if notification is not None:
            for key in (
                "verification_request_public_id",
                "trust_invitation_public_id",
                "organization_public_id",
                "candidate_public_id",
                "delivery_trigger",
                "linked_record_type",
                "linked_record_id",
            ):
                value = notification.metadata_payload.get(key)
                if value is not None:
                    summary[key] = value
        return summary

    def _delivery_timeline(
        self,
        log: EmailDeliveryLog,
        linked_delivery: NotificationDelivery | None,
    ) -> list[AdminCommunicationTimelineEventResponse]:
        events: list[AdminCommunicationTimelineEventResponse] = [
            AdminCommunicationTimelineEventResponse(
                kind="queued",
                occurred_at=log.queued_at,
                detail="Communication queued for provider dispatch.",
                status="queued",
            )
        ]
        if log.sent_at is not None:
            events.append(
                AdminCommunicationTimelineEventResponse(
                    kind="sent",
                    occurred_at=log.sent_at,
                    detail="Provider accepted the communication for delivery.",
                    status=log.status,
                )
            )
        if log.failed_at is not None:
            events.append(
                AdminCommunicationTimelineEventResponse(
                    kind="failed",
                    occurred_at=log.failed_at,
                    detail=self._failure_reason(log) or "Communication delivery failed.",
                    status="failed",
                )
            )
        if linked_delivery is not None:
            if linked_delivery.dispatched_at is not None:
                events.append(
                    AdminCommunicationTimelineEventResponse(
                        kind="notification_dispatch",
                        occurred_at=linked_delivery.dispatched_at,
                        detail="Notification dispatcher recorded the delivery attempt.",
                        status=linked_delivery.status,
                    )
                )
            if linked_delivery.delivered_at is not None:
                events.append(
                    AdminCommunicationTimelineEventResponse(
                        kind="notification_delivered",
                        occurred_at=linked_delivery.delivered_at,
                        detail="Notification delivery completed.",
                        status=linked_delivery.status,
                    )
                )
            if linked_delivery.failed_at is not None:
                events.append(
                    AdminCommunicationTimelineEventResponse(
                        kind="notification_failed",
                        occurred_at=linked_delivery.failed_at,
                        detail=linked_delivery.error_message or "Notification delivery failed.",
                        status=linked_delivery.status,
                    )
                )
        events.sort(key=lambda item: item.occurred_at)
        return events

    def _delivery_attempts(
        self,
        deliveries: list[NotificationDelivery],
    ) -> list[AdminCommunicationAttemptResponse]:
        return [
            AdminCommunicationAttemptResponse(
                notification_delivery_public_id=delivery.public_id,
                communication_public_id=(
                    delivery.email_delivery_log.public_id
                    if delivery.email_delivery_log is not None
                    else None
                ),
                channel=delivery.channel,
                status=delivery.status,
                provider=delivery.provider,
                provider_message_id_display=_abbreviate_provider_message_id(
                    delivery.provider_message_id
                ),
                attempt_count=delivery.attempt_count,
                error_code=delivery.error_code,
                error_message=delivery.error_message,
                dispatched_at=delivery.dispatched_at,
                delivered_at=delivery.delivered_at,
                failed_at=delivery.failed_at,
                created_at=delivery.created_at,
            )
            for delivery in deliveries
        ]

    def _audit_history(
        self,
        history: list[NotificationEvent],
    ) -> list[AdminCommunicationAuditEventResponse]:
        return [
            AdminCommunicationAuditEventResponse(
                public_id=event.public_id,
                actor_user_id=event.actor_user_id,
                event_type=event.event_type,
                status=event.status,
                metadata=event.metadata_payload,
                created_at=event.created_at,
            )
            for event in history
        ]

    @staticmethod
    def _retry_policy(
        log: EmailDeliveryLog,
        linked_delivery: NotificationDelivery | None,
        notification: Notification | None,
    ) -> tuple[bool, str]:
        if linked_delivery is None or notification is None:
            return False, "not_linked_to_notification"
        if notification.channel != "email":
            return False, "unsupported_channel"
        if log.status == "queued":
            return False, "already_queued"
        return True, "manual_resend_available"

    async def _latest_log_for_notification(self, notification_id: UUID) -> EmailDeliveryLog | None:
        return (
            await self._session.execute(
                select(EmailDeliveryLog)
                .join(
                    NotificationDelivery,
                    NotificationDelivery.email_delivery_log_id == EmailDeliveryLog.id,
                )
                .where(NotificationDelivery.notification_id == notification_id)
                .order_by(NotificationDelivery.created_at.desc(), NotificationDelivery.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
