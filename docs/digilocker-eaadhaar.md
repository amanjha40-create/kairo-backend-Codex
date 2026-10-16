# Dedicated DigiLocker e-Aadhaar

## Scope and launch gates

This is a source-certified, synthetic-only integration, not live Production
entitlement certification. It does not enable a service or modify a deployed
configuration. All three gates must pass in Production:

- `DIGILOCKER_ENABLED=true` with the existing valid OAuth/encryption configuration.
- `DIGILOCKER_EAADHAAR_ENABLED=true` (default false).
- `DIGILOCKER_EAADHAAR_ENTITLEMENT_CERTIFIED=true` (default false), set only after
  separately authorized Production entitlement certification.

Registration, selected scopes and User Details `eaadhaar=Y` do not establish
requester entitlement. Frozen clients need follow-up before enabling this feature:
Android/iOS need dedicated consent/actions and the e-Aadhaar label; Candidate web
also has closed PAN/DL enums in history/trust parsing. Do not hide provenance or
mislabel it as an issued document to accommodate those clients.

Existing OAuth authorization-code, form-body client credentials, PKCE, Redis
locator, encrypted tokens and credential-free Android/iOS return are unchanged.
Existing client ID/secret/callback/purpose/service/keyring settings remain
environment-specific. Never reuse staging credentials in Production.

## Provider and API contracts

Provider host: `https://digilocker.meripehchaan.gov.in`.

| Setting | Canonical path |
| --- | --- |
| `DIGILOCKER_ISSUED_DOCUMENTS_URL` | `/public/oauth2/2/files/issued` |
| `DIGILOCKER_USER_DETAILS_URL` | `/public/oauth2/1/user` |
| `DIGILOCKER_EAADHAAR_URL` | `/public/oauth2/2/xml/eaadhaar` |

Enabled configuration validates the exact HTTPS host/path and rejects credentials,
queries, fragments and alternate ports. There is no `/3` fallback.

The official current API Setu Authpartner OpenAPI is published at
<https://cf-media.api-setu.in/specfiles/apisetu_digilocker_authpartner_1.0.0.yaml>.
It documents the `/2` e-Aadhaar GET, no parameters, Bearer authentication and XML.
The saved official Requester v2.4 specification, printed page 26, establishes
the `hmac` response header: standard Base64 HMAC-SHA256 of file content, using
the UTF-8 client secret as key. Endpoint version follows the current OpenAPI,
not the historical `/3` endpoint. Live wire conformance remains uncertified.

`GET /api/v1/integrations/digilocker/eaadhaar/availability` returns only
`available` and `entitlement_confirmed=false`. It performs one authorized User
Details read; it neither fetches Aadhaar nor certifies entitlement.

`POST /api/v1/integrations/digilocker/eaadhaar/verify` accepts only
`{"consent":true,"consent_version":"v1"}`. Authenticated ownership is derived
server-side; client user IDs are forbidden. It checks User Details once, then
retrieves e-Aadhaar once if available. No automatic retries, token refresh,
issued-document retrieval, revocation or other provider action is performed.

Both responses are no-store. The verification response has an explicit derived
field allowlist. The owner/profile lock fences verification against concurrent
profile changes and account deletion.

## Integrity, XML and privacy

Transport is bounded to 20 seconds overall, 15 seconds read and 3 seconds connect;
no redirects, no compressed-content decoding. XML is at most 1 MiB; User Details
at most 64 KiB. The original response bytes are authenticated before any semantic
XML parsing. Missing, malformed, noncanonical Base64 or mismatched HMAC fails
closed. Provider error bodies are not read or reflected.

Parsing uses defusedxml with DTD, entities and external resolution forbidden,
and rejects XInclude. Maximum depth 16, 256 elements, 32 attributes per element;
attribute keys 128/value 1024 characters; text/tails 8192 (photo bounded by body).
Unknown bounded elements are ignored, never persisted. Only the documented
Poi name and full DOB child fields enter the existing India-aware matcher.
Gender/address/photo/uid/tkn and other provider fields are discarded. The supplied
`AadhaarXmlSchema` wrapper and published `EaadharXamlSchema` wrapper are accepted;
undocumented wire variants fail closed and require evidence before adaptation.
No Aadhaar address data is used to verify Permanent Address.

Raw XML is ephemeral memory only, never S3/Redis/database/audit data; the mutable
retrieval buffer is cleared after matching. Python/HTTP/XML allocations cannot
provide a guarantee of cryptographic memory erasure. Persisted provenance contains
no name, DOB, photo, address, full/masked Aadhaar number or provider identifier.
Its stable fingerprint is a local owner-scoped namespace hash, not an Aadhaar hash.

Generic Aadhaar upload metadata is separately hardened: discard document number,
extracted payload and reviewer note; use a generic filename before constructing
new storage keys. ORM insert/update guards and response minimization add defense
in depth. Other document types retain their contracts. This is not a bulk repair
of historical records, a database-wide restriction on privileged direct SQL, or
an assertion that user-uploaded evidence files contain no identity information.

401 invalid_token uses existing reconnect-required/token-erasure semantics.
403 returns safe access denial; 404 safe not-linked; 500/503/transport errors are
recoverable unavailable responses without retry. HMAC/schema failures never
produce a verified row. Raw bodies and transport descriptions are not exposed.

## Schema 091 and rollback

Table `digilocker_identity_verifications` changes exactly two CHECK constraints:
`ck_digilocker_identity_verifications_document_type` and
`ck_digilocker_identity_verifications_source`.

Allowed pairs are PANCR/issued_document, DRVLC/issued_document and EAADHAAR/eaadhaar,
all with source=digilocker. No column/index change, row rewrite or backfill.
Consent, integrity, profile-revision currentness and owner constraints remain.
Downgrade takes a table lock and refuses if any EAADHAAR row exists; it never
coerces/deletes provenance. Only an empty-Aadhaar downgrade restores old checks.

Future Production migration must preserve separate processes/sessions:
`074 -> 075`, commit/close/exit, then `075 -> 091`. Never use a single uninterrupted
074-to-091 process. Rehearsal must cover PostgreSQL 16.15 and 18.3, including
090-to-091 with unchanged PAN/DL fixtures and safe downgrade.
The older `scripts/certify_production_migration.py` is a historical head090
rehearsal and intentionally fails its head guard on this source. Do not use it as
the new rollout command. The head091 proof uses isolated fresh local databases
and separate Alembic subprocesses, recorded in the external certification report.

e-Aadhaar is an additional source for the existing identity fact, not an extra
score contribution. This service writes no score snapshot or Permanent Address
row/session; the latter retains its document, three successful checks and
separate server-day requirements.
