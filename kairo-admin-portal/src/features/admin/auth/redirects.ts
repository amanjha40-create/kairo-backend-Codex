export const DEFAULT_ADMIN_REDIRECT = "/admin";

export function isSafeAdminRedirect(value: string | null | undefined): value is string {
  if (!value) return false;
  if (!value.startsWith("/")) return false;
  if (value.startsWith("//")) return false;
  if (!value.startsWith("/admin")) return false;
  if (/[\r\n]/.test(value)) return false;
  return true;
}

export function normalizeAdminRedirect(
  value: string | null | undefined,
  fallback = DEFAULT_ADMIN_REDIRECT,
): string {
  return isSafeAdminRedirect(value) ? value : fallback;
}
