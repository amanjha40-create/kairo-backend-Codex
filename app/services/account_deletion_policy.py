"""Erase private payloads while retaining restricted, non-content decisions."""

from sqlalchemy import delete, or_, select, update

from app.models import (
    DocumentSharePack,
    EmailDeliveryLog,
    EmployerVerificationRequest,
    InstitutionVerificationRequest,
    Notification,
    TrustInvitationEvent,
    UserAccountEvent,
    UserAdminNote,
    VerificationAuditEvent,
    VerificationConnectorRun,
    VerificationRequest,
    VerificationRequestEvent,
    VerificationRequestReview,
    VerificationReviewCorrection,
    VerificationReviewNote,
)


async def revoke_and_scrub_related(session, user_id, snapshot, now):
    for model in (UserAccountEvent, VerificationAuditEvent):
        await session.execute(
            update(model).where(model.actor_user_id == user_id).values(actor_display_name=None)
        )
    await session.execute(
        delete(DocumentSharePack).where(DocumentSharePack.owner_user_id == user_id)
    )
    request_ids = (
        snapshot.verification_request_ids_to_purge | snapshot.verification_request_ids_to_retain
    )
    public_ids = [
        str(value)
        for value in (
            await session.scalars(
                select(VerificationRequest.public_id).where(VerificationRequest.id.in_(request_ids))
            )
        ).all()
    ]
    # Remove queued/rendered copies of Candidate content sent to other recipients,
    # scoped by canonical request/record IDs, not a broad textual PII search.
    for model in (Notification, EmailDeliveryLog):
        await session.execute(
            delete(model).where(
                or_(
                    model.payload["verification_request_public_id"].astext.in_(public_ids),
                    model.payload["employment_id"].astext.in_(
                        [str(value) for value in snapshot.employment_ids]
                    ),
                )
            )
        )
    employer_scope = or_(
        EmployerVerificationRequest.verification_request_id.in_(request_ids),
        EmployerVerificationRequest.employment_id.in_(snapshot.employment_ids),
    )
    await session.execute(
        update(EmployerVerificationRequest)
        .where(employer_scope)
        .values(
            revoked_at=now,
            expires_at=now,
            remarks=None,
            response_metadata={},
        )
    )
    # This FK is RESTRICT. Remove outreach attached to requests being removed.
    await session.execute(
        delete(EmployerVerificationRequest).where(
            EmployerVerificationRequest.verification_request_id.in_(
                snapshot.verification_request_ids_to_purge
            )
        )
    )
    await session.execute(
        update(InstitutionVerificationRequest)
        .where(InstitutionVerificationRequest.verification_request_id.in_(request_ids))
        .values(revoked_at=now, expires_at=now, response_note=None, response_metadata={})
    )
    await session.execute(
        update(VerificationRequestEvent)
        .where(VerificationRequestEvent.verification_request_id.in_(request_ids))
        .values(metadata_payload={})
    )
    reviews = select(VerificationRequestReview.id).where(
        VerificationRequestReview.verification_request_id.in_(request_ids)
    )
    await session.execute(
        update(VerificationReviewNote)
        .where(VerificationReviewNote.verification_request_review_id.in_(reviews))
        .values(body="Content erased after account deletion", metadata_payload={})
    )
    await session.execute(
        update(VerificationReviewCorrection)
        .where(VerificationReviewCorrection.verification_request_review_id.in_(reviews))
        .values(request_text="Content erased after account deletion", guidance={})
    )
    await session.execute(
        update(VerificationRequestReview)
        .where(VerificationRequestReview.verification_request_id.in_(request_ids))
        .values(decision_summary=None)
    )
    await session.execute(
        update(VerificationConnectorRun)
        .where(VerificationConnectorRun.verification_request_id.in_(request_ids))
        .values(normalized_result={}, raw_metadata={}, evidence_references=[], error={})
    )
    await session.execute(
        update(VerificationAuditEvent)
        .where(VerificationAuditEvent.employment_id.in_(snapshot.employment_ids))
        .values(actor_display_name=None, metadata_payload={})
    )
    await session.execute(
        update(UserAccountEvent)
        .where(UserAccountEvent.user_id == user_id)
        .values(title="Account event", detail=None, actor_display_name=None, metadata_payload={})
    )
    await session.execute(delete(UserAdminNote).where(UserAdminNote.user_id == user_id))


async def scrub_invitation_events(session, invitation_id):
    await session.execute(
        update(TrustInvitationEvent)
        .where(TrustInvitationEvent.invitation_id == invitation_id)
        .values(metadata_payload={})
    )
