import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { createAdminAuthAdapter } from "./create-admin-auth-adapter";
import { listMockAdminEmails } from "./mock-accounts";
import type { AdminAccount, AdminAuthAdapter, AdminAuthStatus } from "./types";

export interface AdminAuthContextValue {
  status: AdminAuthStatus;
  account: AdminAccount | null;
  signedInAt: string | null;
  login: (
    email: string,
    password: string,
    remember: boolean,
  ) => Promise<{ ok: true } | { ok: false; error: string }>;
  logout: (reason?: "user" | "expired") => void;
  forgotPassword: (
    email: string,
  ) => Promise<{ ok: true; message?: string } | { ok: false; error: string }>;
  mode: AdminAuthAdapter["mode"];
  isConfigured: boolean;
  notice: string | null;
}

const AdminAuthContext = createContext<AdminAuthContextValue | null>(null);

export function AdminAuthProvider({ children }: { children: ReactNode }) {
  const adapter = useMemo(() => createAdminAuthAdapter(), []);
  const [status, setStatus] = useState<AdminAuthStatus>("checking");
  const [account, setAccount] = useState<AdminAccount | null>(null);
  const [signedInAt, setSignedInAt] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    void adapter.restoreSession().then((result) => {
      if (!active) return;

      if (result.status === "authenticated" && result.account && result.signedInAt) {
        setAccount(result.account);
        setSignedInAt(result.signedInAt);
        setStatus("authenticated");
        return;
      }

      setAccount(null);
      setSignedInAt(null);
      setStatus(result.status);
    });

    return () => {
      active = false;
    };
  }, [adapter]);

  const login = useCallback<AdminAuthContextValue["login"]>(
    async (email, password, remember) => {
      const result = await adapter.login(email, password, remember);
      if (!result.ok) return result;

      setAccount(result.account ?? null);
      setSignedInAt(result.signedInAt ?? null);
      setStatus("authenticated");
      return { ok: true };
    },
    [adapter],
  );

  const logout = useCallback<AdminAuthContextValue["logout"]>(
    (reason = "user") => {
      void adapter.logout();
      setAccount(null);
      setSignedInAt(null);
      setStatus(reason === "expired" ? "expired" : "unauthenticated");
    },
    [adapter],
  );

  const forgotPassword = useCallback<AdminAuthContextValue["forgotPassword"]>(
    async (email) => adapter.forgotPassword(email),
    [adapter],
  );

  const value = useMemo<AdminAuthContextValue>(
    () => ({
      status,
      account,
      signedInAt,
      login,
      logout,
      forgotPassword,
      mode: adapter.mode,
      isConfigured: adapter.isConfigured,
      notice: adapter.notice,
    }),
    [status, account, signedInAt, login, logout, forgotPassword, adapter],
  );

  return <AdminAuthContext.Provider value={value}>{children}</AdminAuthContext.Provider>;
}

export function useAdminAuth(): AdminAuthContextValue {
  const ctx = useContext(AdminAuthContext);
  if (!ctx) throw new Error("useAdminAuth must be used inside <AdminAuthProvider>.");
  return ctx;
}

export { listMockAdminEmails };
