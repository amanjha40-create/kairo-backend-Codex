# Admin Data Adapter Layer

Thin repository-style facade over `src/features/admin/mock-data/*`. Every
admin UI read should import from this directory, NOT from `mock-data`
directly. Today each function returns synchronously from the deterministic
mock dataset. Tomorrow each function is the single site to replace with a
`fetch` / TanStack Query hook against the FastAPI backend.

## Contract

- **Reads are pure and async-safe.** Every getter returns a plain value or
  `Promise` — call sites should already be prepared to `await` (they can
  wrap in `queryOptions({ queryKey, queryFn })`).
- **Writes do not exist here.** Session-only mutations still live in the
  `workflow/use-*-session.ts` reducers. When the backend arrives, those
  reducers become `useMutation` calls; the reducers already emit the same
  action shapes an API would accept.
- **No component imports mock-data directly** once migration is complete.
  Types are re-exported from adapters so component files never reach past
  the boundary.

## Migration recipe (per module)

1. Route/component imports `getOrganization(id)` from `@/features/admin/data/registry`
   instead of `getRegistryOrganization` from `mock-data/registry`.
2. When wiring the real backend, change the adapter body to
   `queryOptions({ queryKey: ["registry", "org", id], queryFn: () => api.get(...) })`
   and call sites switch from direct call to `useSuspenseQuery(orgQuery(id))`.
3. No component JSX changes.

The adapters below are intentionally shallow — they exist to move the
import boundary, not to add behaviour.
