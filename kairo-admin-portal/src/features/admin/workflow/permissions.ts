/**
 * Role → permission mapping for the Kairo Admin verification workflow.
 *
 * Kept intentionally simple: each role expands into a fixed permission set.
 * Real production authz will live server-side; this mirrors the shape so
 * the UI is ready to check without further refactor.
 */
import type { AdminRoleKey, WorkflowPermission } from "./types";

export const ROLE_LABEL: Record<AdminRoleKey, string> = {
  admin: "Admin",
  operations_lead: "Operations Lead",
  trust_safety: "Trust & Safety",
  reviewer: "Reviewer",
  read_only: "Read Only",
};

const ALL_DECISION_PERMISSIONS: WorkflowPermission[] = [
  "verification.request_correction",
  "verification.approve_outreach",
  "verification.verify",
  "verification.reject",
  "verification.mark_unable",
  "verification.assign",
  "verification.change_priority",
  "verification.acknowledge_flag",
  "verification.record_clarification",
];

const ALL_USER_PERMISSIONS: WorkflowPermission[] = [
  "users.view",
  "users.notes.create",
  "users.account.disable",
  "users.account.enable",
  "users.sessions.revoke",
  "users.verification.resend",
  "users.password_reset.prepare",
  "users.risk.flag",
  "users.data_export.prepare",
  "users.deletion.prepare",
];

const ALL_COMMS_PERMISSIONS: WorkflowPermission[] = [
  "communications.view",
  "communications.view_failures",
  "communications.notes.create",
  "communications.followup.schedule",
  "communications.followup.cancel",
  "communications.manual_contact.log",
  "communications.failure.review",
];

const ALL_RISK_PERMISSIONS: WorkflowPermission[] = [
  "risk.view",
  "risk.note",
  "risk.review",
  "risk.escalate",
  "risk.resolve",
  "risk.prepare_actions",
];

const ALL_SYSTEM_PERMISSIONS: WorkflowPermission[] = [
  "system.view",
  "system.jobs.view",
  "system.jobs.prepare_actions",
  "system.flags.view",
  "system.flags.prepare_changes",
  "system.messaging.view",
  "system.audit.view",
  "system.alerts.manage",
  "system.configuration.view",
];

// Read-only slice: view surfaces but never prepare changes.
const READ_ONLY_SYSTEM_PERMISSIONS: WorkflowPermission[] = [
  "system.view",
  "system.messaging.view",
  "system.configuration.view",
];

// Reviewer slice: view health, jobs, messaging and audit — no preparation.
const REVIEWER_SYSTEM_PERMISSIONS: WorkflowPermission[] = [
  "system.view",
  "system.jobs.view",
  "system.messaging.view",
  "system.audit.view",
  "system.flags.view",
  "system.configuration.view",
];

const ROLE_PERMISSIONS: Record<AdminRoleKey, WorkflowPermission[]> = {
  admin: [
    ...ALL_DECISION_PERMISSIONS,
    ...ALL_USER_PERMISSIONS,
    ...ALL_COMMS_PERMISSIONS,
    ...ALL_RISK_PERMISSIONS,
    ...ALL_SYSTEM_PERMISSIONS,
  ],
  operations_lead: [
    ...ALL_DECISION_PERMISSIONS,
    ...ALL_USER_PERMISSIONS,
    ...ALL_COMMS_PERMISSIONS,
    ...ALL_RISK_PERMISSIONS,
    ...ALL_SYSTEM_PERMISSIONS,
  ],
  trust_safety: [
    "verification.request_correction",
    "verification.reject",
    "verification.mark_unable",
    "verification.acknowledge_flag",
    "verification.record_clarification",
    "verification.assign",
    "verification.change_priority",
    "users.view",
    "users.notes.create",
    "users.sessions.revoke",
    "users.risk.flag",
    "communications.view",
    "communications.view_failures",
    "communications.notes.create",
    "communications.failure.review",
    ...ALL_RISK_PERMISSIONS,
    ...REVIEWER_SYSTEM_PERMISSIONS,
    "system.alerts.manage",
  ],
  reviewer: [
    "verification.request_correction",
    "verification.assign",
    "verification.change_priority",
    "verification.acknowledge_flag",
    "verification.record_clarification",
    "users.view",
    "users.notes.create",
    "communications.view",
    "communications.notes.create",
    "risk.view",
    "risk.note",
    ...REVIEWER_SYSTEM_PERMISSIONS,
  ],
  read_only: ["users.view", "communications.view", "risk.view", ...READ_ONLY_SYSTEM_PERMISSIONS],
};

export function permissionsForRole(role: AdminRoleKey): WorkflowPermission[] {
  return ROLE_PERMISSIONS[role];
}

export function hasPermission(
  permissions: WorkflowPermission[],
  needed: WorkflowPermission,
): boolean {
  return permissions.includes(needed);
}
