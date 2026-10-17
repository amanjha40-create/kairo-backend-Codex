# Existing Candidate Mobile Verification

Additive contract; no migration, signup session, arbitrary destination or bypass.
This source is not evidence that the routes are deployed in Production.

## Candidate Web Handoff

Both routes require the normal bearer session for an active, email-verified
Candidate. The user is selected from that session, never a request field.

- POST `/api/v1/auth/mobile-verification/request`, JSON `{}`. Use the same route
  for resend, only after the advertised cooldown. Extra fields are rejected.
- POST `/api/v1/auth/mobile-verification/verify`, JSON `{"code":"<six digits>"}`.
  The code must be entered privately in the Candidate UI, never logged.
- Response fields: `state` (`code_sent`, `verified`, `phone_required`),
  `phone_verified`, `resend_after_seconds`, `expires_in_seconds`.
- `phone_required`: use the proper existing profile phone-addition flow; do not
  allow a destination in either verification request.
- HTTP401: missing/invalid session or invalid/expired code (standard error code
  distinguishes the error message); HTTP403: wrong role/email not verified;
  HTTP422: malformed/extra fields; HTTP429: cooldown/cap with Retry-After;
  HTTP503: delivery/configuration failure. Do not retry sends automatically.
- On `verified`, invalidate/refetch `/users/me` and `/onboarding/status` and use
  the canonical current_step. Home is allowed only for complete onboarding;
  profile completion may still be required. Never synthesize verified state.

No Candidate/Android/iOS implementation is included in this backend change.
Do not expose Send code until the deployed contract and provider configuration
are certified. Do not fall back to pre-account signup endpoints.

## Controls

Uses SignupOtpStore with an isolated existing_mobile scope and the same secure
six-digit generator, SHA256-at-rest hash and atomic Lua consume as signup.
Existing signup keys/contracts remain unchanged. Request always targets the
current stored, normalized phone. Redis metadata binds an HMAC of that number,
not plaintext phone. The existing user row lock serializes send/verify with
profile/deletion writes; successful verification atomically updates the existing
phone_verified_at field. No second account or pending-signup row is created.

Defaults: 30-second resend cooldown, five sends/hour per user and destination,
five verification attempts per 600-second window. Resend does not reset attempt
budget. Expiry is the minimum of canonical OTP TTL and MSG91 expiry (currently
300 seconds). Incorrect, expired, replaced and consumed codes fail closed.
Provider or database failure after consumption requires a new code rather than
replaying an external validation. Verified users return safely without sending.

MSG91 recovery uses SendOTP with a new generated `otp`, not `/otp/retry` (which
resends the same code). It retains canonical MSG91 validation after local hash
consumption. This also locally invalidates previous codes independent of provider
state. Signup's existing provider-generated flow remains supported. Production
must use msg91 or sns, never console/staging_fixed; existing configuration
validation enforces that. No provider delivery was exercised by synthetic tests.

Official contract: https://docs.msg91.com/otp/sendotp (optional `otp`: caller's
code); https://docs.msg91.com/otp (retry resends the same OTP). Read 2026-10-17.

Provider response text is never copied into structured logs. OTP/authkey/mobile
query values are redacted before configured application log output; safe audit
event account_mobile_verified records completion without OTP/phone values.

## Release Boundary

Based on canonical launch source410abd2, schema091 unchanged. Production API30
still uses DB074. Do not deploy this canonical091 artifact over API30/DB074 as an
isolated recovery hotfix. Repin the prepared launch image/definitions through an
explicit release step, preserving every reviewed environment/IAM/network field;
revalidate the launch package and migration provenance. No feature activation,
AWS change, schema migration or real OTP is authorized by these source tests.
