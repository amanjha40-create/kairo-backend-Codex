# File-free DigiLocker identity verification (DL-B3)

Migration 081 adds only `digilocker_identity_verifications`. No UserDocument,
storage object, raw file, full identifier, name or DOB snapshot is created.
The current verification is unique by owner, document type and domain-separated
SHA-256 provider-reference fingerprint. The fingerprint is internal, not public.
Source is `digilocker`, source type is `issued_document`.

## API and consent

Authenticated Candidate endpoints under `/api/v1/integrations/digilocker`:

- `POST /identity/verify`: `{document_types: ["PANCR", "DRVLC"], consent: true,
  consent_version: "v1"}`. One or two distinct types, no URI or owner override.
- `GET /identity/verifications`: safe historical results and `identity_verified`.

Each POST obtains the current owner's issued inventory and requires exactly one
distinct supported URI per selected type. Missing/ambiguous selection fails
before file retrieval. The owner lock serializes matching and deletion; a unique
constraint prevents duplicate persistence. Each explicit repeat updates the same
record and latest consent. There is no automatic POST retry. Provider failure
rolls back the entire selected batch, never persisting a new successful result.
HMAC failure persists only failed integrity / UNABLE_TO_VERIFY, with no parsing.

## Matching boundary

The supported parser is the standard machine-readable XML Certificate or its
base64 DataContent envelope. Format reference:
[API Setu XML formats](https://docs.apisetu.gov.in/document-central/dl-xml-format/)
and [PAN/DL structures](https://docs.apisetu.gov.in/document-central/dl-xml-format/Appendix.html).
DTD, entities and external references are prohibited. XML is bounded at 1 MiB
and 500 elements. Exactly one IssuedTo/Person and the selected Certificate type
are required. PDFs/images are not OCR'd or guessed: UNABLE_TO_VERIFY.

Matching uses NFKC/case folding, periods and whitespace normalization only.
Names are not reordered, expanded or fuzzily matched. A comparable conflicting
name or DOB is MISMATCH. Matching name and exact DOB is VERIFIED_MATCH; only one
comparable matching fact is PARTIAL_MATCH. Missing facts are not invented.
Malformed facts, inactive certificates and expired/not-yet-valid DLs cannot verify.
An omitted expiry makes no claim of independently established licence currentness.

Raw bytes and extracted facts remain transient and are not returned or logged.
Historical consent/result remains after ordinary disconnect/reconnect. A nullable
connection FK uses SET NULL. Hard user deletion cascades; the existing account
tombstoning transaction explicitly deletes these rows as well.

`profile_revision_at` holds a timestamp, not personal facts. A profile edit or
subsequent document expiry invalidates the current badge without rewriting the
historical result. A new consented check is needed. This conservatively invalidates
on any profile-row edit rather than silently verifying changed personal details.

No Trust Score recalculation, snapshots, points, OAuth refresh/revoke or unrelated
verification workflow is invoked. Token expiry requires reconnect, not automatic
refresh. Owner history is readable without an active provider connection.

The staging web DigiLocker page displays consent and per-document results. Native
and production gates remain unchanged. Profile/Verify overview/public Passport
projection is deferred; these records are not implicitly granted public share
permission or connected to existing uploaded-document scoring.
