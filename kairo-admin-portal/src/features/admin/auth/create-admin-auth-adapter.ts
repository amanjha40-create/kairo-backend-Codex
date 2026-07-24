import { appEnv, type AppEnvConfig } from "@/config/env";
import { createDemoAuthAdapter } from "./demo-auth-adapter";
import { createProductionAuthAdapter } from "./production-auth-adapter";
import type { AdminAuthAdapter } from "./types";

export function createAdminAuthAdapter(config: AppEnvConfig = appEnv): AdminAuthAdapter {
  return config.adminDemoMode ? createDemoAuthAdapter() : createProductionAuthAdapter(config);
}
