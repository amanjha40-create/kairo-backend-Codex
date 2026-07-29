# QA Reset Tool

`scripts/reset_test_data.py` is a CLI-only destructive utility for local Docker, test, and staging QA. It is not an HTTP endpoint and must never be used against production.

## Modes

```bash
python scripts/reset_test_data.py --email test@example.com
python scripts/reset_test_data.py --emails qa-users.txt
python scripts/reset_test_data.py --full-reset --confirm-full-reset
python scripts/reset_test_data.py --full-reset --dry-run
```

Single-user and email-list modes require an exact email match. Add `--yes` for non-interactive single-user/list execution. Full reset requires `APP_ENV=staging` and `--confirm-full-reset`; it targets non-system users (`role=user`) only.

`--dry-run` performs the same ownership and dependency discovery, reports table and storage-object counts, and makes no database, Redis, or S3 changes. A full-reset dry run does not require the destructive confirmation flag.

## Safety rules

- `APP_ENV=production` is always refused.
- Full reset is allowed only in staging and requires explicit confirmation.
- Shared organizations with another member are never deleted; the reset refuses before committing.
- Shared records with a non-null user reference that cannot be safely detached are refused before committing.
- Organization records owned exclusively by the selected QA user are deleted with their dependent organization-owned records.
- Nullable actor/audit references are detached so organization-owned history can survive.
- Database changes run in one transaction and roll back on failure.
- No public API, background job, migration, or production configuration is involved.
- S3 deletion is limited to object metadata owned by the selected user; Redis OTP state is session-scoped and expires with the deleted pending signup.
- A dry run never deletes, detaches, anonymizes, or writes anything; it prints `DRY RUN: no destructive action occurred` after discovery.

## Recovery procedure

The tool has no undo operation. Restore the local/staging database from the approved backup or snapshot, then restore any required S3 objects from the configured bucket backup/versioning policy. Re-run migrations only through the normal controlled process.

Run the tool again with the same mode to verify that the user, pending signup, profile-owned rows, notifications, passport/share data, resume data, and trust-score snapshots are absent.
