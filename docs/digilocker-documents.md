# DL-B2: issued documents and ephemeral retrieval

Contract source: Requester - Meri Pehchaan API Specification v2.4, pages 22-24,
the previously downloaded official API Setu PDF. The official CDN returned 403
on the fresh documentation fetch. The cached specification agrees with the
public government-hosted Authorized Partner API specification on these routes:

- GET `https://digilocker.meripehchaan.gov.in/public/oauth2/2/files/issued`
- GET `https://digilocker.meripehchaan.gov.in/public/oauth2/1/file/{uri}`

`uri` is the variable final path segment, not a query parameter. Authentication
is the server-held Bearer access token. OAuth authorization, token exchange,
refresh, revocation, encryption envelopes and configuration remain unchanged.

## Kairo API

`GET /api/v1/integrations/digilocker/documents/issued` returns `items`, `count`,
and `malformed_count`. Each valid item contains name, type, date, MIME list,
doctype, issuerid, issuer, description, supported, reference, source=digilocker,
and integrity=not_checked. Invalid entries are counted and omitted, not used
to infer an empty or successful list. Maximum 500 entries and 1 MiB response.

PANCR and DRVLC file entries support retrieval. No name-based inference, ACR,
Aadhaar, user-details, or uploaded-document endpoint is used.

`POST /api/v1/integrations/digilocker/documents/retrieve` accepts only
`{"reference": "opaque-issued-reference"}`. It retrieves ONE file into bounded
memory, verifies the standard Base64 HMAC-SHA256 header with constant-time
comparison, and returns source, doctype, issuer, issuerid, reference, MIME,
retrieved_at, integrity=verified. Raw bytes are discarded and never returned
as part of this metadata response. This phase's UI action is **Verify file
integrity**, not View, KYC, profile verification, or a Trust Score award.

The opaque AES-GCM reference hides the raw provider URI, uses a separate AAD
domain from credential encryption, expires in ten minutes, and is bound to
environment, owner, connection, and the encrypted access-credential generation.
It uses the existing encryption keyring without changing token envelopes or
adding secrets. Raw URIs/references must not be logged. References are kept
only in page memory, not persistent browser storage or URLs.

Both routes require normal Candidate authentication, a verified email, and
an active non-deleted owner/connection. Owner and connection read locks fence
concurrent deletion/disconnection; every path rolls back, with no DB commit.
Credentials expired or within 30 seconds of expiry fail without refresh,
revocation, erasure, or an automatic OAuth attempt. Existing OAuth methods are
not changed. Unexpected provider responses are sanitized without raw bodies.

File reads have a 10 MiB cap, 20-second overall deadline, explicit connect/read
timeouts, no redirects, no compressed transfer, no retries, and allowlisted
MIME types. Missing/mismatched HMAC fails closed. XML is not parsed or rendered.
Only operation, numeric HTTP status and fixed error category are logged; no
file name, document body, URI, token, client secret or reference is logged.

No migration, S3 write, persistent file, profile/Career/Passport change, Trust
Score mutation, or Document Pack creation occurs. Discovery and retrieval are
explicit UI actions. Listing is never fetched automatically on mount/focus.
