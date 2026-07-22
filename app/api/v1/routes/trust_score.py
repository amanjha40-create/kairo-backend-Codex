"""Trust score endpoints — user profile completeness and verification status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_trust_score_service
from app.schemas.trust_score import TrustScoreConsentRequest, TrustScoreResponse
from app.services import TrustScoreService

router = APIRouter(prefix="/trust-score", tags=["trust-score"])


@router.get("", response_model=TrustScoreResponse, summary="Current user trust score and breakdown")
async def get_trust_score(
    current: CurrentUser = Depends(get_current_user),
    service: TrustScoreService = Depends(get_trust_score_service),
) -> TrustScoreResponse:
    return await service.calculate_trust_score(current.id)


@router.post("/consent", status_code=status.HTTP_204_NO_CONTENT, summary="Record explicit consent before Trust Score screening")
async def consent_to_trust_score(
    payload: TrustScoreConsentRequest,
    current: CurrentUser = Depends(get_current_user),
    service: TrustScoreService = Depends(get_trust_score_service),
) -> None:
    await service.record_consent(current.id, payload)


@router.delete("/consent", status_code=status.HTTP_204_NO_CONTENT, summary="Withdraw Trust Score calculation consent")
async def withdraw_trust_score_consent(
    current: CurrentUser = Depends(get_current_user),
    service: TrustScoreService = Depends(get_trust_score_service),
) -> None:
    await service.withdraw_consent(current.id)
