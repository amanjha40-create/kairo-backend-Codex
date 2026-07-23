# Passport Sharing

## Status

Passport sharing is an authenticated, backend-owned feature for candidate Trust Passports. The candidate app creates and manages links through the existing Passport Share API; it does not persist share state locally or manufacture public Passport data.

## Lifecycle

1. `POST /api/v1/passport-shares` creates a share and returns the public URL once.
2. `GET /api/v1/passport-shares` lists the authenticated owner's shares and their server-derived state.
3. `PATCH /api/v1/passport-shares/{share_id}` updates supported metadata such as the label or expiry.
4. `POST /api/v1/passport-shares/{share_id}/revoke` permanently revokes the link.
5. `GET /api/v1/passport-shares/{share_id}/analytics` returns owner-only view metrics.
6. `GET /api/v1/public/passport/{token}` resolves an active, unexpired link for the recipient view.

Active, expired, and revoked states are evaluated by the backend. Public access is denied when a token is invalid, expired, or revoked. Ownership is enforced on all authenticated management and analytics endpoints.

## Token and privacy handling

The raw token is returned only in the create response so the candidate can copy or share it. The backend stores only a hash, and history responses intentionally do not return a raw token that could be reconstructed later. Share URLs must not be logged or persisted in browser storage. Public Passport responses use an explicit allowlist and must not expose private contact details or other owner-only metadata.

View analytics are recorded by the backend with privacy-preserving viewer metadata. The candidate app renders the returned totals and timestamps; it does not calculate or fake analytics.

## Candidate app behavior

The Share Passport screen uses the existing API client and query layer. It provides create, copy, native Android sharing, a client-generated QR image from the backend-issued URL, recipient preview, history, revoke, and analytics. Loading, empty, API error, retry, and revoked/expired states are shown explicitly. Logout/session cleanup continues to be handled by the existing auth layer.

The QR image is generated locally for presentation only; no token is sent to a third-party QR service. Skills, profile completion, Trust Score, and Passport content remain backend-owned and are not changed by sharing actions.

## URL configuration

The backend builds the share URL from `APP_PUBLIC_BASE_URL`. That value must be an HTTPS, web-capable canonical host for the recipient experience. Staging currently uses the configured staging host; if that host serves API-only responses, deployment configuration must point `APP_PUBLIC_BASE_URL` at the approved staging web host before external sharing. No frontend hostname is invented in code.

## QA checklist

- Create a share with each supported expiry option.
- Copy the newly returned URL; historical shares deliberately cannot regenerate a raw token.
- Open recipient preview and verify only permitted Passport fields are visible.
- Scan the QR code and verify the same public route.
- Use Android native sharing and cancel safely.
- Confirm analytics are owner-only and refresh after a public view.
- Revoke a share and confirm public access is denied.
- Confirm expiry is enforced server-side.
- Test offline and retry states without claiming a save succeeded.
- Confirm no share URL, token, PII, or API credential appears in logs.

Production remains unchanged by frontend sharing work. Any backend or deployment change must be staged, reviewed, and validated separately.
