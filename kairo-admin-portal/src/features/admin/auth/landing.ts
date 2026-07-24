import type { AdminAuthAdapter } from "./types";

export async function resolveAdminLandingPath(
  adapter: AdminAuthAdapter,
): Promise<"/admin" | "/admin/login"> {
  const result = await adapter.restoreSession();
  return result.status === "authenticated" ? "/admin" : "/admin/login";
}
