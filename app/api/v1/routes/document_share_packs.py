"""Document Pack owner management and credential-scoped recipient access."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.config import Settings, get_settings
from app.db.session import get_session
from app.exceptions import ForbiddenError
from app.schemas.document_share_pack import (
    DocumentPackCreate,
    DocumentPackCreated,
    DocumentPackDownload,
    DocumentPackResponse,
    PublicDocumentPack,
    SelectableDocument,
)
from app.schemas.pagination import Page, PageParams
from app.services.document_share_pack_service import DocumentSharePackService

PRIVATE_HEADERS = {
    "Cache-Control": "no-store, private, max-age=0",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


async def no_cache(response: Response):
    response.headers.update(PRIVATE_HEADERS)


router = APIRouter(
    prefix="/document-share-packs", tags=["document-share-packs"], dependencies=[Depends(no_cache)]
)
public_router = APIRouter(
    prefix="/public/document-share-packs",
    tags=["public-document-share-packs"],
    dependencies=[Depends(no_cache)],
)


def service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return DocumentSharePackService(session, settings)


def candidate(current: Annotated[CurrentUser, Depends(get_current_user)]):
    if current.role not in {"candidate", "user"}:
        raise ForbiddenError("Candidate account required")
    return current


Owner = Annotated[CurrentUser, Depends(candidate)]
Service = Annotated[DocumentSharePackService, Depends(service)]
Paging = Annotated[PageParams, Depends()]


@router.get("/documents", response_model=Page[SelectableDocument])
async def selectable_documents(current: Owner, svc: Service, page: Paging):
    items, total = await svc.sources.list(current.id, offset=page.offset, limit=page.limit)
    return Page[SelectableDocument].create(items=items, total=total, params=page)


@router.post("", response_model=DocumentPackCreated, status_code=201)
async def create_pack(payload: DocumentPackCreate, current: Owner, svc: Service):
    return await svc.create(current.id, payload)


@router.get("", response_model=Page[DocumentPackResponse])
async def history(current: Owner, svc: Service, page: Paging):
    items, total = await svc.history(current.id, offset=page.offset, limit=page.limit)
    return Page[DocumentPackResponse].create(items=items, total=total, params=page)


@router.get("/{public_id}", response_model=DocumentPackResponse)
async def details(public_id: UUID, current: Owner, svc: Service):
    return svc.response(await svc.owned(current.id, public_id))


@router.post("/{public_id}/revoke", response_model=DocumentPackResponse)
async def revoke(public_id: UUID, current: Owner, svc: Service):
    return await svc.revoke(current.id, public_id)


@router.get("/{public_id}/analytics")
async def analytics(public_id: UUID, current: Owner, svc: Service):
    pack = await svc.owned(current.id, public_id)
    return {"view_count": pack.view_count, "last_viewed_at": pack.last_viewed_at}


@public_router.get("/{token}", response_model=PublicDocumentPack)
async def recipient(token: str, svc: Service):
    return await svc.recipient(token)


@public_router.get(
    "/{token}/items/{item_public_id}/download-url", response_model=DocumentPackDownload
)
async def download(token: str, item_public_id: UUID, svc: Service):
    return await svc.download_url(token, item_public_id)


@public_router.get("/{token}/items/{item_public_id}/content")
async def content(
    token: str,
    item_public_id: UUID,
    svc: Service,
    expires: int = Query(),
    signature: str = Query(min_length=64, max_length=64),
):
    chunks, headers, mime = await svc.content(token, item_public_id, expires, signature)
    return StreamingResponse(chunks, headers=headers, media_type=mime)
