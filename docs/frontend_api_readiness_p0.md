# Frontend API Readiness (P0)

## Scope

This document maps the current FastAPI backend surface to the investor-MVP frontend path.

Goal:
- identify which frontend mock-backed areas can already switch to real APIs
- identify contract risks before frontend cutover
- identify blockers that still require backend work

Out of scope for this document:
- DigiLocker
- resume parsing
- dashboard redesign
- Trust Score redesign

## Auth endpoints available

Primary auth endpoints already available:

| Purpose | Method | Endpoint | Notes |
| --- | --- | --- | --- |
| Start signup | `POST` | `/api/v1/auth/register` | Sends OTP, returns `signup_session_id` |
| Start signup (explicit alias) | `POST` | `/api/v1/auth/signup/start` | Same behavior as `/register` |
| Verify signup OTP | `POST` | `/api/v1/auth/signup/verify` | Issues access + refresh tokens |
| Resend signup OTP | `POST` | `/api/v1/auth/signup/resend` | Resend flow available |
| Login | `POST` | `/api/v1/auth/login` | Email/password |
| Forgot password | `POST` | `/api/v1/auth/forgot-password` | Generic `202`, non-enumerating |
| Reset password | `POST` | `/api/v1/auth/reset-password` | One-time hashed token, expiry enforced |
| Refresh | `POST` | `/api/v1/auth/refresh` | Refresh token rotation |
| Logout | `POST` | `/api/v1/auth/logout` | Revokes presented refresh token |
| Set password | `POST` | `/api/v1/auth/set-password` | For social-only accounts |
| Change password | `POST` | `/api/v1/auth/change-password` | Authenticated current-password flow |
| Provider auth URL | `GET` | `/api/v1/auth/{provider}/url` | Google / LinkedIn / GitHub |
| Provider callback | `POST` | `/api/v1/auth/{provider}/callback` | Exchanges provider auth code |

## Profile and vault endpoints available

Authenticated user/profile endpoints:

| Purpose | Method | Endpoint |
| --- | --- | --- |
| Current user profile | `GET` | `/api/v1/users/me` |
| Update profile | `PATCH` | `/api/v1/users/me` |
| Avatar upload intent | `POST` | `/api/v1/users/me/avatar-upload-url` |
| Complete onboarding flag | `POST` | `/api/v1/users/me/complete-onboarding` |
| Profile share analytics (legacy profile-view analytics) | `GET` | `/api/v1/users/me/share-analytics` |
| Current trust score | `GET` | `/api/v1/trust-score` |

Vault/domain CRUD already available:

| Domain | Endpoints available |
| --- | --- |
| Employments | `/api/v1/employments/*` |
| Employment documents | `/api/v1/employment-documents/*`, `/api/v1/documents/*` |
| Educations | `/api/v1/educations/*` |
| Internships | `/api/v1/internships/*` |
| Freelance contracts | `/api/v1/freelance-contracts/*` |
| Gig platforms | `/api/v1/gig-platforms/*` |
| Portfolio | `/api/v1/portfolio/*` |
| Certifications | `/api/v1/certifications/*` |
| User documents | `/api/v1/user-documents/*` |

## Passport share endpoints available

Authenticated Trust Passport sharing endpoints:

| Purpose | Method | Endpoint | Notes |
| --- | --- | --- | --- |
| Create share link | `POST` | `/api/v1/passport-shares` | Returns raw `share_url` only once |
| List my share links | `GET` | `/api/v1/passport-shares` | Paginated |
| Get one share link | `GET` | `/api/v1/passport-shares/{share_id}` | No raw token returned |
| Update share link | `PATCH` | `/api/v1/passport-shares/{share_id}` | Permissions / label / expiry |
| Revoke share link | `POST` | `/api/v1/passport-shares/{share_id}/revoke` | Revocation is server-authoritative |
| Share analytics | `GET` | `/api/v1/passport-shares/{share_id}/analytics` | Owner-only |

## Public Trust Passport endpoint available

Backend-authoritative public Trust Passport:

| Purpose | Method | Endpoint | Notes |
| --- | --- | --- | --- |
| View public Trust Passport | `GET` | `/api/v1/public/passport/{token}` | Enforces unknown/revoked/expired fail-closed behavior |

Returned payload includes:
- `profile`
- `trust_score`
- `vault`
- `share`

This is the recommended public-facing endpoint for the frontend investor demo.

## Analytics endpoint available

Owner-only share analytics:

| Purpose | Method | Endpoint | Returned data |
| --- | --- | --- | --- |
| View share analytics | `GET` | `/api/v1/passport-shares/{share_id}/analytics` | `share_id`, `total_views`, `unique_views`, `last_viewed_at`, `recent_views` |

## Missing backend endpoints

The following gaps still remain for a clean full-frontend cutover:

1. No single authenticated "my Trust Passport" aggregation endpoint.
   The public endpoint is complete, but the authenticated frontend still has to compose the owner view from:
   - `/users/me`
   - `/trust-score`
   - vault domain endpoints
   - `/passport-shares/*`

2. No authenticated "passport preview by current user" endpoint.
   The frontend can render a private passport view by aggregating data client-side, but there is no one-call backend view-model yet.

3. No onboarding progress/completion breakdown endpoint.
   There is a completion flag endpoint, but no backend-authored progress meter for adaptive onboarding screens.

4. No resume/KYC/DigiLocker endpoints in the current P0 path.
   These remain blockers for those specific frontend flows, but they are out of scope for this sprint.

5. No QR/PDF export endpoint for Trust Passport shares.

6. No delete endpoint for share links.
   Current lifecycle is create, update, list, inspect, revoke.

7. No dashboard aggregation endpoint for investor-demo summary cards.

## Response shape risks

Frontend integration should account for the following current contracts:

1. Auth success payloads are mostly bare DTOs, not `{ data: ... }` envelopes.

2. Error payloads are standardized as:
   ```json
   {
     "error": {
       "code": "string",
       "message": "string"
     }
   }
   ```

3. `POST /api/v1/auth/forgot-password` always returns the same generic `202` response.
   The frontend must not expect existence confirmation.

4. Paginated list endpoints return:
   - `items`
   - `total`
   - `offset`
   - `limit`

5. Trust Passport share creation returns `share_url` only at create time.
   The frontend must not expect raw tokens or URLs from list/detail endpoints later.

6. The public Trust Passport payload is nested and opinionated:
   - `profile`
   - `trust_score`
   - `vault`
   - `share`

7. Legacy public routes still exist:
   - `/api/v1/public/profile/{slug}`
   - `/api/v1/public/vault/{slug}`
   These should not be the default integration path for the investor demo because `/api/v1/public/passport/{token}` is now the authoritative product contract.

8. File upload flows are two-step flows.
   Most document APIs expect:
   - upload intent
   - client upload to object storage
   - complete-upload confirmation

## Auth requirements

Authentication expectations for frontend integration:

1. Private endpoints require Bearer access tokens in the `Authorization` header.

2. Access tokens are short-lived JWTs.

3. Refresh token rotation is server-side and uses `POST /api/v1/auth/refresh`.

4. Signup requires OTP verification before the user receives tokens.

5. Public Trust Passport access requires no auth, but is controlled by opaque share tokens.

6. Share analytics is owner-only and fails closed for non-owners.

## Exact frontend mock areas that can now be replaced

The following frontend mock-backed areas can switch to live backend APIs now:

1. Signup, OTP verification, resend OTP, login, refresh, logout.

2. Forgot-password and reset-password screens.

3. Current-user profile fetch and edit flows.

4. Trust Passport share creation, listing, detail, update, and revocation.

5. Public Trust Passport page using `/api/v1/public/passport/{token}`.

6. Share analytics views using `/api/v1/passport-shares/{share_id}/analytics`.

7. Vault CRUD screens for:
   - employments
   - educations
   - internships
   - freelance contracts
   - gig platforms
   - portfolio
   - certifications
   - user documents

8. Trust score display via `/api/v1/trust-score` for authenticated views and via `public.passport.trust_score` for shared public views.

## Exact blockers before frontend integration

The main blockers are no longer auth/share primitives. They are integration-shape and aggregation issues:

1. The frontend needs a contract map for which owner-facing screen reads which combination of endpoints.

2. If the frontend expects a single owner-passport payload, that aggregation is still missing.

3. If the frontend currently assumes direct file upload to backend endpoints instead of upload-intent + complete-upload, those flows need frontend adaptation.

4. If the frontend still reads from legacy public profile/public vault mocks, it should be migrated to the public Trust Passport contract instead.

5. Dashboard/home summary widgets still need backend aggregation work if the frontend expects one-call summary APIs.

6. Resume-first onboarding, KYC, DigiLocker, and verification-provider flows remain blocked by out-of-scope backend work.

## Low-risk correctness fixes needed right now

None identified in this sprint.

The main recommendation is to keep Commit 2 documentation-only and let the frontend cutover work happen against the current backend contracts rather than changing the backend surface again before the integration starts.
