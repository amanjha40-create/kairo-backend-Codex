# Account & Settings

Command 11 adds authenticated account settings aggregation without changing onboarding, authentication, verification, Trust Score, or Passport workflows.

## APIs

- `GET /api/v1/account/settings` returns the authenticated profile, Trust Score consent summary, notification preferences, and version information.
- `PATCH /api/v1/account/settings` updates notification delivery preferences and supports Trust Score consent withdrawal where policy permits.
- `GET /api/v1/account/sessions` lists active refresh-token sessions owned by the authenticated user.
- `DELETE /api/v1/account/sessions/{id}` revokes one owned session.
- `DELETE /api/v1/account/sessions` revokes all active sessions for the user.

All routes require authentication and enforce ownership in the service layer. Refresh-token rows store hashes only; device and location metadata are not currently collected and are therefore not fabricated in responses.

## Preferences and consent

Notification preferences control delivery decisions, not creation of security or audit events. Trust Score consent status is read from the canonical user fields. Withdrawal clears the active consent fields but does not delete historical verification or audit records.

## Known limitations

Version 1 exposes English/version metadata only. Active-session device, platform, and approximate-location details require additional trusted session metadata and are intentionally omitted until that data is collected securely.
