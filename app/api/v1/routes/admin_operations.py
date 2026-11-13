"""Permission-separated Admin Operations V1.1 routes."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import (
    get_admin_operations_service,
    get_education_service,
    get_employment_document_service,
    get_resume_review_service,
    get_resume_service,
    get_user_document_service,
    get_verification_request_service,
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
    AdminCandidateInvitationResponse,
    AdminCandidateResponse,
    AdminCareerDeleteResponse,
    AdminCareerDocumentCompleteUploadRequest,
    AdminCareerDocumentResponse,
    AdminCareerDocumentUploadIntentRequest,
    AdminCareerMutationRequest,
    AdminCareerMutationResponse,
    AdminCareerRecordResponse,
    AdminCareerUpdateRequest,
    AdminClientPersonActivationRequest,
    AdminClientPersonCreateRequest,
    AdminClientPersonResponse,
    AdminCreateCandidateRequest,
    AdminFirstHRInvitationRequest,
    AdminFirstHRInvitationResponse,
    AdminOrganizationCreateRequest,
    AdminOrganizationCreateResponse,
    AdminOrganizationProvisioningStatus,
    AdminProfileMutationRequest,
    AdminProfileMutationResponse,
    CandidateActivationResponse,
    CandidateActivationTokenRequest,
    CandidateActivationValidationResponse,
    CandidateClaimRequest,
    CandidateClaimResponse,
    CandidateProvenanceConfirmationRequest,
    CandidateProvenanceConfirmationResponse,
    CareerClaimType,
    CourtCheckResponse,
    CourtCheckUpdateRequest,
    CourtCheckWriteRequest,
    InPersonVerificationCreateRequest,
    InPersonVerificationResponse,
)
from app.schemas.education import EducationDocumentUploadIntentRequest
from app.schemas.employment_document import (
    DocumentCompleteUploadRequest,
    DocumentUploadIntentRequest,
)
from app.schemas.pagination import Page, PageParams
from app.schemas.user_document import (
    UserDocumentCompleteUploadRequest,
    UserDocumentResponse,
    UserDocumentUploadIntentRequest,
    UserDocumentUploadIntentResponse,
)
from app.schemas.verification_request import (
    VerificationRequestEvidenceCreateRequest,
    VerificationRequestEvidenceResponse,
)
from app.services.admin_operations_service import AdminOperationsService
from app.services.education_service import EducationService
from app.services.employment_document_service import EmploymentDocumentService
from app.services.resume_review_service import ResumeReviewService
from app.services.resume_service import ResumeService
from app.services.user_document_service import UserDocumentService
from app.services.verification_request_service import VerificationRequestService

router = APIRouter(prefix="/admin/operations", tags=["admin-operations"])
activation_router = APIRouter(prefix="/candidate-activations", tags=["candidate-activation"])
candidate_router = APIRouter(prefix="/candidate", tags=["candidate-profile-provenance"])


def _permission(permission: Permission):
    return Depends(require_permission(permission))


@router.get(
    "/organizations/{org_public_id}/provisioning",
    response_model=AdminOrganizationProvisioningStatus,
)
async def get_organization_provisioning(
    org_public_id: UUID,
    _: Annotated[CurrentUser, _permission(Permission.INVITE_FIRST_HR)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> AdminOrganizationProvisioningStatus:
    return await service.provisioning_status(org_public_id)


@router.get(
    "/organizations/{org_public_id}/people/{person_public_id}/court-checks",
    response_model=Page[CourtCheckResponse],
)
async def list_court_receipts(
    org_public_id: UUID,
    person_public_id: UUID,
    params: Annotated[PageParams, Depends()],
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_COURT_CHECK)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> Page[CourtCheckResponse]:
    return await service.list_court_checks(org_public_id, person_public_id, params)


@router.get(
    "/organizations/{org_public_id}/people/{person_public_id}/court-checks/{check_public_id}",
    response_model=CourtCheckResponse,
)
async def get_court_receipt(
    org_public_id: UUID,
    person_public_id: UUID,
    check_public_id: UUID,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_COURT_CHECK)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> CourtCheckResponse:
    return await service.get_court_check(org_public_id, person_public_id, check_public_id)


@router.get(
    "/organizations/{org_public_id}/people/{person_public_id}/in-person-verifications",
    response_model=Page[InPersonVerificationResponse],
)
async def list_in_person_receipts(
    org_public_id: UUID,
    person_public_id: UUID,
    params: Annotated[PageParams, Depends()],
    _: Annotated[CurrentUser, _permission(Permission.PERFORM_IN_PERSON_VERIFICATION)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> Page[InPersonVerificationResponse]:
    return await service.list_in_person_verifications(org_public_id, person_public_id, params)


@router.get(
    "/organizations/{org_public_id}/people/{person_public_id}/in-person-verifications/{record_public_id}",
    response_model=InPersonVerificationResponse,
)
async def get_in_person_receipt(
    org_public_id: UUID,
    person_public_id: UUID,
    record_public_id: UUID,
    _: Annotated[CurrentUser, _permission(Permission.PERFORM_IN_PERSON_VERIFICATION)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> InPersonVerificationResponse:
    return await service.get_in_person_verification(
        org_public_id, person_public_id, record_public_id
    )


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


@router.get(
    "/candidate-invitations",
    response_model=list[AdminCandidateInvitationResponse],
)
async def list_pending_candidate_invitations(
    _: Annotated[CurrentUser, _permission(Permission.READ_USERS)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> list[AdminCandidateInvitationResponse]:
    return await service.list_pending_candidate_invitations()


@router.post(
    "/organizations/{org_public_id}/people",
    response_model=AdminClientPersonResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_client_person(
    org_public_id: UUID,
    payload: AdminClientPersonCreateRequest,
    actor: Annotated[CurrentUser, _permission(Permission.CREATE_PERSON)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> AdminClientPersonResponse:
    return await service.create_client_person(actor.id, org_public_id, payload)


@router.post(
    "/organizations/{org_public_id}/people/{person_public_id}/candidate-activation",
    response_model=CandidateActivationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def activate_client_person(
    org_public_id: UUID,
    person_public_id: UUID,
    payload: AdminClientPersonActivationRequest,
    actor: Annotated[CurrentUser, _permission(Permission.SEND_CANDIDATE_ACTIVATION)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> CandidateActivationResponse:
    return await service.activate_client_person(actor.id, org_public_id, person_public_id, payload)


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


@router.patch("/candidates/{candidate_id}/profile", response_model=AdminProfileMutationResponse)
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
    payload: AdminCareerUpdateRequest,
    actor: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> AdminCareerMutationResponse:
    return await service.mutate_candidate_career(
        actor.id, candidate_id, payload, record_id=record_id
    )


@router.get("/candidates/{candidate_id}/career", response_model=Page[AdminCareerRecordResponse])
async def list_assisted_candidate_career_records(
    candidate_id: UUID,
    claim_type: CareerClaimType,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> Page[AdminCareerRecordResponse]:
    return await service.list_candidate_career(candidate_id, claim_type, params)


@router.get(
    "/candidates/{candidate_id}/career/{record_id}", response_model=AdminCareerRecordResponse
)
async def read_assisted_candidate_career_record(
    candidate_id: UUID,
    record_id: UUID,
    claim_type: CareerClaimType,
    actor: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> AdminCareerRecordResponse:
    return await service.read_candidate_career(candidate_id, claim_type, record_id)


@router.delete(
    "/candidates/{candidate_id}/career/{record_id}", response_model=AdminCareerDeleteResponse
)
async def delete_assisted_candidate_career_record(
    candidate_id: UUID,
    record_id: UUID,
    claim_type: CareerClaimType,
    actor: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> AdminCareerDeleteResponse:
    return await service.delete_candidate_career(actor.id, candidate_id, claim_type, record_id)


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
@router.get(
    "/candidates/{candidate_id}/resumes",
    response_model=Page[ResumeResponse],
)
async def list_admin_resumes(
    candidate_id: UUID,
    params: Annotated[PageParams, Depends()],
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    resumes: Annotated[ResumeService, Depends(get_resume_service)],
) -> Page[ResumeResponse]:
    await admin.candidate_identity(candidate_id)
    return await resumes.list(candidate_id, params.offset or 0, params.limit or 20)


@router.get(
    "/candidates/{candidate_id}/resumes/{resume_id}/status",
    response_model=ResumeProcessResponse,
)
async def get_admin_resume_status(
    candidate_id: UUID,
    resume_id: UUID,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    resumes: Annotated[ResumeService, Depends(get_resume_service)],
) -> ResumeProcessResponse:
    await admin.candidate_identity(candidate_id)
    return await resumes.status(candidate_id, resume_id)


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
    await admin.candidate_identity(candidate_id)
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
    await admin.candidate_identity(candidate_id)
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
    await admin.candidate_identity(candidate_id)
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
    await admin.candidate_identity(candidate_id)
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
    await admin.candidate_identity(candidate_id)
    return await reviews.create(candidate_id, resume_id)


@router.get(
    "/candidates/{candidate_id}/resumes/{resume_id}/review-session",
    response_model=ReviewSessionResponse,
)
async def get_admin_resume_review(
    candidate_id: UUID,
    resume_id: UUID,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    reviews: Annotated[ResumeReviewService, Depends(get_resume_review_service)],
) -> ReviewSessionResponse:
    await admin.candidate_identity(candidate_id)
    return await reviews.get_by_resume(candidate_id, resume_id)


@router.get(
    "/candidates/{candidate_id}/resume-reviews/{review_id}",
    response_model=ReviewSessionResponse,
)
async def get_admin_resume_review_by_id(
    candidate_id: UUID,
    review_id: UUID,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    reviews: Annotated[ResumeReviewService, Depends(get_resume_review_service)],
) -> ReviewSessionResponse:
    await admin.candidate_identity(candidate_id)
    return await reviews.get(candidate_id, review_id)


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
    await admin.candidate_identity(candidate_id)
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
    await admin.candidate_identity(candidate_id)
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
    await admin.candidate_identity(candidate_id)
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


@router.get(
    "/candidates/{candidate_id}/resume-reviews/{review_id}/import-status",
    response_model=ImportBatchResponse,
)
async def get_admin_resume_import_status(
    candidate_id: UUID,
    review_id: UUID,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    reviews: Annotated[ResumeReviewService, Depends(get_resume_review_service)],
) -> ImportBatchResponse:
    await admin.candidate_identity(candidate_id)
    return await reviews.latest_import_status(candidate_id, review_id)


@router.get(
    "/candidates/{candidate_id}/documents",
    response_model=Page[UserDocumentResponse],
)
async def list_admin_candidate_documents(
    candidate_id: UUID,
    params: Annotated[PageParams, Depends()],
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    documents: Annotated[UserDocumentService, Depends(get_user_document_service)],
) -> Page[UserDocumentResponse]:
    await admin.candidate_identity(candidate_id)
    items, total = await documents.list_for_user(
        candidate_id, offset=params.offset, limit=params.limit
    )
    return Page[UserDocumentResponse].create(
        items=[UserDocumentResponse.model_validate(item) for item in items],
        total=total,
        params=params,
    )


@router.post(
    "/candidates/{candidate_id}/documents/upload-intent",
    response_model=UserDocumentUploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_candidate_document_upload_intent(
    candidate_id: UUID,
    payload: UserDocumentUploadIntentRequest,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    documents: Annotated[UserDocumentService, Depends(get_user_document_service)],
) -> UserDocumentUploadIntentResponse:
    await admin.candidate_identity(candidate_id)
    return await documents.create_upload_intent(candidate_id, payload)


@router.post(
    "/candidates/{candidate_id}/documents/{document_id}/complete-upload",
    response_model=UserDocumentResponse,
)
async def complete_admin_candidate_document_upload(
    candidate_id: UUID,
    document_id: UUID,
    payload: UserDocumentCompleteUploadRequest,
    actor: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    documents: Annotated[UserDocumentService, Depends(get_user_document_service)],
) -> UserDocumentResponse:
    await admin.candidate_identity(candidate_id)
    document = await documents.complete_upload(candidate_id, document_id, payload.checksum_sha256)
    await admin.record_document_upload_audit(actor.id, candidate_id, document)
    return UserDocumentResponse.model_validate(document)


@router.get(
    "/candidates/{candidate_id}/documents/{document_id}/content",
    response_class=StreamingResponse,
)
async def view_admin_candidate_document(
    candidate_id: UUID,
    document_id: UUID,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    documents: Annotated[UserDocumentService, Depends(get_user_document_service)],
):
    await admin.candidate_identity(candidate_id)
    chunks, headers, mime = await documents.content(candidate_id, document_id)
    return StreamingResponse(
        chunks,
        headers={**headers, "Cache-Control": "no-store, private, max-age=0"},
        media_type=mime,
    )


@router.get(
    "/candidates/{candidate_id}/career-documents/{claim_type}/{career_record_id}",
    response_model=Page[AdminCareerDocumentResponse],
)
async def list_admin_candidate_career_documents(
    candidate_id: UUID,
    claim_type: Literal["employment", "education"],
    career_record_id: UUID,
    params: Annotated[PageParams, Depends()],
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    employment_documents: Annotated[
        EmploymentDocumentService, Depends(get_employment_document_service)
    ],
    education: Annotated[EducationService, Depends(get_education_service)],
) -> Page[AdminCareerDocumentResponse]:
    await admin.candidate_identity(candidate_id)
    if claim_type == "employment":
        rows, total = await employment_documents.list_for_employment_owned(
            candidate_id,
            career_record_id,
            offset=params.offset,
            limit=params.limit,
        )
    else:
        rows, total = await education.list_documents(
            candidate_id,
            career_record_id,
            offset=params.offset,
            limit=params.limit,
        )
    return Page[AdminCareerDocumentResponse].create(
        items=[_career_document_response(claim_type, career_record_id, row) for row in rows],
        total=total,
        params=params,
    )


@router.post(
    "/candidates/{candidate_id}/career-documents/upload-intent",
    response_model=UserDocumentUploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_candidate_career_document_upload_intent(
    candidate_id: UUID,
    payload: AdminCareerDocumentUploadIntentRequest,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    employment_documents: Annotated[
        EmploymentDocumentService, Depends(get_employment_document_service)
    ],
    education: Annotated[EducationService, Depends(get_education_service)],
):
    await admin.candidate_identity(candidate_id)
    if payload.claim_type == "employment":
        return await employment_documents.create_upload_intent(
            candidate_id,
            payload.career_record_id,
            DocumentUploadIntentRequest(
                document_type=payload.document_type,
                evidence_role=payload.evidence_role,
                original_filename=payload.original_filename,
                content_type=payload.content_type,
                byte_size=payload.byte_size,
            ),
        )
    return await education.create_document_upload_intent(
        candidate_id,
        payload.career_record_id,
        EducationDocumentUploadIntentRequest(
            document_type=payload.document_type,
            original_filename=payload.original_filename,
            content_type=payload.content_type,
            byte_size=payload.byte_size,
        ),
    )


@router.post(
    "/candidates/{candidate_id}/career-documents/{document_id}/complete-upload",
    response_model=AdminCareerDocumentResponse,
)
async def complete_admin_candidate_career_document_upload(
    candidate_id: UUID,
    document_id: UUID,
    payload: AdminCareerDocumentCompleteUploadRequest,
    actor: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    employment_documents: Annotated[
        EmploymentDocumentService, Depends(get_employment_document_service)
    ],
    education: Annotated[EducationService, Depends(get_education_service)],
) -> AdminCareerDocumentResponse:
    await admin.candidate_identity(candidate_id)
    if payload.claim_type == "employment":
        await employment_documents.complete_upload(
            candidate_id,
            payload.career_record_id,
            document_id,
            DocumentCompleteUploadRequest(checksum_sha256=payload.checksum_sha256),
        )
        document = await employment_documents.get_document_owned(candidate_id, document_id)
    else:
        document = await education.complete_document_upload(
            candidate_id,
            payload.career_record_id,
            document_id,
            payload.checksum_sha256,
        )
    await admin.record_document_upload_audit(
        actor.id,
        candidate_id,
        document,
        claim_type=payload.claim_type,
        career_record_id=payload.career_record_id,
    )
    return _career_document_response(
        payload.claim_type,
        payload.career_record_id,
        document,
    )


@router.get(
    "/candidates/{candidate_id}/career-documents/{claim_type}/{career_record_id}/{document_id}/content",
    response_class=StreamingResponse,
)
async def view_admin_candidate_career_document(
    candidate_id: UUID,
    claim_type: Literal["employment", "education"],
    career_record_id: UUID,
    document_id: UUID,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_ASSISTED_PROFILE)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    employment_documents: Annotated[
        EmploymentDocumentService, Depends(get_employment_document_service)
    ],
    education: Annotated[EducationService, Depends(get_education_service)],
):
    await admin.candidate_identity(candidate_id)
    if claim_type == "employment":
        chunks, headers, mime = await employment_documents.content(
            candidate_id, career_record_id, document_id
        )
    else:
        chunks, headers, mime = await education.document_content(
            candidate_id, career_record_id, document_id
        )
    return StreamingResponse(
        chunks,
        headers={**headers, "Cache-Control": "no-store, private, max-age=0"},
        media_type=mime,
    )


def _career_document_response(
    claim_type: Literal["employment", "education"],
    career_record_id: UUID,
    document,
) -> AdminCareerDocumentResponse:
    evidence_role = getattr(document, "evidence_role", None)
    return AdminCareerDocumentResponse(
        id=document.id,
        claim_type=claim_type,
        career_record_id=career_record_id,
        document_type=str(getattr(document.document_type, "value", document.document_type)),
        original_filename=document.original_filename,
        content_type=document.content_type,
        byte_size=document.byte_size,
        verification_status=str(
            getattr(document.verification_status, "value", document.verification_status)
        ),
        evidence_role=evidence_role,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


@router.post(
    "/candidates/{candidate_id}/evidence/upload-intent",
    response_model=UserDocumentUploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_private_evidence_upload_intent(
    candidate_id: UUID,
    payload: UserDocumentUploadIntentRequest,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_COURT_CHECK)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    documents: Annotated[UserDocumentService, Depends(get_user_document_service)],
) -> UserDocumentUploadIntentResponse:
    """Upload a private Candidate document for assisted court/in-person operations."""

    await admin.candidate_identity(candidate_id)
    return await documents.create_upload_intent(candidate_id, payload)


@router.post(
    "/candidates/{candidate_id}/evidence/{document_id}/complete-upload",
    response_model=UserDocumentResponse,
)
async def complete_admin_private_evidence_upload(
    candidate_id: UUID,
    document_id: UUID,
    payload: UserDocumentCompleteUploadRequest,
    _: Annotated[CurrentUser, _permission(Permission.MANAGE_COURT_CHECK)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    documents: Annotated[UserDocumentService, Depends(get_user_document_service)],
) -> UserDocumentResponse:
    await admin.candidate_identity(candidate_id)
    document = await documents.complete_upload(candidate_id, document_id, payload.checksum_sha256)
    return UserDocumentResponse.model_validate(document)


@router.post(
    "/candidates/{candidate_id}/verification-requests/{request_id}/evidence/upload-intent",
    response_model=UserDocumentUploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_evidence_upload_intent(
    candidate_id: UUID,
    request_id: UUID,
    payload: UserDocumentUploadIntentRequest,
    _: Annotated[CurrentUser, _permission(Permission.REVIEW_VERIFICATION)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    documents: Annotated[UserDocumentService, Depends(get_user_document_service)],
    verification_requests: Annotated[
        VerificationRequestService, Depends(get_verification_request_service)
    ],
) -> UserDocumentUploadIntentResponse:
    """Reuse the private user-document pipeline for managed-person evidence."""

    await admin.candidate_identity(candidate_id)
    await verification_requests.require_admin_evidence_target(candidate_id, request_id)
    return await documents.create_upload_intent(candidate_id, payload)


@router.post(
    "/candidates/{candidate_id}/verification-requests/{request_id}/evidence/{document_id}/complete-upload",
    response_model=VerificationRequestEvidenceResponse,
)
async def complete_admin_evidence_upload(
    candidate_id: UUID,
    request_id: UUID,
    document_id: UUID,
    payload: UserDocumentCompleteUploadRequest,
    actor: Annotated[CurrentUser, _permission(Permission.REVIEW_VERIFICATION)],
    admin: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
    documents: Annotated[UserDocumentService, Depends(get_user_document_service)],
    verification_requests: Annotated[
        VerificationRequestService, Depends(get_verification_request_service)
    ],
) -> VerificationRequestEvidenceResponse:
    await admin.candidate_identity(candidate_id)
    document = await documents.complete_upload(candidate_id, document_id, payload.checksum_sha256)
    return await verification_requests.add_evidence_for_admin(
        actor_user_id=actor.id,
        candidate_user_id=candidate_id,
        verification_request_public_id=request_id,
        payload=VerificationRequestEvidenceCreateRequest(
            evidence_type="admin_supplied_document",
            field_key="admin_supporting_evidence",
            document_id=document.id,
            value={"provenance": "admin_uploaded_on_behalf_of_candidate"},
        ),
    )


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
    actor: Annotated[CurrentUser, _permission(Permission.PERFORM_IN_PERSON_VERIFICATION)],
    service: Annotated[AdminOperationsService, Depends(get_admin_operations_service)],
) -> InPersonVerificationResponse:
    return await service.record_in_person_verification(
        actor.id, org_public_id, person_public_id, payload
    )
