import { describe, expect, it } from "vitest";
import { resolveAdminLandingPath } from "./landing";
import type { AdminAuthAdapter } from "./types";

function buildAdapter(status: "authenticated" | "unauthenticated"): AdminAuthAdapter {
  return {
    mode: "demo",
    isConfigured: true,
    notice: null,
    restoreSession: async () =>
      status === "authenticated"
        ? {
            status,
            account: {
              id: "u-1",
              email: "demo@kairo.internal",
              name: "Demo User",
              initials: "DU",
              roleKey: "admin",
              role: "Admin",
              permissions: [],
            },
            signedInAt: new Date("2026-07-24T10:00:00.000Z").toISOString(),
          }
        : { status },
    login: async () => ({ ok: false, error: "unused" }),
    logout: async () => undefined,
    forgotPassword: async () => ({ ok: false, error: "unused" }),
  };
}

describe("resolveAdminLandingPath", () => {
  it("routes authenticated sessions to /admin", async () => {
    await expect(resolveAdminLandingPath(buildAdapter("authenticated"))).resolves.toBe("/admin");
  });

  it("routes unauthenticated sessions to /admin/login", async () => {
    await expect(resolveAdminLandingPath(buildAdapter("unauthenticated"))).resolves.toBe(
      "/admin/login",
    );
  });
});
