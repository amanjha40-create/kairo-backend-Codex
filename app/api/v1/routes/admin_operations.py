"""Permission-separated Admin Operations V1.1 routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import (
    get_admin_operations_service,
    get_resume_review_service,
    get_resume_service,
    get_user_document_service,
)
from app.auth.deps import require_permission
from app.core.permissions import Permission
from app.resumes.review_schemas import (
    ImportBatchResponse,
    ReviewImportRequest,
    ReviewItemResponse,
    ReviewItemUpdateRequest,
    ReviewPlanResponse,
    ReviewSessionResponse,
    ReviewValidateRequest,
)
from app.resumes.schemas import (
    ResumeCompleteUploadRequest,
    ResumeParsedResultResponse,
    ResumeProcessResponse,
    ResumeResponse,
    ResumeUploadIntentRequest,
    ResumeUploadIntentResponse,
)
from app.schemas.admin_operations import (
    AdminCandidateResponse,
    AdminCareerMutationRequest,
    AdminCareerMutationResponse,
    AdminCreateCandidateRequest,
    AdminFirstHRInvitationRequest,
    AdminFirstHRInvitationResponse,
    AdminOrganizationCreateRequest,
    AdminOrganizationCreateResponse,
    AdminProfileMutationRequest,
    AdminProfileMutationResponse,
    CandidateActivationResponse,
    CandidateActivationTokenRequest,
    CandidateActivationValidationResponse,
    CandidateClaimRequest,
    CandidateClaimResponse,
    CandidateProvenanceConfirmationRequest,
    CandidateProvenanceConfirmationResponse,
    CourtCheckResponse,
    CourtCheckUpdateRequest,
    CourtCheckWriteRequest,
    InPersonVerificationCreateRequest,
    InPersonVerificationResponse,
)
from app.schemas.user_document import (
    UserDocumentCompleteUploadRequest,
    UserDocumentResponse,
    UserDocumentUploadIntentRequest,
    UserDocumentUploadIntentResponse,
)
from app.services.admin_operations_service import AdminOperationsService
from app.services.resume_review_service import ResumeReviewService
from app.services.resume_service import ResumeService
from app.services.user_document_service import UserDocumentService

router = APIRouter(prefix="/admin/operations", tags=["admin-operations"])
activation_router = APIRouter(prefix="/candidate-activations", tags=["candidate-activation"])
candidate_router = APIRouter(prefix="/candidate", tags=["candidate-profile-provenance"])


def _permission(permission: Permission):
    return Depends(require_permission(permission))


@router.post(
    "/candidates",
    response_model=AdminCandidateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_assisted_candidate(
    payload: AdminCreateCandidateRequest,
    actor: Annotated[CurrentUser, _permission(Permission.CREATE_PERSON)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> AdminCandidateResponse:
    return await service.create_candidate(actor.id, payload)


@router.get("/candidates/{candidate_id}", response_model=AdminCandidateResponse)
async def get_assisted_candidate_status(
    candidate_id: UUID,
    _: Annotated[CurrentUser, _permission(Permission.CREATE_PERSON)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> AdminCandidateResponse:
    return await service.candidate_status(candidate_id)


@router.post(
    "/candidates/{candidate_id}/activation",
    response_model=CandidateActivationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_candidate_activation(
    candidate_id: UUID,
    actor: Annotated[CurrentUser, _permission(Permission.SEND_CANDIDATE_ACTIVATION)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> CandidateActivationResponse:
    return await service.send_candidate_activation(actor.id, candidate_id, resend=False)


@router.post(
    "/candidates/{candidate_id}/activation/resend",
    response_model=CandidateActivationResponse,
)
async def resend_candidate_activation(
    candidate_id: UUID,
    actor: Annotated[CurrentUser, _permission(Permission.SEND_CANDIDATE_ACTIVATION)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> CandidateActivationResponse:
    return await service.send_candidate_activation(actor.id, candidate_id, resend=True)


@activation_router.post("/validate", response_model=CandidateActivationValidationResponse)
async def validate_candidate_activation(
    payload: CandidateActivationTokenRequest,
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> CandidateActivationValidationResponse:
    return await service.validate_candidate_activation(payload.token)


@activation_router.post("/claim", response_model=CandidateClaimResponse)
async def claim_candidate_account(
    payload: CandidateClaimRequest,
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> CandidateClaimResponse:
    return await service.claim_candidate_account(payload)


@router.patch(
    "/candidates/{candidate_id}/profile", response_model=AdminProfileMutationResponse
)
async def update_assisted_candidate_profile(
    candidate_id: UUID,
    payload: AdminProfileMutationRequest,
    actor: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> AdminProfileMutationResponse:
    return await service.update_candidate_profile(actor.id, candidate_id, payload)


@router.post(
    "/candidates/{candidate_id}/career",
    response_model=AdminCareerMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_assisted_candidate_career_record(
    candidate_id: UUID,
    payload: AdminCareerMutationRequest,
    actor: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> AdminCareerMutationResponse:
    return await service.mutate_candidate_career(actor.id, candidate_id, payload)


@router.patch(
    "/candidates/{candidate_id}/career/{record_id}",
    response_model=AdminCareerMutationResponse,
)
async def update_assisted_candidate_career_record(
    candidate_id: UUID,
    record_id: UUID,
    payload: AdminCareerMutationRequest,
    actor: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> AdminCareerMutationResponse:
    return await service.mutate_candidate_career(
        actor.id, candidate_id, payload, record_id=record_id
    )


@candidate_router.post(
    "/profile/provenance/confirm", response_model=CandidateProvenanceConfirmationResponse
)
async def confirm_assisted_profile_provenance(
    payload: CandidateProvenanceConfirmationRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> CandidateProvenanceConfirmationResponse:
    return await service.confirm_candidate_provenance(current.id, payload)


# Resume/CV routes deliberately delegate to the existing Candidate parser/review/import services.
@router.post(
    "/candidates/{candidate_id}/resumes/upload-intent",
    response_model=ResumeUploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_resume_upload_intent(
    candidate_id: UUID,
    payload: ResumeUploadIntentRequest,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    resumes: Annotated[ResumeService, Depends(get_resume_service)],
) -> ResumeUploadIntentResponse:
    await admin.candidate_status(candidate_id)
    return await resumes.create_upload_intent(candidate_id, payload)


@router.post(
    "/candidates/{candidate_id}/resumes/{resume_id}/complete-upload",
    response_model=ResumeResponse,
)
async def complete_admin_resume_upload(
    candidate_id: UUID,
    resume_id: UUID,
    payload: ResumeCompleteUploadRequest,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    resumes: Annotated[ResumeService, Depends(get_resume_service)],
) -> ResumeResponse:
    await admin.candidate_status(candidate_id)
    return await resumes.complete_upload(candidate_id, resume_id, payload)


@router.post(
    "/candidates/{candidate_id}/resumes/{resume_id}/process",
    response_model=ResumeProcessResponse,
)
async def process_admin_resume(
    candidate_id: UUID,
    resume_id: UUID,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    resumes: Annotated[ResumeService, Depends(get_resume_service)],
) -> ResumeProcessResponse:
    await admin.candidate_status(candidate_id)
    return await resumes.process(candidate_id, resume_id)


@router.get(
    "/candidates/{candidate_id}/resumes/{resume_id}/parsed-result",
    response_model=ResumeParsedResultResponse,
)
async def get_admin_resume_parsed_result(
    candidate_id: UUID,
    resume_id: UUID,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    resumes: Annotated[ResumeService, Depends(get_resume_service)],
) -> ResumeParsedResultResponse:
    await admin.candidate_status(candidate_id)
    return await resumes.parsed_result(candidate_id, resume_id)


@router.post(
    "/candidates/{candidate_id}/resumes/{resume_id}/review-session",
    response_model=ReviewSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_resume_review(
    candidate_id: UUID,
    resume_id: UUID,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    reviews: Annotated[ResumeReviewService, Depends(get_resume_review_service)],
) -> ReviewSessionResponse:
    await admin.candidate_status(candidate_id)
    return await reviews.create(candidate_id, resume_id)


@router.patch(
    "/candidates/{candidate_id}/resume-reviews/{review_id}/items/{item_id}",
    response_model=ReviewItemResponse,
)
async def update_admin_resume_review_item(
    candidate_id: UUID,
    review_id: UUID,
    item_id: UUID,
    payload: ReviewItemUpdateRequest,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    reviews: Annotated[ResumeReviewService, Depends(get_resume_review_service)],
) -> ReviewItemResponse:
    await admin.candidate_status(candidate_id)
    return await reviews.update_item(candidate_id, review_id, item_id, payload)


@router.post(
    "/candidates/{candidate_id}/resume-reviews/{review_id}/validate",
    response_model=ReviewPlanResponse,
)
async def validate_admin_resume_review(
    candidate_id: UUID,
    review_id: UUID,
    payload: ReviewValidateRequest,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    reviews: Annotated[ResumeReviewService, Depends(get_resume_review_service)],
) -> ReviewPlanResponse:
    await admin.candidate_status(candidate_id)
    return await reviews.validate(candidate_id, review_id, payload)


@router.post(
    "/candidates/{candidate_id}/resume-reviews/{review_id}/import",
    response_model=ImportBatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_admin_resume_review(
    candidate_id: UUID,
    review_id: UUID,
    payload: ReviewImportRequest,
    actor: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    reviews: Annotated[ResumeReviewService, Depends(get_resume_review_service)],
) -> ImportBatchResponse:
    await admin.candidate_status(candidate_id)
    batch = await reviews.import_review(
        candidate_id,
        review_id,
        payload,
        confirmed_by_user_id=actor.id,
        confirmation_source="admin_confirmed_for_profile",
        provenance_source="cv_extracted",
    )
    await admin.record_cv_import_audit(actor.id, candidate_id, batch)
    return batch


@router.post(
    "/candidates/{candidate_id}/evidence/upload-intent",
    response_model=UserDocumentUploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_evidence_upload_intent(
    candidate_id: UUID,
    payload: UserDocumentUploadIntentRequest,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_COURT_CHECK)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    documents: Annotated[UserDocumentService, Depends(get_user_document_service)],
) -> UserDocumentUploadIntentResponse:
    """Reuse the private user-document pipeline for managed-person evidence."""

    await admin.candidate_status(candidate_id)
    return await documents.create_upload_intent(candidate_id, payload)


@router.post(
    "/candidates/{candidate_id}/evidence/{document_id}/complete-upload",
    response_model=UserDocumentResponse,
)
async def complete_admin_evidence_upload(
    candidate_id: UUID,
    document_id: UUID,
    payload: UserDocumentCompleteUploadRequest,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_COURT_CHECK)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    documents: Annotated[UserDocumentService, Depends(get_user_document_service)],
) -> UserDocumentResponse:
    await admin.candidate_status(candidate_id)
    document = await documents.complete_upload(
        candidate_id, document_id, payload.checksum_sha256
    )
    return UserDocumentResponse.model_validate(document)


@router.post(
    "/organizations",
    response_model=AdminOrganizationCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_organization(
    payload: AdminOrganizationCreateRequest,
    actor: Annotated[CurrentUser, _permission(Permission.CREATE_ORGANIZATION)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> AdminOrganizationCreateResponse:
    return await service.create_organization(actor.id, payload)


@router.post(
    "/organizations/{org_public_id}/first-hr-invitations",
    response_model=AdminFirstHRInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_first_hr(
    org_public_id: UUID,
    payload: AdminFirstHRInvitationRequest,
    actor: Annotated[CurrentUser, _permission(Permission.INVITE_FIRST_HR)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> AdminFirstHRInvitationResponse:
    return await service.invite_first_hr(actor.id, org_public_id, payload)


@router.post(
    "/organizations/{org_public_id}/first-hr-invitations/{invitation_public_id}/resend",
    response_model=AdminFirstHRInvitationResponse,
)
async def resend_first_hr_invitation(
    org_public_id: UUID,
    invitation_public_id: UUID,
    payload: AdminFirstHRInvitationRequest,
    actor: Annotated[CurrentUser, _permission(Permission.INVITE_FIRST_HR)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> AdminFirstHRInvitationResponse:
    return await service.invite_first_hr(
        actor.id,
        org_public_id,
        payload,
        resend_invitation_public_id=invitation_public_id,
    )


@router.post(
    "/organizations/{org_public_id}/people/{person_public_id}/court-checks",
    response_model=CourtCheckResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_court_check(
    org_public_id: UUID,
    person_public_id: UUID,
    payload: CourtCheckWriteRequest,
    actor: Annotated[CurrentUser, _permission(Permission.MANAGE_COURT_CHECK)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> CourtCheckResponse:
    return await service.create_court_check(actor.id, org_public_id, person_public_id, payload)


@router.patch(
    "/organizations/{org_public_id}/people/{person_public_id}/court-checks/{check_public_id}",
    response_model=CourtCheckResponse,
)
async def update_court_check(
    org_public_id: UUID,
    person_public_id: UUID,
    check_public_id: UUID,
    payload: CourtCheckUpdateRequest,
    actor: Annotated[CurrentUser, _permission(Permission.MANAGE_COURT_CHECK)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> CourtCheckResponse:
    return await service.update_court_check(
        actor.id, org_public_id, person_public_id, check_public_id, payload
    )


@router.post(
    "/organizations/{org_public_id}/people/{person_public_id}/court-checks/{check_public_id}/finalize",
    response_model=CourtCheckResponse,
)
async def finalize_court_check(
    org_public_id: UUID,
    person_public_id: UUID,
    check_public_id: UUID,
    actor: Annotated[CurrentUser, _permission(Permission.MANAGE_COURT_CHECK)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> CourtCheckResponse:
    return await service.finalize_court_check(
        actor.id, org_public_id, person_public_id, check_public_id
    )


@router.post(
    "/organizations/{org_public_id}/people/{person_public_id}/in-person-verifications",
    response_model=InPersonVerificationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_in_person_verification(
    org_public_id: UUID,
    person_public_id: UUID,
    payload: InPersonVerificationCreateRequest,
    actor: Annotated[
        CurrentUser, _permission(Permission.PERFORM_IN_PERSON_VERIFICATION)
    ],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> InPersonVerificationResponse:
    return await service.record_in_person_verification(
        actor.id, org_public_id, person_public_id, payload
    )
