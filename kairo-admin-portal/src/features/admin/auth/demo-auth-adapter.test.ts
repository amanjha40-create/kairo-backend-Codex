import { describe, expect, it } from "vitest";
import { createDemoAuthAdapter } from "./demo-auth-adapter";
import { SESSION_KEY, type SessionStorageBag } from "./session-storage";

function createMemoryStore() {
  const map = new Map<string, string>();
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => {
      map.set(key, value);
    },
    removeItem: (key: string) => {
      map.delete(key);
    },
  };
}

function createMemoryStorage(): SessionStorageBag {
  return {
    local: createMemoryStore(),
    session: createMemoryStore(),
  };
}

describe("createDemoAuthAdapter", () => {
  it("supports demo login success and restore", async () => {
    const storage = createMemoryStorage();
    const adapter = createDemoAuthAdapter({ storage, delayMs: 0 });

    const loginResult = await adapter.login("aman.jha@kairo.internal", "kairo-ops-2026", true);

    expect(loginResult.ok).toBe(true);

    const restored = await adapter.restoreSession();
    expect(restored.status).toBe("authenticated");
    expect(restored.account?.email).toBe("aman.jha@kairo.internal");
  });

  it("rejects invalid demo credentials", async () => {
    const adapter = createDemoAuthAdapter({
      storage: createMemoryStorage(),
      delayMs: 0,
    });

    await expect(adapter.login("aman.jha@kairo.internal", "bad-password", true)).resolves.toEqual({
      ok: false,
      error: "Invalid email or password. Check your credentials and try again.",
    });
  });

  it("clears state on logout", async () => {
    const storage = createMemoryStorage();
    const adapter = createDemoAuthAdapter({ storage, delayMs: 0 });

    await adapter.login("aman.jha@kairo.internal", "kairo-ops-2026", true);
    await adapter.logout();

    await expect(adapter.restoreSession()).resolves.toEqual({ status: "unauthenticated" });
  });

  it("marks old sessions as expired", async () => {
    const storage = createMemoryStorage();
    storage.local.setItem(
      SESSION_KEY,
      JSON.stringify({
        accountId: "u-ops-lead-01",
        signedInAt: new Date("2026-07-23T00:00:00.000Z").toISOString(),
        remember: true,
      }),
    );

    const adapter = createDemoAuthAdapter({
      storage,
      delayMs: 0,
      now: () => new Date("2026-07-24T18:30:00.000Z"),
    });

    await expect(adapter.restoreSession()).resolves.toEqual({ status: "expired" });
  });
});
