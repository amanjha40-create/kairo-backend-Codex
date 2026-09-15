"""Version bindings, or conditional private snapshots for unversioned source objects."""

import asyncio
from dataclasses import dataclass
from urllib.parse import quote

from botocore.exceptions import ClientError

from app.exceptions import NotFoundError, ServiceUnavailableError, ValidationAppError
from app.infrastructure.s3.client import get_s3_client

ALLOWED_MIME = frozenset({"application/pdf", "image/jpeg", "image/png", "image/webp"})


@dataclass(frozen=True)
class ObjectBinding:
    key: str
    version: str | None
    etag: str
    size: int
    content_type: str
    owns_snapshot: bool = False


class DocumentPackStorage:
    def __init__(self, settings):
        self.settings = settings
        self.bucket = settings.s3_documents_bucket

    def client(self):
        if not self.bucket:
            raise ServiceUnavailableError("Document sharing storage is unavailable")
        return get_s3_client(self.settings)

    async def inspect(self, key: str) -> ObjectBinding:
        try:
            meta = await asyncio.to_thread(self.client().head_object, Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
                raise NotFoundError("Selected document is unavailable") from None
            raise ServiceUnavailableError("Document sharing storage is unavailable") from None
        mime = str(meta.get("ContentType", "")).split(";")[0].lower()
        size = int(meta.get("ContentLength", 0))
        if mime not in ALLOWED_MIME or not 0 < size <= 50 * 1024 * 1024:
            raise ValidationAppError("Selected document has an unsupported format or size")
        version = meta.get("VersionId")
        return ObjectBinding(
            key, version if version and version != "null" else None, meta["ETag"], size, mime
        )

    async def snapshot(self, source: ObjectBinding, destination: str) -> ObjectBinding:
        if source.version:
            return source
        # COPY, never MOVE. If the source changes during selection, do not share the new bytes.
        try:
            result = await asyncio.to_thread(
                self.client().copy_object,
                Bucket=self.bucket,
                Key=destination,
                CopySource={"Bucket": self.bucket, "Key": source.key},
                CopySourceIfMatch=source.etag,
                MetadataDirective="REPLACE",
                ContentType=source.content_type,
                CacheControl="no-store",
                Metadata={},
                TaggingDirective="REPLACE",
                Tagging="",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"PreconditionFailed", "412", "NoSuchKey"}:
                raise ValidationAppError(
                    "Document changed. Select it again before sharing."
                ) from None
            raise ServiceUnavailableError("Document sharing storage is unavailable") from None
        version = result.get("VersionId")
        return ObjectBinding(
            destination,
            version if version and version != "null" else None,
            result["CopyObjectResult"]["ETag"],
            source.size,
            source.content_type,
            True,
        )

    async def delete_snapshot(self, binding: ObjectBinding) -> None:
        if not binding.owns_snapshot:
            return
        params = {"Bucket": self.bucket, "Key": binding.key}
        if binding.version:
            params["VersionId"] = binding.version
        await asyncio.to_thread(self.client().delete_object, **params)

    async def open(self, item):
        params = {"Bucket": self.bucket, "Key": item.object_key, "IfMatch": item.object_etag}
        if item.object_version:
            params["VersionId"] = item.object_version
        try:
            response = await asyncio.to_thread(self.client().get_object, **params)
        except ClientError:
            raise NotFoundError("Shared document is unavailable") from None
        body = response["Body"]
        if int(response.get("ContentLength", 0)) != item.byte_size:
            body.close()
            raise NotFoundError("Shared document is unavailable")

        def chunks():
            try:
                while data := body.read(64 * 1024):
                    yield data
            finally:
                body.close()

        return chunks(), {
            "Cache-Control": "no-store, private, max-age=0",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(item.filename, safe='')}",
            "Content-Length": str(item.byte_size),
        }
