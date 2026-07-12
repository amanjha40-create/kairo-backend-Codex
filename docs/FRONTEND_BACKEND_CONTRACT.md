# Frontend Backend Contract

This document is the shared source of truth for the current Kairo frontend and backend integration.

Scope for the current implementation batch:

- Phase 1 only
- authentication
- staged dual-channel signup verification
- password reset
- session lifecycle
- onboarding status
- quick profile onboarding

Out of scope for this phase:

- dashboard integration
- owner Trust Passport integration
- employment CRUD integration
- evidence and document upload integration
- verification request submission integration
- passport sharing integration
- admin and organization UI integration
- resume parsing and resume review flows

## Global Decisions

### API base URL

`VITE_API_BASE_URL` must be host-only.

Examples:

- `http://localhost:8000`
- `https://api.kairoid.com`

Do not include `/api/v1` in the environment variable.

Frontend endpoint constants must include `/api/v1/...` explicitly.

### Naming convention

Backend wire format remains `snake_case`.

Frontend route components and view models use `camelCase` through adapters in the API layer.

Rules:

- request bodies sent to the backend use `snake_case`
- response DTOs parsed from the backend use `snake_case`
- frontend UI state maps those DTOs into `camelCase` models outside route components
- do not mix `snake_case` and `camelCase` in the same wire contract

### Error contract

The frontend must consume the shared backend error envelope:

```json
{
  "error": {
    "code": "string",
    "message": "string",
    "details": []
  }
}
```

Rules:

- `error.code` is the stable machine-readable key
- `error.message` is the primary display message
- `error.details` is optional and mainly used for validation failures
- `401`, `403`, `404`, `409`, `422`, `429`, `500`, and `503` must all be handled through the same parser

### Empty responses

The frontend API client must treat `204 No Content` as a successful empty response and must not attempt JSON parsing.

### Token lifecycle

Access token and refresh token remain the backend source of truth.

Rules:

- backend login and signup completion return:

```json
{
  "access_token": "string",
  "refresh_token": "string",
  "token_type": "bearer",
  "expires_in": 900
}
```

- frontend stores both tokens in its session layer
- authenticated API calls send the access token as `Authorization: Bearer <token>`
- on one `401` response, the frontend may attempt exactly one refresh using the refresh token
- if refresh succeeds, the original request is replayed once
- if refresh fails, the frontend clears session state and routes to `/login`
- logout sends the current `refresh_token`
- logout clears local session state even if the logout request fails
- signup start and OTP verification use `signup_session_id`, not bearer tokens

### Onboarding state ownership

The backend owns onboarding state.

The frontend must route from backend facts, not from locally persisted onboarding flags.

Canonical backend onboarding state for this phase:

- `verify_identity`
- `complete_profile`
- `complete`

Frontend route mapping for this phase:

- `verify_identity` -> `/verify-identity`
- `complete_profile` -> `/start-method`, then `/quick-profile`
- `complete` -> `/passport-created`

### Deferred resume path

Resume import is deferred until a real backend engine exists.

Current frontend behavior must be:

- keep resume routes behind a disabled feature flag
- keep quick profile as the active onboarding path
- do not call fake resume APIs

## Authentication And Onboarding Contract

### 1. Signup start

Feature/screens:

- `/signup`

Endpoint:

- `POST /api/v1/auth/signup/start`

Authentication:

- none

Request JSON:

```json
{
  "full_name": "Aman Jha",
  "email": "aman@example.com",
  "phone": "+919876543210",
  "password": "StrongPassword123!"
}
```

Response JSON:

```json
{
  "signup_session_id": "uuid",
  "email_masked": "am***@example.com",
  "phone_masked": "+91******3210",
  "email_verified": false,
  "phone_verified": false,
  "email_resend_after_seconds": 30,
  "phone_resend_after_seconds": 30,
  "expires_in_seconds": 900,
  "message": "Verification codes sent"
}
```

Errors:

- `409 conflict` when the account cannot be created because email or phone is already registered
- `422 validation_error` for invalid email, phone, or password
- `429 rate_limited`

Frontend TypeScript adapter:

- request model: `{ fullName, email, phone, password }`
- maps to wire DTO `full_name`, `email`, `phone`, `password`
- stores only `signupSessionId` after success

Backend implementation status:

- backend change required

Owning side:

- backend and frontend

Integration status:

- both required

### 2. Email OTP send

Feature/screens:

- `/verify-identity`

Endpoint:

- `POST /api/v1/auth/signup/email/send`

Authentication:

- none

Request JSON:

```json
{
  "signup_session_id": "uuid"
}
```

Response JSON:

```json
{
  "signup_session_id": "uuid",
  "channel": "email",
  "email_masked": "am***@example.com",
  "verified": false,
  "resend_after_seconds": 30,
  "expires_in_seconds": 300,
  "message": "Verification code sent"
}
```

Errors:

- `404 not_found` for unknown or expired signup session
- `429 rate_limited`

Backend implementation status:

- backend change required

Owning side:

- backend and frontend

Integration status:

- both required

### 3. Email OTP resend

Feature/screens:

- `/verify-identity`

Endpoint:

- `POST /api/v1/auth/signup/email/resend`

Authentication:

- none

Request JSON:

```json
{
  "signup_session_id": "uuid"
}
```

Response JSON:

```json
{
  "signup_session_id": "uuid",
  "channel": "email",
  "email_masked": "am***@example.com",
  "verified": false,
  "resend_after_seconds": 30,
  "expires_in_seconds": 300,
  "message": "Verification code sent"
}
```

Backend implementation status:

- backend change required

Owning side:

- backend and frontend

Integration status:

- both required

### 4. Email OTP verify

Feature/screens:

- `/verify-identity`

Endpoint:

- `POST /api/v1/auth/signup/email/verify`

Authentication:

- none

Request JSON:

```json
{
  "signup_session_id": "uuid",
  "code": "123456"
}
```

Response JSON:

```json
{
  "signup_session_id": "uuid",
  "channel": "email",
  "verified": true,
  "email_verified": true,
  "phone_verified": false,
  "message": "Email verified"
}
```

Errors:

- `400 invalid_otp`
- `400 otp_expired`
- `429 rate_limited`

Backend implementation status:

- backend change required

Owning side:

- backend and frontend

Integration status:

- both required

### 5. Phone OTP send

Feature/screens:

- `/verify-identity`

Endpoint:

- `POST /api/v1/auth/signup/phone/send`

Authentication:

- none

Request JSON:

```json
{
  "signup_session_id": "uuid"
}
```

Response JSON:

```json
{
  "signup_session_id": "uuid",
  "channel": "phone",
  "phone_masked": "+91******3210",
  "verified": false,
  "resend_after_seconds": 30,
  "expires_in_seconds": 300,
  "message": "Verification code sent"
}
```

Backend implementation status:

- backend change required

Owning side:

- backend and frontend

Integration status:

- both required

### 6. Phone OTP resend

Feature/screens:

- `/verify-identity`

Endpoint:

- `POST /api/v1/auth/signup/phone/resend`

Authentication:

- none

Request JSON:

```json
{
  "signup_session_id": "uuid"
}
```

Response JSON:

```json
{
  "signup_session_id": "uuid",
  "channel": "phone",
  "phone_masked": "+91******3210",
  "verified": false,
  "resend_after_seconds": 30,
  "expires_in_seconds": 300,
  "message": "Verification code sent"
}
```

Backend implementation status:

- backend change required

Owning side:

- backend and frontend

Integration status:

- both required

### 7. Phone OTP verify

Feature/screens:

- `/verify-identity`

Endpoint:

- `POST /api/v1/auth/signup/phone/verify`

Authentication:

- none

Request JSON:

```json
{
  "signup_session_id": "uuid",
  "code": "123456"
}
```

Response JSON:

```json
{
  "signup_session_id": "uuid",
  "channel": "phone",
  "verified": true,
  "email_verified": true,
  "phone_verified": true,
  "message": "Phone verified"
}
```

Backend implementation status:

- backend change required

Owning side:

- backend and frontend

Integration status:

- both required

### 8. Signup complete

Feature/screens:

- `/verify-identity`

Endpoint:

- `POST /api/v1/auth/signup/complete`

Authentication:

- none

Request JSON:

```json
{
  "signup_session_id": "uuid"
}
```

Response JSON:

```json
{
  "access_token": "string",
  "refresh_token": "string",
  "token_type": "bearer",
  "expires_in": 900
}
```

Rules:

- allowed only after both email and phone are verified
- must be idempotent
- must not create duplicate users when retried

Backend implementation status:

- backend change required

Owning side:

- backend and frontend

Integration status:

- both required

### 9. Login

Feature/screens:

- `/login`

Endpoint:

- `POST /api/v1/auth/login`

Authentication:

- none

Request JSON:

```json
{
  "email": "aman@example.com",
  "password": "StrongPassword123!"
}
```

Response JSON:

```json
{
  "access_token": "string",
  "refresh_token": "string",
  "token_type": "bearer",
  "expires_in": 900
}
```

Backend implementation status:

- ready

Owning side:

- frontend change required

Integration status:

- frontend change required

### 10. Refresh token

Feature/screens:

- authenticated session lifecycle

Endpoint:

- `POST /api/v1/auth/refresh`

Authentication:

- none

Request JSON:

```json
{
  "refresh_token": "string"
}
```

Response JSON:

```json
{
  "access_token": "string",
  "refresh_token": "string",
  "token_type": "bearer",
  "expires_in": 900
}
```

Backend implementation status:

- ready

Owning side:

- frontend change required

Integration status:

- frontend change required

### 11. Logout

Feature/screens:

- `/more`

Endpoint:

- `POST /api/v1/auth/logout`

Authentication:

- none

Request JSON:

```json
{
  "refresh_token": "string"
}
```

Response:

- `204 No Content`

Backend implementation status:

- ready

Owning side:

- frontend change required

Integration status:

- frontend change required

### 12. Forgot password

Feature/screens:

- `/reset-password`

Endpoint:

- `POST /api/v1/auth/forgot-password`

Authentication:

- none

Request JSON:

```json
{
  "email": "aman@example.com"
}
```

Response JSON:

```json
{
  "message": "If an account exists for that email, a password reset email has been sent."
}
```

Rules:

- response must remain generic
- must not reveal whether the email exists

Backend implementation status:

- ready

Owning side:

- frontend change required

Integration status:

- frontend change required

### 13. Reset password confirm

Feature/screens:

- separate frontend confirm-reset route required

Endpoint:

- `POST /api/v1/auth/reset-password`

Authentication:

- none

Request JSON:

```json
{
  "token": "string",
  "new_password": "NewStrongPassword123!",
  "confirm_password": "NewStrongPassword123!"
}
```

Response JSON:

```json
{
  "message": "Password reset successful."
}
```

Backend implementation status:

- ready

Owning side:

- frontend change required

Integration status:

- frontend change required

### 14. Onboarding status

Feature/screens:

- `/login`
- `/verify-identity`
- `/start-method`
- `/quick-profile`
- `/passport-created`

Endpoint:

- `GET /api/v1/onboarding/status`

Authentication:

- bearer token

Response JSON:

```json
{
  "current_step": "verify_identity",
  "email_verified": true,
  "phone_verified": true,
  "passport_ready": false,
  "completed_steps": ["verify_email", "verify_phone"],
  "missing_requirements": ["headline", "current_role", "industry", "years_of_experience"],
  "next_recommended_step": "complete_profile",
  "completion_percentage": 40,
  "is_onboarding_complete": false
}
```

Rules:

- backend remains the source of truth
- response must stay route-agnostic
- frontend maps `current_step` to route navigation

Backend implementation status:

- backend change required

Owning side:

- backend and frontend

Integration status:

- both required

### 15. Quick profile update

Feature/screens:

- `/quick-profile`

Preferred endpoint:

- `PATCH /api/v1/users/me`

Authentication:

- bearer token

Request JSON:

```json
{
  "headline": "Senior Software Engineer",
  "current_role": "Software Engineer",
  "industry": "Technology",
  "years_of_experience": 6
}
```

Response JSON:

```json
{
  "public_id": "uuid",
  "email": "aman@example.com",
  "phone": "+919876543210",
  "full_name": "Aman Jha",
  "headline": "Senior Software Engineer",
  "current_role": "Software Engineer",
  "industry": "Technology",
  "years_of_experience": 6,
  "email_verified": true,
  "phone_verified": true,
  "updated_at": "2026-07-12T10:00:00Z"
}
```

Contract note:

- if `PATCH /api/v1/users/me` already owns these profile fields canonically, it should remain the permanent contract
- only add a dedicated onboarding quick-profile endpoint if orchestration is needed beyond a normal profile update

Backend implementation status:

- backend change required

Owning side:

- backend and frontend

Integration status:

- both required

## Deferred Feature Contract Decisions

The following frontend areas are intentionally deferred and must not call placeholder APIs in this phase:

- `/resume`
- `/resume-processing`
- `/review-import/$importId`
- dashboard widgets
- owner Trust Passport detail screens
- employment CRUD screens
- evidence and document uploads
- verification request submission
- admin review screens
- organization management screens
- passport sharing and public Trust Passport UI
- candidate notifications
- DigiLocker
- references
- support chat

Frontend handling for deferred features:

- hide or disable resume-first entry points behind a feature flag
- keep quick profile as the active onboarding path
- do not ship calls to nonexistent endpoints

## Route By Route Integration Matrix

| Frontend route | Feature | Required endpoint(s) | Backend status | Ownership | Integration status |
| --- | --- | --- | --- | --- | --- |
| `/signup` | staged signup start | `POST /api/v1/auth/signup/start` | backend change required | backend + frontend | both required |
| `/verify-identity` | dual OTP verification | `POST /api/v1/auth/signup/email/send`, `POST /api/v1/auth/signup/email/resend`, `POST /api/v1/auth/signup/email/verify`, `POST /api/v1/auth/signup/phone/send`, `POST /api/v1/auth/signup/phone/resend`, `POST /api/v1/auth/signup/phone/verify`, `POST /api/v1/auth/signup/complete` | backend change required | backend + frontend | both required |
| `/login` | login + onboarding routing | `POST /api/v1/auth/login`, `GET /api/v1/onboarding/status` | partial | frontend primary, backend additive | both required |
| `/reset-password` | forgot password request | `POST /api/v1/auth/forgot-password` | ready | frontend | frontend change required |
| `/reset-password/confirm` | password reset confirm | `POST /api/v1/auth/reset-password` | ready | frontend | frontend change required |
| `/more` | logout | `POST /api/v1/auth/logout` | ready | frontend | frontend change required |
| `/start-method` | onboarding route selection | `GET /api/v1/onboarding/status` | partial | frontend + backend | both required |
| `/quick-profile` | minimal profile onboarding | `PATCH /api/v1/users/me`, `GET /api/v1/onboarding/status` | backend change required | backend + frontend | both required |
| `/passport-created` | onboarding completion landing | `GET /api/v1/onboarding/status` | partial | frontend + backend | both required |
| `/resume` | deferred resume onboarding | none in phase 1 | missing | frontend | deferred |
| `/resume-processing` | deferred resume onboarding | none in phase 1 | missing | frontend | deferred |
| `/review-import/$importId` | deferred resume onboarding | none in phase 1 | missing | frontend | deferred |

## Frontend Files Expected To Change In Phase 1

- `src/lib/api/client.ts`
- `src/lib/api/endpoints.ts`
- `src/lib/api/schemas.ts`
- `src/lib/api/types.ts`
- `src/lib/api/session.ts`
- `src/lib/api/auth.ts`
- `src/lib/api/onboarding.ts`
- `src/routes/signup.tsx`
- `src/routes/verify-identity.tsx`
- `src/routes/login.tsx`
- `src/routes/reset-password.tsx`
- `src/routes/more.tsx`
- `src/routes/start-method.tsx`
- `src/routes/quick-profile.tsx`
- `src/routes/passport-created.tsx`
- `src/hooks/use-onboarding-guard.ts`
- `src/hooks/use-onboarding-status.ts`
- `src/lib/steps.config.ts`

Likely new frontend files:

- confirm-reset route
- DTO adapter helpers
- feature flag for deferred resume flow

## Backend Files Expected To Change In Phase 1

- `app/api/v1/routes/auth.py`
- `app/auth/service.py`
- `app/schemas/auth.py`
- `app/services/passport_engine_service.py`
- `app/schemas/passport_engine.py`
- `app/api/v1/routes/passport_engine.py`
- `app/models/user.py`
- `app/models/pending_signup.py`
- signup-related repositories and OTP stores
- phone OTP provider abstraction files
- settings and environment validation files
- Alembic migration for signup and phone verification fields
- tests covering signup, login, refresh, logout, onboarding, and quick profile

## Readiness Summary

Ready now:

- login endpoint
- refresh endpoint
- logout endpoint
- forgot password request endpoint
- reset password confirm endpoint

Needs backend extension:

- staged dual-channel signup
- phone OTP provider abstraction
- backend-owned onboarding `current_step`
- quick profile persistence fields if missing
- phone verification persistence on the user profile

Needs frontend integration work:

- host-only base URL handling
- `/api/v1` endpoint constants
- snake_case wire parsing
- nested backend error parsing
- 204 response handling
- refresh token lifecycle
- signup-session lifecycle
- backend-driven onboarding navigation
- confirm-reset route

## Phase 1 Implementation Order

1. Commit the contract document.
2. Extend backend signup schema and service logic for staged dual OTP.
3. Extend backend onboarding status and quick profile contract.
4. Add backend tests and complete live verification.
5. Update frontend API client and session lifecycle.
6. Integrate frontend auth screens.
7. Integrate frontend onboarding screens.
8. Run end-to-end verification and stop for review.
