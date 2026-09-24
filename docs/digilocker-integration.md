# DigiLocker requester foundation (DL-B1)

Status: local implementation for review. Disabled by default. No credentials,
AWS provisioning, live provider requests, or deployments are part of this change.
This is a requester OAuth integration, not a Kairo login provider or an issuer.

## Architecture and API contract

The existing Candidate bearer/session authentication dependency protects all
owner endpoints. The service rechecks active, non-deleted, email-verified
Candidate ownership under the same user-row lock used by account deletion.
All lifecycle operations acquire the owner lock before the connection lock.
Organization and administrative principals cannot connect through these APIs.

Base path: `/api/v1/integrations/digilocker`.

| Method | Path | Contract |
| --- | --- | --- |
| POST | `/connect` | Authenticated; absent/empty JSON body. Returns `authorization_url`, `expires_at`, `connection_state: pending`. No verifier or provider credentials. |
| GET | `/callback` | Public; accepts `state` and `code`, or `state`, `error`, optional `error_description`. State authenticates the initiating connection attempt. |
| GET | `/status` | Authenticated; returns `connected`, `status`, `connected_at`, `consent_valid_until`, safe `scopes`. |
| DELETE | `/connection` | Authenticated; best-effort remote revocation, local erasure, HTTP 204. Idempotent when already disconnected. |

There is no public refresh/token endpoint. `DigiLockerService.access_token()` is
internal only and returns `SecretStr`; it must never be serialized to clients.
Disconnect and status remain available while the integration is disabled.

Successful callbacks return only `{"connection_state":"active"}` by default.
If configured, a 303 redirect uses the operator-configured completion URL plus
the static query `digilocker_result=connected`. The completion URL must be HTTPS
on the configured Candidate portal origin, with no existing query or fragment.
No request-supplied return URL, token, state, code, or identity is placed there.
Failures return the ordinary safe error envelope, never a provider error body.
Callback responses and successful owner responses are `Cache-Control: no-store`
and `Referrer-Policy: no-referrer`.

## State, PKCE, replay, and race protection

Connect creates 32 random bytes of state (43 URL-safe characters), a 64-byte
random PKCE verifier (86 URL-safe characters), and SHA-256/base64url S256 challenge.
The exact configured callback URI is used in authorization and code exchange.

Redis stores only the SHA-256 state fingerprint in keys, not the external state.
The bounded server-side payload contains owner UUID, connection UUID, attempt UUID,
PKCE verifier, creation time, and expiry. Both owner index and transaction expire
after 600 seconds. An atomic Lua operation replaces the previous owner attempt;
only one live transaction per owner is retained. The existing rate limiter allows
five initiation attempts per owner per 600 seconds. Redis failure fails closed;
there is no process-memory fallback.

A second Lua operation atomically consumes state before code exchange. Replay,
unknown state, malformed state, and Redis-expired state fail safely. A payload
whose explicit expiry has elapsed maps to `digilocker_callback_expired`; a missing
Redis key intentionally does not disclose whether it expired or was consumed.
Provider denial also consumes the attempt. Failed attempts require a new connect.

The DB's pending attempt UUID fences callbacks that were already consumed while
a newer connect, disconnect, or deletion won the owner lock. The callback checks
the owner again after waiting. Owner locking also serializes refresh rotation and
disconnect, preventing concurrent refresh overwrites and deletion resurrection.

## Runtime configuration

All names follow the existing typed Settings environment convention:

| Variable | Requirement |
| --- | --- |
| `DIGILOCKER_ENABLED` | Default false. |
| `DIGILOCKER_CLIENT_ID` | Required when enabled; runtime configuration only. |
| `DIGILOCKER_CLIENT_SECRET` | Required when enabled; `SecretStr`, omitted from repr. |
| `DIGILOCKER_REDIRECT_URI` | Exact HTTPS registered URI ending in `/api/v1/integrations/digilocker/callback`. |
| `DIGILOCKER_AUTHORIZE_URL` | Approved environment-specific HTTPS authorization endpoint. |
| `DIGILOCKER_TOKEN_URL` | Approved environment-specific HTTPS token endpoint. |
| `DIGILOCKER_REVOKE_URL` | Approved environment-specific HTTPS revocation endpoint. |
| `DIGILOCKER_CONNECTION_RETURN_URL` | Optional exact Candidate completion URL; otherwise JSON. |
| `DIGILOCKER_PURPOSE` | Required when enabled; runtime-configured consent purpose. |
| `DIGILOCKER_SERVICE_NAME` | Required when enabled; runtime-configured service/application label. |
| `DIGILOCKER_CONSENT_TTL` | Optional consent lifetime in seconds, 60 through 31,536,000. |
| `DIGILOCKER_REQ_DOCTYPES` | Optional comma-separated approved document-type codes; no defaults. |
| `DIGILOCKER_TOKEN_ENCRYPTION_ACTIVE_KEY_ID` | Public identifier of the active key. |
| `DIGILOCKER_TOKEN_ENCRYPTION_KEYS` | Secret JSON object: key IDs to canonical base64-encoded 32-byte keys. |

The published contract baseline is [Requester / MeriPehchaan v2.4, September
2026](https://cdn.apisetu.gov.in/portal/assets/Requester-MeriPehchaan-APISpecificationv2.4.pdf),
authorization parameters on page 5. Both consent labels are required when enabled
and accept only ASCII letters, digits, spaces, and underscores. Blank labels are
rejected. That definition supplies no maximum length or fixed purpose enum, so
neither is invented here. Values are preserved and URL-encoded exactly once;
no product label or final purpose text is hardcoded. When disabled, these fields
may remain unset under the existing startup conventions.

Final Stage label values and any portal-matching requirements need portal/provider
confirmation. The authorization builder still emits no explicit `scope` parameter:
grant-response scope filtering is not a scope request or evidence of assigned
permissions. Stage scope assignment remains portal-dependent; do not add scopes
merely because their names occur in the specification. The portal authentication
dropdown is not the OAuth grant: the operator-reported API Setu STAGE generator
uses `grant_type=authorization_code`, regardless of a `client_credentials` label
in its token-authentication-method setting. The sanitized generated Python example
uses form-body client credentials, not HTTP Basic, for authorization-code exchange.

### Approved STAGE NSSO endpoint alignment (2026-09-24)

The operator reports that the registered KairoID STAGE Auth Partner's live API
Setu generator selects the following endpoints. Keep them explicitly configured;
do not introduce application defaults or change production configuration:

```text
DIGILOCKER_AUTHORIZE_URL=https://digilocker.meripehchaan.gov.in/public/oauth2/2/authorize
DIGILOCKER_TOKEN_URL=https://digilocker.meripehchaan.gov.in/public/oauth2/2/token
```

Only these two endpoint settings replace the previous `/1` values. The revoke
endpoint is unchanged. Authorization remains `response_type=code`; exchange
remains POST form-encoded with exactly `code`, `grant_type`, `redirect_uri`,
`code_verifier`, `client_id`, and `client_secret`, without an Authorization header.
Configured credentials are supplied directly to form serialization and never logged.
The grant remains `authorization_code`; refresh/revoke authentication is unchanged.
Redirect URI, state, S256 PKCE, Redis routing, token encryption, response parsing
and all public API contracts are unchanged.

The operator supplied a sanitized generated request: authorization has response_type,
client_id, state, redirect_uri, code_challenge, code_challenge_method and dl_flow.
KairoID now explicitly sends `dl_flow=signin` as generated. Token endpoint, form
field names and form-body credential placement match the supplied example.
Existing purpose/service_name remain deliberately present; the example's omission
does not establish that the endpoint rejects them. Optional configured
req_doctype/consent_valid_till also remain unchanged. scope, acr, amr and prompt
remain absent. Do not add identity-data scopes or silently remove consent labels.
Any live rejection of those parameters requires review
before another source/configuration change. Refresh/revoke and live OAuth are
not exercised by endpoint-alignment certification.

HTTPS endpoint configuration rejects credentials, queries, fragments, IP literals,
localhost, nonstandard ports, and malformed URLs. The staging callback may not be
the production API host; a production callback may not be a staging host.
Deployment operators must additionally verify the approved provider endpoints and
registered redirect URI for their environment; no live provider defaults are baked in.

Missing or invalid enabled configuration fails startup/config access. There are no
fallback credentials or ephemeral keys. Key/config errors are intentionally safe
RuntimeError subclasses so Pydantic does not echo secret-bearing invalid inputs.

Enabling requires canonical sanitized application access logging (`LOG_ACCESS_ENABLED`
true), no DEBUG logging, and no SQL echo. In development, explicitly disable SQL
echo before enabling. This prevents native access logs recording callback queries
and SQL debug output recording encrypted envelopes. Do not enable HTTP wire/body
logging. Proxy/load-balancer logging must also be reviewed before live enablement.

## Encryption and rotation

Uses `cryptography`'s maintained `AESGCM`, declared directly as
`cryptography>=50.0.0,<51`; the local validated runtime is 50.0.0. No custom
cryptographic primitives are implemented. Each independently random key is exactly
32 bytes (AES-256). Every encryption uses `secrets.token_bytes(12)` for a fresh
96-bit nonce. AESGCM supplies its authentication tag.

The persisted JSON envelope has exactly four keys:
`version` (integer 1), `key_id`, `nonce` (canonical base64), and `ciphertext`
(canonical base64 ciphertext plus authentication tag). There are no plaintext
token fields or parallel plaintext columns.

AAD is UTF-8/ASCII canonical JSON with sorted keys and fixed separators, containing:

- domain `kairoid:provider-token`
- envelope version 1 and key ID
- environment
- provider `digilocker`
- immutable Kairo user UUID
- connection UUID (the existing public/immutable UUID convention)
- token purpose `access_token` or `refresh_token`

This binds ciphertext to the owner, connection, provider, environment, key metadata,
and token purpose. Transplantation and authenticated-data modification fail closed.
Envelope shape, version, key ID, base64 encoding, sizes, and tag are validated.
Tokens must be nonempty/non-whitespace UTF-8 strings no larger than 16 KiB.

The small key ring accepts 1-8 entries. Duplicate JSON IDs, duplicate key material,
invalid IDs/lengths, missing active keys, and malformed JSON are rejected. Encrypt
uses only the active key; decrypt uses only the recorded key ID, never trial keys.
Rotation adds an independently generated key, makes it active, and retains older
keys for decrypt. Newly issued/refreshed token values use the active key. If the
provider omits a replacement refresh token, its previous envelope remains intact.
There is no bulk re-encryption job. Do not remove an old key until its retained
ciphertexts have been replaced or disconnected.

Staging IDs require the `staging-` prefix; production IDs require `production-`.
AAD also separates environments. **Actual staging and production key bytes must
be generated independently and must never be copied between environments.**
One environment cannot prove another environment's key material differs without
accessing it; independent provisioning and operator review are therefore required.
No cross-environment secret access or AWS key provisioning occurred here.

Later approved provisioning must use dedicated, environment-separated AWS Secrets
Manager secret values injected via ECS `secrets`, not plaintext task environment.
The client secret and key-ring JSON must not be placed in source, committed env
files, command lines/history, reports, Swagger examples, logs, or the database.
Use existing narrowly scoped execution-role injection conventions. No exact AWS
resource creation or IAM changes are authorized by DL-B1.

Business services use the wrapper, not raw AESGCM. Safe categories distinguish
malformed envelope, unknown version/key, authentication failure, and invalid key
configuration without exposing details to clients. Token/transaction dataclasses
have no field repr; plaintext is wrapped in SecretStr and not globally cached.
Python immutable strings cannot be reliably zeroized. This implementation does
not claim zeroization or protection against a compromised running backend process.

## Provider and token lifecycle

The narrow async HTTP client supports authorize URL construction, code exchange,
refresh, and revocation only. Exchange sends Basic client authentication,
authorization_code, exact redirect URI, code, and PKCE verifier. Refresh and revoke
also use Basic authentication. Redirect following is disabled. Connect/pool waits
are bounded at 3 seconds, read/write at 10 seconds, total request at 15 seconds;
token response content is capped at 64 KiB. No automatic provider retry is used.

Only valid Bearer token grants with bounded positive integer `expires_in` are
accepted. Optional consent expiry must be a future integer UNIX timestamp.
Provider errors are mapped to stable Kairo codes: `digilocker_provider_unavailable`,
`digilocker_not_configured`, `digilocker_storage_unavailable`,
`digilocker_callback_invalid`, `digilocker_callback_expired`,
`digilocker_consent_denied`, and `digilocker_reconnect_required`.

Refresh starts within 60 seconds of access-token expiry. A missing replacement
refresh token, scope, or consent value preserves its existing value. Expired
consent, unusable encryption, missing usable refresh credentials, or invalid_grant
erases local tokens and requires reconnect. A transient provider outage fails
closed but retains ciphertext for a later attempt. Status never falsely reports
expired unrefreshable credentials as connected. A still-usable active connection
must be explicitly disconnected before connecting again.

Disconnect attempts remote refresh/access revocation, then always clears local
envelopes, expiry, scopes, consent, and pending attempt metadata when its DB commit
succeeds. Remote revocation is best effort, not guaranteed if disabled, keys are
unavailable, or the provider is unavailable. Database failure returns an error,
never false success. Provider tokens obtained before a persistence failure are
best-effort revoked. There is no provider refresh/revoke background job in DL-B1.

## Persistence, privacy, and deletion

Migration `080`, parent `079`, creates only `digilocker_connections`. No existing
table is altered. It has one row per user, a cascading owner FK, status/envelope
constraints, and no custom database enum artifacts. Migration must precede any
future deployment of this source, including when the integration remains disabled.
Local/test downgrade drops only this table and its contained connection data.
No staging migration is authorized or performed.

Stored fields: UUID id/user_id, encrypted access/refresh envelopes, access expiry,
consent expiry, safe scope list, pending attempt UUID/expiry, connection status,
connected/refreshed/revoked timestamps, created/updated timestamps. Provider is
implicit in the table and explicit in AAD; no provider account reference is needed.

Never retained: Aadhaar/PAN/Driving Licence numbers, provider account ID/name,
DOB, gender, address, profile picture, reference_key, raw profile/token response,
document content, or document identifiers. DigiLocker scope strings can themselves
contain identity numbers. Only known non-identifying generic scope names are
retained; document-specific and unrecognized scopes are discarded. Stored scopes
are metadata, not a claim of verified documents or authorization for DL-B2 import.

Existing DB-first deletion explicitly deletes the DigiLocker row in the same
transaction as the Candidate tombstone. Rollback preserves both consistently.
After commit it best-effort clears the owner's Redis transaction. If Redis is down,
600-second TTL bounds remnants and the deleted-owner check blocks callback reuse.
No new deletion workflow, remote provider job, retained token copy, or live account
deletion QA is introduced. Automated tests use disposable local synthetic accounts.

Privacy-safe lifecycle log events:
`digilocker_connect_started`, `digilocker_connected`, `digilocker_connect_failed`,
`digilocker_token_refreshed`, `digilocker_disconnected`. Payloads contain only fixed
safe categories where needed, never tokens, codes, ciphertext, keys, provider
identity payloads, or document data. Existing request correlation remains unchanged.

## Validation and later gates

Tests cover encryption/tampering/rotation, configuration failures, mocked HTTP,
real Redis Lua replay/supersession/TTL, PostgreSQL encrypted persistence and
constraints, parallel callback/refresh, ownership, deletion fencing/rollback,
disconnect failure, route contracts, and OpenAPI. No live DigiLocker/API Setu call
is used. Run the backend regression suite with disposable test PostgreSQL/Redis;
set DATABASE_URL, MIGRATION_DATABASE_URL, and REDIS_URL only to local test services.

Before live enablement: review source and migration, separately approve secure
environment provisioning, register the exact callback, verify provider-approved
endpoints/consents, inspect ingress logging, and obtain controlled staging QA
approval. DL-B2 remains out of scope: document listing/download/import, Aadhaar
XML, HMAC/document verification, Education/Evidence mapping, Trust Score, any
verification status changes, and mobile UI.

Primary provider references reviewed for the wire contract:

- https://apisetu.gov.in/digilocker
- https://cf-media.api-setu.in/resources/Requester-APISpecification-V1_12.pdf
- https://cdn.apisetu.gov.in/portal/assets/Requester-MeriPehchaan-APISpecificationv2.4.pdf
