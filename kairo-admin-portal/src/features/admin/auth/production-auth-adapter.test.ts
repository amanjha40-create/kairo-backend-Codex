import { describe, expect, it } from "vitest";
import { resolveAppEnvConfig } from "@/config/env";
import { createAdminAuthAdapter } from "./create-admin-auth-adapter";

describe("production auth adapter", () => {
  it("refuses mock fallback when demo mode is disabled", async () => {
    const config = resolveAppEnvConfig(
      {
        VITE_APP_ENV: "production",
        VITE_ADMIN_DEMO_MODE: "false",
      },
      { dev: false },
    );

    const adapter = createAdminAuthAdapter(config);

    expect(adapter.mode).toBe("production");
    expect(adapter.isConfigured).toBe(false);
    await expect(adapter.login("demo@kairo.internal", "password", true)).resolves.toEqual({
      ok: false,
      error: "Admin authentication is not configured.",
    });
  });
});
