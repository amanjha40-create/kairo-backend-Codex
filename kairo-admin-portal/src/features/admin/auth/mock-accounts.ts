import { ROLE_LABEL, permissionsForRole } from "../workflow/permissions";
import type { AdminAccount, DemoAdminAccountSeed } from "./types";

export const DEMO_ADMIN_ACCOUNTS: DemoAdminAccountSeed[] = [
  {
    id: "u-ops-lead-01",
    email: "aman.jha@kairo.internal",
    password: "kairo-ops-2026",
    name: "Aman Jha",
    initials: "AJ",
    roleKey: "operations_lead",
  },
  {
    id: "u-admin-01",
    email: "priya.raman@kairo.internal",
    password: "kairo-admin-2026",
    name: "Priya Raman",
    initials: "PR",
    roleKey: "admin",
  },
  {
    id: "u-ts-01",
    email: "noah.mensah@kairo.internal",
    password: "kairo-ts-2026",
    name: "Noah Mensah",
    initials: "NM",
    roleKey: "trust_safety",
  },
  {
    id: "u-rev-01",
    email: "sara.linden@kairo.internal",
    password: "kairo-review-2026",
    name: "Sara Linden",
    initials: "SL",
    roleKey: "reviewer",
  },
  {
    id: "u-ro-01",
    email: "elena.ward@kairo.internal",
    password: "kairo-view-2026",
    name: "Elena Ward",
    initials: "EW",
    roleKey: "read_only",
  },
];

export function toAdminAccount(seed: DemoAdminAccountSeed): AdminAccount {
  return {
    id: seed.id,
    email: seed.email,
    name: seed.name,
    initials: seed.initials,
    roleKey: seed.roleKey,
    role: ROLE_LABEL[seed.roleKey],
    permissions: permissionsForRole(seed.roleKey),
  };
}

export function listMockAdminEmails(): {
  email: string;
  roleKey: DemoAdminAccountSeed["roleKey"];
  name: string;
}[] {
  return DEMO_ADMIN_ACCOUNTS.map(({ email, roleKey, name }) => ({ email, roleKey, name }));
}

export function listMockAdminCredentials(): DemoAdminAccountSeed[] {
  return DEMO_ADMIN_ACCOUNTS;
}
