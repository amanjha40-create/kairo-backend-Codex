import type { AppEnvConfig } from "@/config/env";
import type { AdminAuthAdapter } from "./types";

export function createProductionAuthAdapter(config: AppEnvConfig): AdminAuthAdapter {
  const notice = !config.authTransportConfigured
    ? "Admin authentication is not configured. Set VITE_API_BASE_URL and wire the approved backend contract before enabling production sign-in."
    : "Admin authentication transport has not been wired because no approved backend contract is available yet.";

  return {
    mode: "production",
    isConfigured: false,
    notice,
    async restoreSession() {
      return { status: "unauthenticated" };
    },
    async login() {
      return {
        ok: false,
        error: "Admin authentication is not configured.",
      };
    },
    async logout() {
      return;
    },
    async forgotPassword() {
      return {
        ok: false,
        error: "Admin password reset is not configured.",
      };
    },
  };
}
