import { describe, expect, it } from "vitest";
import { resolveAppEnvConfig } from "./env";

describe("resolveAppEnvConfig", () => {
  it("defaults demo mode to true in development", () => {
    const config = resolveAppEnvConfig({}, { dev: true });

    expect(config.appEnv).toBe("development");
    expect(config.adminDemoMode).toBe(true);
    expect(config.issues).toEqual([]);
  });

  it("defaults demo mode to false in production", () => {
    const config = resolveAppEnvConfig({}, { dev: false });

    expect(config.appEnv).toBe("production");
    expect(config.adminDemoMode).toBe(false);
    expect(config.issues).toHaveLength(1);
  });
});
