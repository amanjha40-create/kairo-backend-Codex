"""S3 helpers — client factory, presigned uploads, path layout, validation."""

from app.infrastructure.s3.client import get_s3_client
from app.infrastructure.s3.paths import build_user_employment_document_key, sanitize_filename_for_storage
from app.infrastructure.s3.presign import generate_presigned_put_url, head_object_meta
from app.infrastructure.s3.service import S3UploadService
from app.infrastructure.s3.validation import normalize_primary_mime, validate_upload_declaration

__all__ = [
    "S3UploadService",
    "build_user_employment_document_key",
    "generate_presigned_put_url",
    "get_s3_client",
    "head_object_meta",
    "normalize_primary_mime",
    "sanitize_filename_for_storage",
    "validate_upload_declaration",
]
