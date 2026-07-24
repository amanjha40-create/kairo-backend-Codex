# Production Readiness Checklist

Use this checklist before enabling non-demo access to the admin portal.

## Environment

- `VITE_APP_ENV=production`
- `VITE_ADMIN_DEMO_MODE=false`
- `VITE_API_BASE_URL` points to the approved admin backend

## Authentication

- Backend login contract is approved and implemented
- Backend logout contract is approved and implemented
- Session restore / refresh contract is approved and implemented
- Forgot-password contract is approved and implemented
- Secure `HttpOnly` cookies are in place

## Authorization

- Backend permission claims are returned by the session endpoint
- Every admin API route enforces authorization server-side
- Frontend permission checks are treated as UX, not security

## Hosting

- App is deployed at `admin.kairoid.com`
- CSP is configured
- Clickjacking protections are configured
- Source-map exposure is reviewed

## Quality Gates

- `bun run build`
- `bun run lint`
- `bunx tsc --noEmit`
- `bunx prettier --check .`
- `bun run test`
