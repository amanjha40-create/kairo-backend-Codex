# Private Vault file viewing

`GET /api/v1/user-documents/{document_id}/content` requires the normal authenticated
owner session. Ownership, soft deletion, upload completion and MIME are checked before
storage access. The response streams through KairoID using the existing Document Pack
storage reader, with an ETag/version binding, no-store/private headers, nosniff,
sandbox CSP, a sanitized filename and an allowlisted MIME. No redirect or S3 metadata
is returned. Range is intentionally unsupported; clients receive a complete 200 body.

The legacy authenticated `download-url` metadata endpoint now returns the relative
content route and `expires_in_seconds: 0`. This is not a bearer grant: every content
request must still authenticate as the owner. It cannot be opened anonymously in an
external browser. Clients must fetch bytes through their normal authenticated API client.

Upload/replace/remove contracts, including direct presigned PUT upload, are unchanged.
The no-storage-URL guarantee here applies to viewing, not the existing upload transport.
Document Pack routes and grants are unchanged. No migration is needed.
