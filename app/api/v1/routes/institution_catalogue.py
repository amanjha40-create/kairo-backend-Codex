"""Public, read-only suggestions shared by Candidate and Admin clients."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.catalogues.institutions import search_institutions

router = APIRouter(prefix="/catalogues/institutions", tags=["catalogues"])


class InstitutionSuggestion(BaseModel):
    id: str
    name: str
    state: str
    district: str
    city: str


class InstitutionSearchResponse(BaseModel):
    version: str
    scope: str
    available: bool
    manual_entry_allowed: bool
    fallback_label: str
    items: list[InstitutionSuggestion]
    total: int
    limit: int
    offset: int
    page: int


@router.get("", response_model=InstitutionSearchResponse)
def institution_search(
    q: Annotated[str, Query(max_length=160)] = "",
    search: Annotated[str | None, Query(max_length=160)] = None,
    state: Annotated[str, Query(max_length=100)] = "",
    district: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int | None, Query(ge=0, le=100000)] = None,
    page: Annotated[int | None, Query(ge=1, le=2001)] = None,
) -> dict:
    if search is not None and q and q != search:
        raise HTTPException(422, "Use either search or q, not conflicting values")
    if page is not None and offset is not None:
        raise HTTPException(422, "Use either page or offset")
    resolved_offset = offset if offset is not None else ((page or 1) - 1) * limit
    result = search_institutions(search if search is not None else q, state, district,
                                 limit, resolved_offset)
    result["page"] = resolved_offset // limit + 1
    return result
