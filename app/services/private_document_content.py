"""Bounded content delivery for an already-authorized exact private file binding."""

import re
from types import SimpleNamespace

from app.exceptions import NotFoundError
from app.services.document_pack_storage import ALLOWED_MIME, DocumentPackStorage

CONTENT_RESPONSES = {
    200: {
        "content": {
            mime: {"schema": {"type": "string", "format": "binary"}}
            for mime in sorted(ALLOWED_MIME)
        }
    }
}


async def private_document_content(settings, document, *, completed: bool):
    # Never resolve a replacement, latest attachment or filename match here.
    if (
        not completed
        or not document.object_key
        or document.content_type not in ALLOWED_MIME
        or not document.byte_size
        or not 0 < document.byte_size <= 50 * 1024 * 1024
    ):
        raise NotFoundError("Private document is unavailable")
    storage = DocumentPackStorage(settings)
    binding = await storage.inspect(document.object_key)
    if binding.content_type != document.content_type or binding.size != document.byte_size:
        raise NotFoundError("Private document is unavailable")
    filename = (document.original_filename or "document").replace("\\", "/").rsplit("/", 1)[-1]
    filename = re.sub(r"[\x00-\x1f\x7f]", "", filename).strip()[:200] or "document"
    chunks, headers = await storage.open(
        SimpleNamespace(
            object_key=binding.key,
            object_version=binding.version,
            object_etag=binding.etag,
            byte_size=binding.size,
            filename=filename,
        )
    )
    return chunks, headers, binding.content_type
