import {
  clearStoredSession,
  createBrowserSessionStorage,
  isStoredSessionExpired,
  readStoredSession,
  writeStoredSession,
  type SessionStorageBag,
} from "./session-storage";
import { DEMO_ADMIN_ACCOUNTS, toAdminAccount } from "./mock-accounts";
import type { AdminAuthAdapter, DemoAdminAccountSeed } from "./types";

interface DemoAuthAdapterOptions {
  accounts?: DemoAdminAccountSeed[];
  storage?: SessionStorageBag | null;
  now?: () => Date;
  delayMs?: number;
}

export function createDemoAuthAdapter(options: DemoAuthAdapterOptions = {}): AdminAuthAdapter {
  const accounts = options.accounts ?? DEMO_ADMIN_ACCOUNTS;
  const storage = options.storage ?? createBrowserSessionStorage();
  const now = options.now ?? (() => new Date());
  const delayMs = options.delayMs ?? 350;

  return {
    mode: "demo",
    isConfigured: true,
    notice:
      "Demo mode is enabled. Mock credentials and deterministic mock data are available for local validation only.",
    async restoreSession() {
      const stored = readStoredSession(storage);
      if (!stored) return { status: "unauthenticated" };

      if (isStoredSessionExpired(stored.session, now().getTime())) {
        clearStoredSession(storage);
        return { status: "expired" };
      }

      const account = accounts.find((candidate) => candidate.id === stored.session.accountId);
      if (!account) {
        clearStoredSession(storage);
        return { status: "unauthenticated" };
      }

      return {
        status: "authenticated",
        account: toAdminAccount(account),
        signedInAt: stored.session.signedInAt,
      };
    },
    async login(email, password, remember) {
      if (delayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }

      const normalizedEmail = email.trim().toLowerCase();
      const account = accounts.find(
        (candidate) => candidate.email.toLowerCase() === normalizedEmail,
      );

      if (!account || account.password !== password) {
        return {
          ok: false,
          error: "Invalid email or password. Check your credentials and try again.",
        };
      }

      const signedInAt = now().toISOString();
      writeStoredSession(storage, {
        accountId: account.id,
        signedInAt,
        remember,
      });

      return {
        ok: true,
        account: toAdminAccount(account),
        signedInAt,
      };
    },
    async logout() {
      clearStoredSession(storage);
    },
    async forgotPassword() {
      if (delayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, Math.min(delayMs, 400)));
      }

      return {
        ok: true,
        message:
          "If an authorised Admin account exists for this email, password reset instructions will be sent.",
      };
    },
  };
}
