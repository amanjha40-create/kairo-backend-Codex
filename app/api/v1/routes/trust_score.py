"""Trust score endpoints — user profile completeness and verification status."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_trust_score_service
from app.schemas.trust_score import TrustScoreResponse
from app.services import TrustScoreService

router = APIRouter(prefix="/trust-score", tags=["trust-score"])


@router.get("", response_model=TrustScoreResponse, summary="Current user trust score and breakdown")
async def get_trust_score(
    current: CurrentUser = Depends(get_current_user),
    service: TrustScoreService = Depends(get_trust_score_service),
) -> TrustScoreResponse:
    return await service.calculate_trust_score(current.id)
