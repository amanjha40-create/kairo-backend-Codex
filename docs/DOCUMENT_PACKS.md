# Document Packs and precise identity types

This is independent of Trust Passport Sharing Policy V2. No Passport permissions,
verification, Trust Score, messaging, or Projects schema is changed.

## Identity contract

Use the existing private user-document upload intent, binary upload, and completion
flow. `document_type` accepts these seven UI choices:

| Visible label | Backend value |
| --- | --- |
| Aadhaar | `aadhaar` |
| PAN | `pan` |
| Passport | `passport` |
| Driving Licence | `driving_license` |
| Voter ID | `voter_id` |
| Birth Certificate | `birth_certificate` |
| Address Proof | `address_proof` |

The last two extend the existing string-backed enum; no document backfill is needed.
Legacy `government_id` stays readable as **Identity document**. `other` remains
API-compatible for existing personal files. Neither is offered for new manual
identity uploads. Never infer a type from a filename or verification from upload.

## Authenticated Candidate API

All paths below have `/api/v1` prefix. Normal Candidate authentication is required;
non-Candidate roles receive 403 and another owner's pack receives 404.

| Method | Path | Result |
| --- | --- | --- |
| GET | `/document-share-packs/documents` | Paginated current selectable files |
| POST | `/document-share-packs` | 201, created pack and one-time `share_url` |
| GET | `/document-share-packs` | Paginated owner history, never bearer URLs |
| GET | `/document-share-packs/{public_id}` | Metadata and immutable item snapshots |
| POST | `/document-share-packs/{public_id}/revoke` | Idempotently revoked metadata |
| GET | `/document-share-packs/{public_id}/analytics` | `view_count`, `last_viewed_at` |

Pagination uses existing `page`/`page_size` and Page response conventions.
The catalog returns `source_type`, `source_id`, `selection_version`, `category`,
`title`, `context`, `filename`, `content_type`, and `byte_size`. The version is an
opaque HMAC selection guard, not a storage address. Send it back unchanged.

Create JSON:

```json
{
  "purpose": "Employment onboarding - Example",
  "expiry_days": 7,
  "items": [{
    "source_type": "vault",
    "source_id": "<UUID from catalog>",
    "selection_version": "<64-character opaque catalog value>"
  }]
}
```

Purpose is trimmed and required (1-120 characters). Expiry is required, one of
1, 3, 7, 14, 30 days; clients default to 7. Select 1-20 files, at most 200 MiB
combined and 50 MiB each. Supported formats: PDF, JPEG, PNG, WebP.
Duplicates, foreign/incomplete/deleted files and stale versions fail closed.
Unknown properties (including Passport permissions) are rejected. There is no
PATCH, expansion, token-reissue, or no-expiry endpoint. After an ambiguous create
network failure, inspect history before retrying; creation has no idempotency key.

Sources are `vault`, `employment`, `education`, `certification`, `portfolio`.
Only owner-uploaded current documents qualify. Historical verification evidence
references are excluded at both catalog and create. Portfolio uses its existing
completed-attachment contract; the separate Projects model is not migrated.

Owner metadata: `public_id`, `purpose`, `created_at`, `expires_at`, `revoked_at`,
`status` (active/expired/revoked), `view_count`, `last_viewed_at`, `document_count`,
`items`. Only creation adds `share_url`.

## Recipient contract

The creation URL uses the existing configured public frontend origin:
`/document-pack#token=<opaque credential>`. The fragment avoids sending the bearer
to frontend hosting access logs. Keep the URL in creation-result memory only;
Copy, QR, native Share, and View recipient must use that exact same URL.

| Method | Path under `/api/v1/public/document-share-packs` | Result |
| --- | --- | --- |
| GET | `/{token}` | Purpose, expiry, count, selected item snapshots |
| GET | `/{token}/items/{item_public_id}/download-url` | Short-lived relative API URL |
| GET | `/{token}/items/{item_public_id}/content?expires=...&signature=...` | Authorized bytes |

Public item fields are exactly `public_id`, `category`, `title`, `context`,
`filename`, `content_type`, `byte_size`. No owner attribution, profile, email,
phone, score, storage path, underlying source identifier, or verification claim.
Categories: identity, employment, education, certifications, projects.

The server stores SHA-256 of a random 256-bit bearer, never the raw credential.
Unknown, expired, revoked, disabled-owner and deleted-owner packs return neutral
404. File grants last at most 60 seconds and never outlive the pack. The content
endpoint rechecks authorization, so revocation also blocks preissued grants.
Bytes already delivered cannot be recalled. Responses are private/no-store;
filenames are encoded and active content is sandboxed. No S3 URL is returned.
Application logging redacts bearer path segments and download signatures.
Analytics are aggregate count/time only, with row locking to prevent lost updates.

## Exact-file binding and retention

Migration 078 (parent 077) adds only `document_share_packs` and
`document_share_pack_items`. Each item has immutable display metadata and an
internal object/version/ETag binding. There is intentionally no FK to the mutable
source record. Pack creation is one DB transaction; partial copies are cleaned
on failure, and no partial pack is committed.

Where S3 has a durable version reference, that version is reused. The current
staging bucket is unversioned, so retaining the original key alone is NOT safe.
A conditional server-side private COPY, never MOVE, snapshots the selected bytes
under `.../document-share-packs/{pack}/{item}`. ETag mismatch rejects a concurrent
replacement. Source overwrite/delete/detach cannot alter the retained copy.
Copied objects do not inherit source retention tags. No bucket/IAM change is needed.

`python -m app.services.document_pack_cleanup` removes only pack-owned copies
after expiry/revocation/owner deletion, retaining audit metadata.
It skips active packs and never deletes original/version-referenced documents.
Run it through the existing staging task runner. This change ships the command,
not a new cloud schedule or lifecycle policy. Until scheduled/invoked, expired
copies may remain stored but cannot be accessed through the public contract.
An interrupted copy before DB commit may require operator reconciliation of the
dedicated snapshot prefix; do not apply broad source-document cleanup rules there.

## Android and future iOS integration

Documents is the entry point: Share documents and Shared document packs. Use
Select -> Purpose -> Expiry -> Review -> Create, with zero initial selections,
category filtering/count/clear, and seven-type compact identity sheet. Android
Back closes sheets or returns to the preceding creation step. Result offers
Copy/QR/Share/View recipient/Done. History shows metadata and active revocation;
old bearer actions cannot be reconstructed after the creation result is gone.

iOS should consume these same platform-neutral endpoints and exact backend type
values, preserve the catalog version guard, show truthful uploaded/not-verified
semantics, and use the same creation URL for all sharing actions. Do not persist
bearers in general preferences or request token reissue from history. No Swift
files were changed; the available iOS checkout has no matching Vault taxonomy.

## Release gate

Local tests use only synthetic bytes and isolated PostgreSQL. Staging migration
078 and application deployment are approved; production is not. Git push waits
for live QA. Before live mutations, get explicit approval for exactly one disposable
identity Vault upload and one disposable pack of synthetic harmless QA files.
