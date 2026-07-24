/**
 * Session-only User Admin state.
 *
 * Manages internal notes, simulated administrative actions, risk flags and
 * a session-only timeline overlay. Never mutates imported mock data. All
 * changes are lost on reload — see the "Session-only" labeling in the UI.
 */
import { useCallback, useMemo, useState } from "react";
import type { UserAccountStatus, UserActivityEvent, UserAttentionKind } from "../data/users";

export type UserNoteCategory = "support" | "verification" | "risk" | "account" | "general";

export const USER_NOTE_CATEGORY_LABEL: Record<UserNoteCategory, string> = {
  support: "Support",
  verification: "Verification",
  risk: "Risk",
  account: "Account",
  general: "General",
};

export interface UserNote {
  id: string;
  at: string;
  author: string;
  role: string;
  category: UserNoteCategory;
  body: string;
}

export type UserAdminActionKind =
  | "password_reset_prepared"
  | "email_verification_resent"
  | "phone_verification_resent"
  | "account_disabled"
  | "account_reenabled"
  | "sessions_revoked"
  | "flagged_for_trust_safety"
  | "data_export_prepared"
  | "deletion_prepared";

export const USER_ACTION_LABEL: Record<UserAdminActionKind, string> = {
  password_reset_prepared: "Password reset prepared",
  email_verification_resent: "Email verification resent",
  phone_verification_resent: "Phone verification resent",
  account_disabled: "Account disabled",
  account_reenabled: "Account re-enabled",
  sessions_revoked: "Active sessions revoked",
  flagged_for_trust_safety: "Flagged for Trust & Safety",
  data_export_prepared: "Data export prepared",
  deletion_prepared: "Deletion request prepared",
};

export interface UserAdminAction {
  id: string;
  kind: UserAdminActionKind;
  at: string;
  actor: string;
  role: string;
  reason?: string;
  impactSummary?: string;
}

export interface UserSessionState {
  notes: UserNote[];
  actions: UserAdminAction[];
  accountStatusOverride?: UserAccountStatus;
  addedRiskFlags: UserAttentionKind[];
  extraTimeline: UserActivityEvent[];
}

interface Actor {
  name: string;
  role: string;
}

function uid(prefix: string) {
  return `${prefix}-${Math.random().toString(36).slice(2, 9)}`;
}

export function useUserAdminSession(_userId: string, actor: Actor) {
  const [state, setState] = useState<UserSessionState>({
    notes: [],
    actions: [],
    addedRiskFlags: [],
    extraTimeline: [],
  });

  const pushTimeline = useCallback(
    (summary: string, kind: UserActivityEvent["kind"] = "account_change") => {
      setState((s) => ({
        ...s,
        extraTimeline: [
          {
            id: uid("act"),
            at: new Date().toISOString(),
            kind,
            summary,
            sessionOnly: true,
            actor: actor.name,
          },
          ...s.extraTimeline,
        ],
      }));
    },
    [actor.name],
  );

  const addNote = useCallback(
    (body: string, category: UserNoteCategory) => {
      const trimmed = body.trim();
      if (!trimmed) return;
      setState((s) => ({
        ...s,
        notes: [
          {
            id: uid("note"),
            at: new Date().toISOString(),
            author: actor.name,
            role: actor.role,
            category,
            body: trimmed,
          },
          ...s.notes,
        ],
      }));
      pushTimeline(`Internal note added (${USER_NOTE_CATEGORY_LABEL[category]})`, "admin_note");
    },
    [actor.name, actor.role, pushTimeline],
  );

  const performAction = useCallback(
    (kind: UserAdminActionKind, opts: { reason?: string; impactSummary?: string } = {}) => {
      const action: UserAdminAction = {
        id: uid("axn"),
        kind,
        at: new Date().toISOString(),
        actor: actor.name,
        role: actor.role,
        reason: opts.reason,
        impactSummary: opts.impactSummary,
      };
      setState((s) => {
        let next: UserSessionState = { ...s, actions: [action, ...s.actions] };
        if (kind === "account_disabled") next.accountStatusOverride = "disabled";
        if (kind === "account_reenabled") next.accountStatusOverride = "active";
        if (kind === "deletion_prepared") next.accountStatusOverride = "deletion_requested";
        if (kind === "flagged_for_trust_safety" && !s.addedRiskFlags.includes("risk")) {
          next = { ...next, addedRiskFlags: [...s.addedRiskFlags, "risk"] };
        }
        return next;
      });
      pushTimeline(
        `${USER_ACTION_LABEL[kind]} (simulated)${opts.reason ? ` — ${opts.reason}` : ""}`,
        kind === "flagged_for_trust_safety" ? "risk_flag" : "account_change",
      );
    },
    [actor.name, actor.role, pushTimeline],
  );

  const hasSessionChanges = useMemo(
    () =>
      state.notes.length > 0 ||
      state.actions.length > 0 ||
      state.addedRiskFlags.length > 0 ||
      state.accountStatusOverride !== undefined,
    [state],
  );

  return { ...state, addNote, performAction, hasSessionChanges };
}
