import { z } from "zod";

export const APP_ENVIRONMENTS = ["development", "test", "staging", "production"] as const;

export type AppEnvironment = (typeof APP_ENVIRONMENTS)[number];

const rawAppEnvSchema = z.object({
  VITE_APP_ENV: z.string().optional(),
  VITE_API_BASE_URL: z.string().optional(),
  VITE_ADMIN_DEMO_MODE: z.string().optional(),
});
const urlSchema = z.string().url();

export interface AppEnvConfig {
  appEnv: AppEnvironment;
  apiBaseUrl: string | null;
  adminDemoMode: boolean;
  authTransportConfigured: boolean;
  issues: string[];
}

function parseBooleanFlag(value: string | undefined, fallback: boolean): boolean {
  if (value == null || value.trim() === "") return fallback;

  const normalized = value.trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) return true;
  if (["0", "false", "no", "off"].includes(normalized)) return false;

  return fallback;
}

export function resolveAppEnvConfig(
  env: Record<string, unknown>,
  options: { dev: boolean },
): AppEnvConfig {
  const parsed = rawAppEnvSchema.parse(env);
  const fallbackAppEnv: AppEnvironment = options.dev ? "development" : "production";
  const appEnv = APP_ENVIRONMENTS.includes(parsed.VITE_APP_ENV as AppEnvironment)
    ? (parsed.VITE_APP_ENV as AppEnvironment)
    : fallbackAppEnv;

  const rawApiBaseUrl = parsed.VITE_API_BASE_URL?.trim() ? parsed.VITE_API_BASE_URL.trim() : null;
  const apiBaseUrl =
    rawApiBaseUrl && urlSchema.safeParse(rawApiBaseUrl).success ? rawApiBaseUrl : null;
  const defaultDemoMode = appEnv === "production" ? false : true;
  const adminDemoMode = parseBooleanFlag(parsed.VITE_ADMIN_DEMO_MODE, defaultDemoMode);
  const issues: string[] = [];

  if (rawApiBaseUrl && !apiBaseUrl) {
    issues.push("VITE_API_BASE_URL must be a valid absolute URL.");
  }

  if (!adminDemoMode && !apiBaseUrl) {
    issues.push(
      "VITE_API_BASE_URL is required when VITE_ADMIN_DEMO_MODE is false so production auth cannot silently fall back to mock mode.",
    );
  }

  return {
    appEnv,
    apiBaseUrl,
    adminDemoMode,
    authTransportConfigured: Boolean(apiBaseUrl),
    issues,
  };
}

export const appEnv = resolveAppEnvConfig(import.meta.env, { dev: import.meta.env.DEV });

export function getAdminModeLabel(config: AppEnvConfig = appEnv): string {
  return config.adminDemoMode ? "Demo mode" : "Production mode";
}

export function getAdminEnvironmentNotice(config: AppEnvConfig = appEnv): string | null {
  if (config.adminDemoMode) {
    return "Demo mode uses mock accounts and deterministic mock operational data. Frontend route guards do not secure backend resources.";
  }

  if (!config.authTransportConfigured) {
    return "Admin authentication is not configured. Set VITE_API_BASE_URL and wire the approved backend auth contract before enabling production sign-in.";
  }

  return "Production mode is enabled, but the backend authentication contract has not been wired into the frontend adapter yet.";
}

export function requireApiBaseUrl(config: AppEnvConfig = appEnv): string {
  if (!config.apiBaseUrl) {
    throw new Error("VITE_API_BASE_URL is required when the admin portal runs without demo mode.");
  }

  return config.apiBaseUrl;
}
