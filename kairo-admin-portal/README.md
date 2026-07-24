# Kairo Operations Hub / Admin Portal

Internal admin frontend for Kairo operations, verifications, communications, risk review, registry management, and system operations.

## Local Setup

1. Install dependencies with `bun install --frozen-lockfile`.
2. Copy `.env.example` to `.env` and adjust values for your environment.
3. Run `bun run dev` for local development.

If Bun is not available in your environment, the equivalent npm-based commands are:

- `npm install`
- `npm run dev`
- `npm run build`
- `npm run lint`
- `npx tsc --noEmit`
- `npx prettier --check .`
- `npm test`

## Environment Variables

- `VITE_APP_ENV`
  Expected values: `development`, `test`, `staging`, `production`.
  Defaults to `development` in dev builds and `production` otherwise.

- `VITE_API_BASE_URL`
  Base URL for future backend API integration.
  Required whenever `VITE_ADMIN_DEMO_MODE=false`.

- `VITE_ADMIN_DEMO_MODE`
  Enables the deterministic frontend demo path.
  Defaults to `true` outside production and `false` in production.

## Demo Mode

Demo mode keeps the current prototype usable for local reviews without pretending to be secure:

- Mock accounts are available only through the demo auth adapter.
- Deterministic mock datasets stay behind `src/features/admin/data/*`.
- A visible demo-mode notice appears on public auth pages and inside the admin shell.
- Frontend-only permissions are presentation aids, not backend authorization.

## Production Mode

Production mode is intentionally conservative until an approved API contract exists:

- Mock login is disabled.
- Demo credentials are not shown.
- `VITE_API_BASE_URL` must be configured to avoid silent fallback.
- The UI shows a safe “Admin authentication is not configured” state instead of simulating security.

## Authentication Architecture

Public auth consumers still use:

- `AdminAuthProvider`
- `useAdminAuth()`

The implementation is now split into:

- `src/features/admin/auth/types.ts`
- `src/features/admin/auth/mock-accounts.ts`
- `src/features/admin/auth/session-storage.ts`
- `src/features/admin/auth/demo-auth-adapter.ts`
- `src/features/admin/auth/production-auth-adapter.ts`
- `src/features/admin/auth/create-admin-auth-adapter.ts`
- `src/features/admin/auth/redirects.ts`

Current status:

- Demo mode supports login, logout, session restore, and simulated forgot-password.
- Production mode refuses mock fallback.
- No backend endpoints are assumed or implemented.

## Data Adapter Architecture

All domain reads should go through `src/features/admin/data/*`.

Current adapters cover:

- Overview
- Verifications
- Verification detail
- Users
- User detail
- Registry
- Registry detail
- Communications
- Communication detail
- Risk
- Investigation detail
- System

The mock datasets remain implementation details behind those adapters.

## Backend Integration Points

Prepared but intentionally not wired to guessed endpoints:

- `src/lib/api/client.ts`
- `src/lib/api/errors.ts`
- `src/lib/query-client.ts`
- `docs/admin-api-integration-spec.md`

These provide:

- Base URL handling
- Abort and timeout support
- Safe error mapping
- Future secure-cookie-friendly credentials handling
- Query retry and stale-time defaults

## Hosting

This application is expected to live at `admin.kairoid.com`.

Current root behavior:

- `/` redirects authenticated demo sessions to `/admin`
- `/` redirects everyone else to `/admin/login`
- `/admin` remains the application prefix in this phase

## Security Notes

Current limitations are explicit by design:

- Frontend route guards do not protect backend resources.
- Browser storage is only a convenience for the demo adapter.
- Secure cookies, real session expiry, CSRF protection, CSP, clickjacking headers, and server-side authorization must be enforced by the backend and hosting layer.
- Sensitive API payloads are not logged by the new API client foundation.

Recommended hosting and backend follow-up:

- Use secure, `HttpOnly`, same-site cookies for real admin sessions.
- Enforce authorization on every backend admin endpoint.
- Set CSP, `X-Frame-Options` or `frame-ancestors`, and production source-map policy at the hosting layer.

## Lovable / GitHub Synchronization

This repository remains connected to Lovable.

- Do not force-push.
- Do not rebase, amend, or rewrite published history.
- Keep the connected branch working.
- Use normal incremental commits only.

## Still Blocked On Backend Contract

- Real authentication transport
- Forgot-password request contract
- Session refresh and expiry endpoints
- Domain query endpoints
- Mutation endpoints for workflows and operations
- Server-driven permission claims

## Validation Commands

- `bun install --frozen-lockfile`
- `bun run build`
- `bun run lint`
- `bunx tsc --noEmit`
- `bunx prettier --check .`
- `bun run test`

## Production Readiness Checklist

- [ ] Approved backend auth contract is available
- [ ] `VITE_API_BASE_URL` points at the admin backend
- [ ] Demo mode is disabled in production
- [ ] Secure cookie session transport is implemented server-side
- [ ] Server-side authorization is enforced for every admin action
- [ ] Query hooks are swapped from mock adapters to backend adapters
- [ ] CSP and clickjacking protections are configured
- [ ] Production source-map policy is confirmed
- [ ] Build, lint, typecheck, prettier, and tests pass in CI
