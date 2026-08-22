"""Canonical Trust & Safety operations."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.deps import CurrentUser
from app.config import Settings
from app.core.constants import Role
from app.core.permissions import Permission, has_permission
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.risk_signal import RiskSignal
from app.models.trust_registry_record import TrustRegistryRecord
from app.models.trust_safety_investigation import TrustSafetyInvestigation
from app.models.trust_safety_investigation_event import TrustSafetyInvestigationEvent
from app.models.trust_safety_investigation_note import TrustSafetyInvestigationNote
from app.models.user import User
from app.models.verification_request import VerificationRequest
from app.models.verification_request_event import VerificationRequestEvent
from app.notifications.contracts import NotificationRequest
from app.schemas.pagination import Page, filter_sort_paginate
from app.schemas.trust_safety import (
    RiskSignalResponse,
    TrustSafetyAddNoteRequest,
    TrustSafetyAssignInvestigationRequest,
    TrustSafetyCreateInvestigationRequest,
    TrustSafetyDismissRequest,
    TrustSafetyInvestigationAssigneeResponse,
    TrustSafetyInvestigationDetailResponse,
    TrustSafetyInvestigationEventResponse,
    TrustSafetyInvestigationListItemResponse,
    TrustSafetyInvestigationNoteResponse,
    TrustSafetyListParams,
    TrustSafetyOverviewSummaryResponse,
    TrustSafetyResolveRequest,
    TrustSafetySubjectContextResponse,
    TrustSafetyUpdateSeverityRequest,
    TrustSafetyUpdateStatusRequest,
)
from app.services.admin_directory_service import AdminDirectoryService
from app.services.notification_service import NotificationService
from app.services.trust_registry_admin_service import TrustRegistryAdminService
from app.services.verification_request_admin_review_service import (
    VerificationRequestAdminReviewService,
)
from app.verification_requests.enums import VerificationRequestStatus

_NEGATIVE_VERIFICATION_STATUSES = {
    VerificationRequestStatus.REJECTED,
    VerificationRequestStatus.UNABLE_TO_VERIFY,
    VerificationRequestStatus.CANCELLED,
}
_TERMINAL_STATUSES = {"resolved", "dismissed"}
_ACTIVE_SIGNAL_STATUS = "active"
_SUBJECT_TYPES = {"user", "verification_request", "trust_registry_record"}
_NON_TERMINAL_TRANSITIONS: dict[str, set[str]] = {
    "open": {"in_review", "awaiting_information"},
    "in_review": {"open", "awaiting_information"},
    "awaiting_information": {"open", "in_review"},
}


class TrustSafetyService:
    """Admin-only Trust & Safety investigations backed by canonical product truth."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._notifications = NotificationService(session, settings)

    async def list_signals(self, params: TrustSafetyListParams) -> Page[RiskSignalResponse]:
        await self._ensure_automatic_signals()
        signals = await self._load_signals()
        signals = self._filter_signals(signals, params)
        rows = [self._to_signal_response(item) for item in signals]
        page = filter_sort_paginate(
            rows,
            params=params,
            search_fields=("signal_type", "subject_type", "summary", "source"),
            status_field="status",
            allowed_sort_fields=("detected_at", "severity", "signal_type", "source"),
            default_sort_by="detected_at",
            force_page_envelope=True,
        )
        if not isinstance(page, Page):
            raise RuntimeError("Trust & Safety signals must return a page envelope")
        return page

    async def list_investigations(
        self,
        params: TrustSafetyListParams,
    ) -> Page[TrustSafetyInvestigationListItemResponse]:
        await self._ensure_automatic_signals()
        investigations = await self._load_investigations()
        investigations = self._filter_investigations(investigations, params)
        rows = [await self._to_list_item(item) for item in investigations]
        page = filter_sort_paginate(
            rows,
            params=params,
            search_fields=("title", "summary", "subject_label", "primary_signal_summary"),
            status_field="status",
            allowed_sort_fields=("created_at", "updated_at", "severity", "title", "status"),
            default_sort_by="updated_at",
            force_page_envelope=True,
        )
        if not isinstance(page, Page):
            raise RuntimeError("Trust & Safety investigations must return a page envelope")
        return page

    async def list_assignees(
        self,
        params: TrustSafetyListParams,
    ) -> Page[TrustSafetyInvestigationAssigneeResponse]:
        page = await AdminDirectoryService(
            self._session,
            self._settings,
        ).list_trust_safety_assignees(params)
        return Page[TrustSafetyInvestigationAssigneeResponse].create(
            items=[
                TrustSafetyInvestigationAssigneeResponse(
                    user_id=item.user_id,
                    full_name=item.full_name,
                    email=item.email,
                    role=item.role,
                )
                for item in page.items
            ],
            total=page.total,
            params=params,
        )

    async def get_detail(
        self,
        actor: CurrentUser,
        investigation_public_id: UUID,
    ) -> TrustSafetyInvestigationDetailResponse:
        investigation = await self._get_required_investigation(investigation_public_id)
        await self._ensure_subject_automatic_signals(
            investigation.subject_type,
            investigation.subject_public_id,
        )
        investigation = await self._get_required_investigation(investigation_public_id)
        subject_label = await self._subject_label(
            investigation.subject_type,
            investigation.subject_public_id,
        )
        assignee = await self._assignee_response(investigation.assigned_admin_user_id)
        return TrustSafetyInvestigationDetailResponse(
            public_id=investigation.public_id,
            title=investigation.title,
            summary=investigation.summary,
            status=investigation.status,  # type: ignore[arg-type]
            severity=investigation.severity,  # type: ignore[arg-type]
            subject_type=investigation.subject_type,  # type: ignore[arg-type]
            subject_public_id=investigation.subject_public_id,
            subject_label=subject_label,
            assignee=assignee,
            created_by_user_id=investigation.created_by_user_id,
            resolved_by_user_id=investigation.resolved_by_user_id,
            resolved_at=investigation.resolved_at,
            resolution_reason=investigation.resolution_reason,
            dismissed_at=investigation.dismissed_at,
            dismissed_by_user_id=investigation.dismissed_by_user_id,
            dismissal_reason=investigation.dismissal_reason,
            created_at=investigation.created_at,
            updated_at=investigation.updated_at,
            signals=[self._to_signal_response(item) for item in investigation.signals],
            notes=[await self._to_note_response(item) for item in investigation.notes],
            timeline=[await self._to_event_response(item) for item in investigation.events],
            subject_context=await self._subject_context(actor, investigation),
        )

    async def create_investigation(
        self,
        actor: CurrentUser,
        payload: TrustSafetyCreateInvestigationRequest,
    ) -> TrustSafetyInvestigationDetailResponse:
        await self._validate_subject(payload.subject_type, payload.subject_public_id)
        await self._ensure_subject_automatic_signals(
            payload.subject_type,
            payload.subject_public_id,
        )
        title = payload.title or await self._default_title(
            payload.subject_type,
            payload.subject_public_id,
            payload.signal_type,
        )
        investigation = TrustSafetyInvestigation(
            subject_type=payload.subject_type,
            subject_public_id=payload.subject_public_id,
            title=title,
            summary=payload.summary,
            status="open",
            severity=payload.severity,
            created_by_user_id=actor.id,
        )
        self._session.add(investigation)
        await self._session.flush()

        attached_signals = await self._attach_existing_subject_signals(investigation)
        manual_signal = RiskSignal(
            signal_type=payload.signal_type,
            subject_type=payload.subject_type,
            subject_public_id=payload.subject_public_id,
            severity=payload.severity,
            source="manual",
            summary=payload.summary,
            metadata_payload={"created_from": "manual_investigation"},
            investigation_id=investigation.id,
            created_by_user_id=actor.id,
        )
        self._session.add(manual_signal)
        if investigation.first_signal_detected_at is None:
            investigation.first_signal_detected_at = datetime.now(tz=UTC)

        await self._append_event(
            investigation,
            actor=actor,
            event_type="investigation_created",
            detail=payload.summary,
            metadata={"manual_signal_type": payload.signal_type},
        )
        for signal in attached_signals:
            await self._append_event(
                investigation,
                actor=actor,
                event_type="signal_attached",
                detail=signal.summary,
                metadata={"signal_public_id": str(signal.public_id)},
            )
        await self._append_event(
            investigation,
            actor=actor,
            event_type="signal_attached",
            detail=manual_signal.summary,
            metadata={"signal_type": payload.signal_type, "source": "manual"},
        )
        await self._notify_created_if_needed(actor, investigation)
        await self._session.commit()
        return await self.get_detail(actor, investigation.public_id)

    async def assign(
        self,
        actor: CurrentUser,
        investigation_public_id: UUID,
        payload: TrustSafetyAssignInvestigationRequest,
    ) -> TrustSafetyInvestigationDetailResponse:
        investigation = await self._get_required_investigation(investigation_public_id)
        assignee = await self._session.scalar(
            select(User).where(User.id == payload.assignee_user_id)
        )
        if assignee is None:
            raise NotFoundError("Assignee not found")
        if not has_permission(assignee.role, Permission.TRUST_SAFETY_READ):
            raise ForbiddenError("Assignee does not have Trust & Safety access")
        investigation.assigned_admin_user_id = assignee.id
        await self._append_event(
            investigation,
            actor=actor,
            event_type="investigation_assigned",
            detail=f"Assigned to {assignee.full_name or assignee.email}",
            metadata={"assignee_user_id": str(assignee.id)},
        )
        await self._notify_assignment(actor, investigation, assignee)
        await self._session.commit()
        return await self.get_detail(actor, investigation.public_id)

    async def update_severity(
        self,
        actor: CurrentUser,
        investigation_public_id: UUID,
        payload: TrustSafetyUpdateSeverityRequest,
    ) -> TrustSafetyInvestigationDetailResponse:
        investigation = await self._get_required_investigation(investigation_public_id)
        previous = investigation.severity
        investigation.severity = payload.severity
        await self._append_event(
            investigation,
            actor=actor,
            event_type="severity_updated",
            detail=f"{previous} → {payload.severity}",
            metadata={"previous_severity": previous, "next_severity": payload.severity},
        )
        await self._session.commit()
        return await self.get_detail(actor, investigation.public_id)

    async def add_note(
        self,
        actor: CurrentUser,
        investigation_public_id: UUID,
        payload: TrustSafetyAddNoteRequest,
    ) -> TrustSafetyInvestigationNoteResponse:
        investigation = await self._get_required_investigation(investigation_public_id)
        note = TrustSafetyInvestigationNote(
            investigation_id=investigation.id,
            author_user_id=actor.id,
            body=payload.body,
            metadata_payload=payload.metadata,
        )
        self._session.add(note)
        await self._session.flush()
        await self._append_event(
            investigation,
            actor=actor,
            event_type="note_added",
            detail=payload.body,
            metadata={"note_public_id": str(note.public_id)},
        )
        await self._session.commit()
        return await self._to_note_response(note)

    async def update_status(
        self,
        actor: CurrentUser,
        investigation_public_id: UUID,
        payload: TrustSafetyUpdateStatusRequest,
    ) -> TrustSafetyInvestigationDetailResponse:
        investigation = await self._get_required_investigation(investigation_public_id)
        if investigation.status in _TERMINAL_STATUSES:
            raise ConflictError(
                "Resolved or dismissed investigations cannot change workflow state"
            )
        allowed = _NON_TERMINAL_TRANSITIONS.get(investigation.status, set())
        if payload.status not in allowed:
            raise ConflictError("Requested Trust & Safety state transition is not allowed")
        previous = investigation.status
        investigation.status = payload.status
        await self._append_event(
            investigation,
            actor=actor,
            event_type="status_changed",
            detail=f"{previous} → {payload.status}",
            metadata={
                "previous_status": previous,
                "next_status": payload.status,
                "reason": payload.reason,
            },
        )
        await self._session.commit()
        return await self.get_detail(actor, investigation.public_id)

    async def resolve(
        self,
        actor: CurrentUser,
        investigation_public_id: UUID,
        payload: TrustSafetyResolveRequest,
    ) -> TrustSafetyInvestigationDetailResponse:
        investigation = await self._get_required_investigation(investigation_public_id)
        if investigation.status in _TERMINAL_STATUSES:
            raise ConflictError("Investigation is already closed")
        now = datetime.now(tz=UTC)
        investigation.status = "resolved"
        investigation.resolution_reason = payload.reason
        investigation.resolved_at = now
        investigation.resolved_by_user_id = actor.id
        for signal in investigation.signals:
            signal.status = "resolved"
            signal.resolved_at = now
            signal.resolved_by_user_id = actor.id
        await self._append_event(
            investigation,
            actor=actor,
            event_type="resolved",
            detail=payload.reason,
            metadata={},
        )
        await self._session.commit()
        return await self.get_detail(actor, investigation.public_id)

    async def dismiss(
        self,
        actor: CurrentUser,
        investigation_public_id: UUID,
        payload: TrustSafetyDismissRequest,
    ) -> TrustSafetyInvestigationDetailResponse:
        investigation = await self._get_required_investigation(investigation_public_id)
        if investigation.status in _TERMINAL_STATUSES:
            raise ConflictError("Investigation is already closed")
        now = datetime.now(tz=UTC)
        investigation.status = "dismissed"
        investigation.dismissal_reason = payload.reason
        investigation.dismissed_at = now
        investigation.dismissed_by_user_id = actor.id
        for signal in investigation.signals:
            signal.status = "resolved"
            signal.resolved_at = now
            signal.resolved_by_user_id = actor.id
        await self._append_event(
            investigation,
            actor=actor,
            event_type="dismissed",
            detail=payload.reason,
            metadata={},
        )
        await self._session.commit()
        return await self.get_detail(actor, investigation.public_id)

    async def summary(self) -> TrustSafetyOverviewSummaryResponse:
        await self._ensure_automatic_signals()
        investigations = await self._load_investigations()
        open_investigations = sum(
            item.status not in _TERMINAL_STATUSES for item in investigations
        )
        high_or_critical = sum(item.severity in {"high", "critical"} for item in investigations)
        unassigned = sum(
            item.assigned_admin_user_id is None
            for item in investigations
            if item.status not in _TERMINAL_STATUSES
        )
        active_signals = await self._session.scalar(
            select(func.count())
            .select_from(RiskSignal)
            .where(RiskSignal.status == _ACTIVE_SIGNAL_STATUS)
        )
        return TrustSafetyOverviewSummaryResponse(
            open_investigations=open_investigations,
            high_or_critical_investigations=high_or_critical,
            unassigned_investigations=unassigned,
            active_signals=int(active_signals or 0),
        )

    async def _get_required_investigation(
        self,
        investigation_public_id: UUID,
    ) -> TrustSafetyInvestigation:
        stmt = (
            select(TrustSafetyInvestigation)
            .options(
                selectinload(TrustSafetyInvestigation.signals),
                selectinload(TrustSafetyInvestigation.notes),
                selectinload(TrustSafetyInvestigation.events),
            )
            .where(TrustSafetyInvestigation.public_id == investigation_public_id)
        )
        investigation = (await self._session.execute(stmt)).scalars().unique().one_or_none()
        if investigation is None:
            raise NotFoundError("Trust & Safety investigation not found")
        return investigation

    async def _load_investigations(self) -> list[TrustSafetyInvestigation]:
        stmt = (
            select(TrustSafetyInvestigation)
            .options(
                selectinload(TrustSafetyInvestigation.signals),
                selectinload(TrustSafetyInvestigation.notes),
                selectinload(TrustSafetyInvestigation.events),
            )
            .order_by(TrustSafetyInvestigation.updated_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().unique().all())

    async def _load_signals(self) -> list[RiskSignal]:
        stmt = (
            select(RiskSignal)
            .options(selectinload(RiskSignal.investigation))
            .order_by(RiskSignal.detected_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    def _filter_signals(
        self,
        items: list[RiskSignal],
        params: TrustSafetyListParams,
    ) -> list[RiskSignal]:
        filtered = items
        if params.subject_type:
            accepted = {
                value.strip() for value in params.subject_type.split(",") if value.strip()
            }
            filtered = [item for item in filtered if item.subject_type in accepted]
        if params.subject_public_id:
            filtered = [
                item
                for item in filtered
                if item.subject_public_id == params.subject_public_id
            ]
        if params.severity:
            accepted = {value.strip() for value in params.severity.split(",") if value.strip()}
            filtered = [item for item in filtered if item.severity in accepted]
        if params.source:
            accepted = {value.strip() for value in params.source.split(",") if value.strip()}
            filtered = [item for item in filtered if item.source in accepted]
        if params.status:
            accepted = {value.strip() for value in params.status.split(",") if value.strip()}
            filtered = [item for item in filtered if item.status in accepted]
        return filtered

    def _filter_investigations(
        self,
        items: list[TrustSafetyInvestigation],
        params: TrustSafetyListParams,
    ) -> list[TrustSafetyInvestigation]:
        filtered = items
        if params.subject_type:
            accepted = {
                value.strip() for value in params.subject_type.split(",") if value.strip()
            }
            filtered = [item for item in filtered if item.subject_type in accepted]
        if params.subject_public_id:
            filtered = [
                item
                for item in filtered
                if item.subject_public_id == params.subject_public_id
            ]
        if params.severity:
            accepted = {value.strip() for value in params.severity.split(",") if value.strip()}
            filtered = [item for item in filtered if item.severity in accepted]
        if params.status:
            accepted = {value.strip() for value in params.status.split(",") if value.strip()}
            filtered = [item for item in filtered if item.status in accepted]
        if params.assignee_user_id is not None:
            filtered = [
                item
                for item in filtered
                if item.assigned_admin_user_id == params.assignee_user_id
            ]
        return filtered

    async def _to_list_item(
        self,
        investigation: TrustSafetyInvestigation,
    ) -> TrustSafetyInvestigationListItemResponse:
        primary_signal = investigation.signals[0] if investigation.signals else None
        return TrustSafetyInvestigationListItemResponse(
            public_id=investigation.public_id,
            title=investigation.title,
            summary=investigation.summary,
            status=investigation.status,  # type: ignore[arg-type]
            severity=investigation.severity,  # type: ignore[arg-type]
            subject_type=investigation.subject_type,  # type: ignore[arg-type]
            subject_public_id=investigation.subject_public_id,
            subject_label=await self._subject_label(
                investigation.subject_type,
                investigation.subject_public_id,
            ),
            primary_signal_summary=primary_signal.summary if primary_signal is not None else None,
            assignee=await self._assignee_response(investigation.assigned_admin_user_id),
            created_at=investigation.created_at,
            updated_at=investigation.updated_at,
        )

    async def _to_note_response(
        self,
        note: TrustSafetyInvestigationNote,
    ) -> TrustSafetyInvestigationNoteResponse:
        author = None
        if note.author_user_id is not None:
            author = await self._session.scalar(select(User).where(User.id == note.author_user_id))
        return TrustSafetyInvestigationNoteResponse(
            public_id=note.public_id,
            author_user_id=note.author_user_id,
            author_display_name=(
                author.full_name
                if author and author.full_name
                else (author.email if author else None)
            ),
            body=note.body,
            metadata=dict(note.metadata_payload or {}),
            created_at=note.created_at,
        )

    async def _to_event_response(
        self,
        event: TrustSafetyInvestigationEvent,
    ) -> TrustSafetyInvestigationEventResponse:
        actor = None
        if event.actor_user_id is not None:
            actor = await self._session.scalar(select(User).where(User.id == event.actor_user_id))
        return TrustSafetyInvestigationEventResponse(
            public_id=event.public_id,
            actor_user_id=event.actor_user_id,
            actor_display_name=(
                actor.full_name if actor and actor.full_name else (actor.email if actor else None)
            ),
            event_type=event.event_type,
            detail=event.detail,
            metadata=dict(event.metadata_payload or {}),
            created_at=event.created_at,
        )

    def _to_signal_response(self, signal: RiskSignal) -> RiskSignalResponse:
        investigation_public_id = None
        if signal.investigation is not None:
            investigation_public_id = signal.investigation.public_id
        return RiskSignalResponse(
            public_id=signal.public_id,
            signal_type=signal.signal_type,
            subject_type=signal.subject_type,  # type: ignore[arg-type]
            subject_public_id=signal.subject_public_id,
            severity=signal.severity,  # type: ignore[arg-type]
            source=signal.source,
            summary=signal.summary,
            metadata=dict(signal.metadata_payload or {}),
            status=signal.status,  # type: ignore[arg-type]
            detected_at=signal.detected_at,
            resolved_at=signal.resolved_at,
            investigation_public_id=investigation_public_id,
        )

    async def _assignee_response(
        self,
        assignee_user_id: UUID | None,
    ) -> TrustSafetyInvestigationAssigneeResponse | None:
        if assignee_user_id is None:
            return None
        assignee = await self._session.scalar(select(User).where(User.id == assignee_user_id))
        if assignee is None:
            return None
        return TrustSafetyInvestigationAssigneeResponse(
            user_id=assignee.id,
            full_name=assignee.full_name,
            email=assignee.email,
            role=assignee.role,
        )

    async def _subject_context(
        self,
        actor: CurrentUser,
        investigation: TrustSafetyInvestigation,
    ) -> TrustSafetySubjectContextResponse:
        if investigation.subject_type == "user":
            user_detail = await AdminDirectoryService(
                self._session,
                self._settings,
            ).get_user_detail(actor, investigation.subject_public_id)
            return TrustSafetySubjectContextResponse(user=user_detail)
        if investigation.subject_type == "verification_request":
            review_service = VerificationRequestAdminReviewService(self._session, self._settings)
            detail = await review_service.get_detail(investigation.subject_public_id)
            timeline = await review_service.get_timeline(
                investigation.subject_public_id,
                TrustSafetyListParams(page=1, page_size=100),
            )
            return TrustSafetySubjectContextResponse(
                verification=detail,
                verification_timeline=timeline,
            )
        registry_detail = await TrustRegistryAdminService(self._session).get_detail(
            investigation.subject_public_id
        )
        return TrustSafetySubjectContextResponse(registry=registry_detail)

    async def _subject_label(self, subject_type: str, subject_public_id: UUID) -> str:
        if subject_type == "user":
            user = await self._session.scalar(
                select(User).where(
                    User.id == subject_public_id,
                    User.role == Role.USER.value,
                )
            )
            if user is None:
                return str(subject_public_id)
            return user.full_name or user.email
        if subject_type == "verification_request":
            request = await self._session.scalar(
                select(VerificationRequest).where(
                    VerificationRequest.public_id == subject_public_id
                )
            )
            if request is None:
                return str(subject_public_id)
            request_type = getattr(request.request_type, "value", request.request_type)
            return f"{request.subject_name} • {str(request_type).replace('_', ' ')}"
        record = await self._session.scalar(
            select(TrustRegistryRecord).where(TrustRegistryRecord.public_id == subject_public_id)
        )
        if record is None:
            return str(subject_public_id)
        return record.display_name or record.legal_name

    async def _validate_subject(self, subject_type: str, subject_public_id: UUID) -> None:
        if subject_type not in _SUBJECT_TYPES:
            raise NotFoundError("Unsupported Trust & Safety subject type")
        if subject_type == "user":
            user = await self._session.scalar(
                select(User).where(User.id == subject_public_id, User.role == Role.USER.value)
            )
            if user is None:
                raise NotFoundError("Candidate not found")
            return
        if subject_type == "verification_request":
            request = await self._session.scalar(
                select(VerificationRequest).where(
                    VerificationRequest.public_id == subject_public_id
                )
            )
            if request is None:
                raise NotFoundError("Verification request not found")
            return
        record = await self._session.scalar(
            select(TrustRegistryRecord).where(
                TrustRegistryRecord.public_id == subject_public_id,
                TrustRegistryRecord.deleted_at.is_(None),
            )
        )
        if record is None:
            raise NotFoundError("Trust Registry record not found")

    async def _default_title(
        self,
        subject_type: str,
        subject_public_id: UUID,
        signal_type: str,
    ) -> str:
        label = await self._subject_label(subject_type, subject_public_id)
        return f"{signal_type.replace('_', ' ').strip().title()} — {label}"

    async def _attach_existing_subject_signals(
        self,
        investigation: TrustSafetyInvestigation,
    ) -> list[RiskSignal]:
        stmt = select(RiskSignal).where(
            RiskSignal.subject_type == investigation.subject_type,
            RiskSignal.subject_public_id == investigation.subject_public_id,
            RiskSignal.status == _ACTIVE_SIGNAL_STATUS,
            RiskSignal.investigation_id.is_(None),
        )
        signals = list((await self._session.execute(stmt)).scalars().all())
        for signal in signals:
            signal.investigation_id = investigation.id
            if investigation.first_signal_detected_at is None:
                investigation.first_signal_detected_at = signal.detected_at
        return signals

    async def _append_event(
        self,
        investigation: TrustSafetyInvestigation,
        *,
        actor: CurrentUser,
        event_type: str,
        detail: str | None,
        metadata: dict[str, object],
    ) -> None:
        event = TrustSafetyInvestigationEvent(
            investigation_id=investigation.id,
            actor_user_id=actor.id,
            event_type=event_type,
            detail=detail,
            metadata_payload=metadata,
        )
        self._session.add(event)
        await self._session.flush()

    async def _ensure_automatic_signals(self) -> None:
        await self._sync_repeated_negative_verification_signals()
        await self._sync_repeated_correction_cycle_signals()

    async def _ensure_subject_automatic_signals(
        self,
        subject_type: str,
        subject_public_id: UUID,
    ) -> None:
        if subject_type == "user":
            await self._sync_repeated_negative_verification_signals(user_ids={subject_public_id})
        if subject_type == "verification_request":
            await self._sync_repeated_correction_cycle_signals(
                verification_public_ids={subject_public_id}
            )

    async def _sync_repeated_negative_verification_signals(
        self,
        *,
        user_ids: set[UUID] | None = None,
    ) -> None:
        stmt = (
            select(VerificationRequest.subject_user_id, VerificationRequest.status)
            .where(
                VerificationRequest.subject_user_id.is_not(None),
                VerificationRequest.status.in_(_NEGATIVE_VERIFICATION_STATUSES),
            )
        )
        if user_ids:
            stmt = stmt.where(VerificationRequest.subject_user_id.in_(user_ids))
        rows = (await self._session.execute(stmt)).all()
        counts: dict[UUID, Counter[str]] = {}
        for user_id, status in rows:
            if user_id is None:
                continue
            bucket = counts.setdefault(user_id, Counter())
            bucket[str(getattr(status, "value", status))] += 1
        active_fingerprints: set[str] = set()
        for user_id, bucket in counts.items():
            total = sum(bucket.values())
            if total < 2:
                continue
            fingerprint = f"user-negative-outcomes:{user_id}"
            active_fingerprints.add(fingerprint)
            severity = "high" if total >= 3 else "medium"
            summary = (
                f"{total} verification requests for this candidate ended in rejected, "
                "unable-to-verify, or cancelled outcomes."
            )
            await self._upsert_signal(
                fingerprint=fingerprint,
                signal_type="repeated_negative_verification_outcomes",
                subject_type="user",
                subject_public_id=user_id,
                severity=severity,
                source="verification_outcomes",
                summary=summary,
                metadata={
                    "negative_outcome_count": total,
                    "status_breakdown": dict(bucket),
                },
            )
        await self._resolve_missing_automatic_signals(
            prefix="user-negative-outcomes:",
            active_fingerprints=active_fingerprints,
            subject_type="user",
            subject_public_ids=user_ids,
        )

    async def _sync_repeated_correction_cycle_signals(
        self,
        *,
        verification_public_ids: set[UUID] | None = None,
    ) -> None:
        stmt = (
            select(
                VerificationRequest.public_id,
                func.count(VerificationRequestEvent.id),
            )
            .join(
                VerificationRequestEvent,
                VerificationRequestEvent.verification_request_id == VerificationRequest.id,
            )
            .where(VerificationRequestEvent.event_type == "admin_requested_corrections")
            .group_by(VerificationRequest.public_id)
        )
        if verification_public_ids:
            stmt = stmt.where(VerificationRequest.public_id.in_(verification_public_ids))
        rows = (await self._session.execute(stmt)).all()
        active_fingerprints: set[str] = set()
        for request_public_id, count in rows:
            total = int(count or 0)
            if total < 2:
                continue
            fingerprint = f"verification-corrections:{request_public_id}"
            active_fingerprints.add(fingerprint)
            severity = "high" if total >= 3 else "medium"
            summary = (
                f"This verification request has entered {total} admin correction cycles."
            )
            await self._upsert_signal(
                fingerprint=fingerprint,
                signal_type="repeated_correction_cycles",
                subject_type="verification_request",
                subject_public_id=request_public_id,
                severity=severity,
                source="verification_workflow",
                summary=summary,
                metadata={"correction_cycle_count": total},
            )
        await self._resolve_missing_automatic_signals(
            prefix="verification-corrections:",
            active_fingerprints=active_fingerprints,
            subject_type="verification_request",
            subject_public_ids=verification_public_ids,
        )

    async def _upsert_signal(
        self,
        *,
        fingerprint: str,
        signal_type: str,
        subject_type: str,
        subject_public_id: UUID,
        severity: str,
        source: str,
        summary: str,
        metadata: dict[str, object],
    ) -> RiskSignal:
        signal = await self._session.scalar(
            select(RiskSignal).where(RiskSignal.fingerprint == fingerprint)
        )
        if signal is None:
            signal = RiskSignal(
                fingerprint=fingerprint,
                signal_type=signal_type,
                subject_type=subject_type,
                subject_public_id=subject_public_id,
                severity=severity,
                source=source,
                summary=summary,
                metadata_payload=metadata,
                status=_ACTIVE_SIGNAL_STATUS,
            )
            self._session.add(signal)
            await self._session.flush()
            return signal
        signal.signal_type = signal_type
        signal.subject_type = subject_type
        signal.subject_public_id = subject_public_id
        signal.severity = severity
        signal.source = source
        signal.summary = summary
        signal.metadata_payload = metadata
        signal.status = _ACTIVE_SIGNAL_STATUS
        signal.resolved_at = None
        signal.resolved_by_user_id = None
        await self._session.flush()
        return signal

    async def _resolve_missing_automatic_signals(
        self,
        *,
        prefix: str,
        active_fingerprints: set[str],
        subject_type: str,
        subject_public_ids: set[UUID] | None = None,
    ) -> None:
        stmt = select(RiskSignal).where(
            RiskSignal.subject_type == subject_type,
            RiskSignal.fingerprint.is_not(None),
            RiskSignal.fingerprint.like(f"{prefix}%"),
            RiskSignal.status == _ACTIVE_SIGNAL_STATUS,
        )
        if subject_public_ids:
            stmt = stmt.where(RiskSignal.subject_public_id.in_(subject_public_ids))
        rows = (await self._session.execute(stmt)).scalars().all()
        now = datetime.now(tz=UTC)
        for signal in rows:
            if signal.fingerprint in active_fingerprints:
                continue
            signal.status = "resolved"
            signal.resolved_at = now
            signal.resolved_by_user_id = None

    async def _notify_created_if_needed(
        self,
        actor: CurrentUser,
        investigation: TrustSafetyInvestigation,
    ) -> None:
        if investigation.severity not in {"high", "critical"}:
            return
        await self._notifications.create_and_dispatch_for_admin_roles(
            NotificationRequest(
                event_type="trust_safety_investigation_created",
                channel="in_app",
                notification_type="trust_safety",
                priority="high" if investigation.severity == "critical" else "normal",
                recipient_user_id=actor.id,
                recipient_email=actor.email,
                template_key="admin_in_app",
                category="security",
                title="Trust & Safety investigation created",
                body=investigation.title,
                dedupe_key=f"trust-safety-created:{investigation.public_id}",
                payload={
                    "investigation_public_id": str(investigation.public_id),
                    "severity": investigation.severity,
                },
                metadata={"subject_type": investigation.subject_type},
            ),
            actor_user_id=actor.id,
            exclude_user_ids=frozenset({actor.id}),
        )

    async def _notify_assignment(
        self,
        actor: CurrentUser,
        investigation: TrustSafetyInvestigation,
        assignee: User,
    ) -> None:
        await self._notifications.create_and_dispatch(
            NotificationRequest(
                event_type="trust_safety_investigation_assigned",
                channel="in_app",
                notification_type="trust_safety",
                priority="high" if investigation.severity in {"high", "critical"} else "normal",
                recipient_user_id=assignee.id,
                recipient_email=assignee.email,
                template_key="admin_in_app",
                category="security",
                title="Trust & Safety investigation assigned",
                body=investigation.title,
                dedupe_key=f"trust-safety-assigned:{investigation.public_id}:{assignee.id}",
                payload={"investigation_public_id": str(investigation.public_id)},
                metadata={"assigned_by_user_id": str(actor.id)},
            ),
            actor_user_id=actor.id,
        )
