import type { AdminRoleKey, WorkflowPermission } from "../workflow/types";

export interface DemoAdminAccountSeed {
  id: string;
  email: string;
  password: string;
  name: string;
  initials: string;
  roleKey: AdminRoleKey;
}

export interface AdminAccount {
  id: string;
  email: string;
  name: string;
  initials: string;
  roleKey: AdminRoleKey;
  role: string;
  permissions: WorkflowPermission[];
}

export interface StoredSession {
  accountId: string;
  signedInAt: string;
  remember: boolean;
}

export type SessionSource = "local" | "session";

export type AdminAuthStatus = "checking" | "authenticated" | "unauthenticated" | "expired";

export interface AdminAuthRestoreResult {
  status: Exclude<AdminAuthStatus, "checking">;
  account?: AdminAccount;
  signedInAt?: string;
}

export type AdminAuthActionResult =
  | {
      ok: true;
      account?: AdminAccount;
      signedInAt?: string;
      message?: string;
    }
  | {
      ok: false;
      error: string;
    };

export interface AdminAuthAdapter {
  mode: "demo" | "production";
  isConfigured: boolean;
  notice: string | null;
  restoreSession: () => Promise<AdminAuthRestoreResult>;
  login: (email: string, password: string, remember: boolean) => Promise<AdminAuthActionResult>;
  logout: () => Promise<void>;
  forgotPassword: (email: string) => Promise<AdminAuthActionResult>;
}
