# V1.1 Client Handoff

No client source was modified. Exact server OpenAPI comparison against the deployed
baseline is a certification gate. No route, enum, required field or nullable field
is intentionally changed in this batch. Security denial behavior is intentionally
stricter and needs the handling below.

Read-only source references examined:
- Candidate Web `61aae89038bc41bc9fa40204914b3d2a628ba4bf`,
  `src/features/auth/api/auth.api.ts`, `src/routes/verify-identity.tsx`.
- Android `3a65146ea7dc046672090ed4fd86287f6f7bc6fe`, same auth adapter/route.
- iOS checkout `22d8c5988f7cd5ac4b0e9548216249a92bba674d`,
  `Kairo/Core/Auth/AuthService.swift`, `Kairo/Core/API/DTOs/AuthDTOs.swift`.
These are observed local client sources, not claims about currently installed or
deployed client binaries. No client build or device QA was run for this backend task.

| Contract | Existing/corrected behavior | Candidate Web | Android | iOS |
| --- | --- | --- | --- | --- |
| POST /api/v1/auth/signup/start | Restart returns fresh signup_session_id | Persist latest returned ID | Same | Replace stored signup ID |
| POST /api/v1/auth/signup/complete | First completion unchanged; replay returns 409 instead of issuing tokens | Offer normal sign-in after lost completed response; no retry loop | Same | Clear/handle completed session and offer normal sign-in |
| Signup recovery | Completed status remains readable; it is not authentication | No DTO change | No DTO change | No DTO change |
| Refresh | Concurrent token consumption serialized; replay remains rejected | Single-flight refresh recommended | Same | Same |
| Password reset | Exactly one valid consumption | Existing error handling | Existing error handling | Existing error handling |
| Profile PATCH phone | Explicit clear nulls phone and verification | Refetch onboarding/contact state | Same | Same |
| Generic created_after/created_before lists | UTC-safe comparison, whole date-before day | No change required | No change required | No change required |
| Forced legacy page envelopes | Full legacy list retained even above input page-size cap | No change required | No change required | No change required |
| Organization request evidence list | Consent filter precedes metadata/URL output | Do not assume unconsented evidence is visible | No Candidate DTO change | No Candidate DTO change |
| Public Vault | Current/historical address-proof metadata absent | No change required | No change required | No change required |
| Public Passport JSON/photo | Inactive/deleted owner fails with generic 404 | Existing unavailable state | Same | Same |
| Dashboard/share analytics | Same counts, constant query count | No change required | No change required | No change required |
| Trust identity source | Expired/superseded manual documents no longer establish current identity | Render backend truth, never recalculate locally | Same | Same |
| Production connector | Mock implementation unavailable | Do not show mock result as verified evidence | Same | Same |
| DigiLocker / Permanent Address | Existing contracts unchanged | No change required | No change required | No change required |

## Compatibility Limits and Follow-ups

Successful requests and wire schemas remain compatible. Signup completion replay
is not behaviorally identical: all clients must recover through normal sign-in if
the original completion response was lost. Existing Web/Android routes display a
completion error; iOS propagates it. Do not claim those screens already provide the
ideal recovery CTA; that is a client follow-up, not a reason to retain reusable
unauthenticated login capability.

Incomplete imported Career records currently conflict with required public/freelance
response fields. Widening those fields to null can break released decoders, while
inventing dates or hiding records changes product truth. D03 is held for coordinated
contract/client approval. D01/D02 also require a decided edit/reverification model.

Profile-view recruiter/company labels are not authoritative actor/company metrics;
score completeness is not whole-profile completion. Clients should not promote
these as stronger claims. Notification/security events must only be displayed when
actually produced; session rows are not guaranteed physical-device identities.

The exact method/path inventory is `backend-v1-1-api-inventory.md`; remaining
decisions and source-only boundaries are in `backend-v1-1-core-api-audit.md`.
