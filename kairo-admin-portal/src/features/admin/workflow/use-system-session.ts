/**
 * useSystemSession — session-only state for the System Operations Center.
 *
 * Manages prepared job actions, prepared feature-flag changes, alert
 * acknowledgements / notes / assignments, and manual incidents. NEVER
 * mutates imported mock data. Resets on unmount / reload.
 *
 * Uses a reducer so all mutations are auditable in one place.
 */
import { useCallback, useMemo, useReducer } from "react";
import {
  ALERT_KIND_LABEL,
  ALERT_STATUS_LABEL,
  FLAG_STATE_LABEL,
  JOB_STATUS_LABEL,
  mockAlerts,
  mockFeatureFlags,
  type AlertRecord,
  type AlertStatus,
  type BackgroundJob,
  type FeatureFlag,
  type FlagState,
} from "../data/system";

function uid(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

// ---------------------------------------------------------------------
// Session record types
// ---------------------------------------------------------------------

export type JobActionKind = "retry" | "cancel" | "escalate" | "reviewed";
export const JOB_ACTION_LABEL: Record<JobActionKind, string> = {
  retry: "Prepared retry",
  cancel: "Prepared cancellation",
  escalate: "Escalated",
  reviewed: "Marked reviewed",
};

export interface PreparedJobAction {
  id: string;
  jobId: string;
  kind: JobActionKind;
  note?: string;
  at: string;
  actor: string;
}

export interface PreparedFlagChange {
  id: string;
  flagId: string;
  nextState: FlagState;
  nextRolloutPct: number;
  note?: string;
  at: string;
  actor: string;
}

export type AlertActionKind =
  | "acknowledged"
  | "assigned"
  | "note_added"
  | "resolved_simulation"
  | "escalated"
  | "prepared_incident";

export const ALERT_ACTION_LABEL: Record<AlertActionKind, string> = {
  acknowledged: "Acknowledged",
  assigned: "Owner assigned",
  note_added: "Note added",
  resolved_simulation: "Resolve simulation",
  escalated: "Escalated",
  prepared_incident: "Incident prepared",
};

export interface AlertUpdate {
  id: string;
  alertId: string;
  kind: AlertActionKind;
  detail: string;
  at: string;
  actor: string;
}

export interface ManualIncident {
  id: string;
  title: string;
  impact: string;
  severity: "info" | "warning" | "critical";
  createdAt: string;
  actor: string;
}

export interface TimelineEntry {
  id: string;
  at: string;
  actor: string;
  detail: string;
  kind: "job" | "flag" | "alert" | "incident";
  linkTo?: string;
}

// ---------------------------------------------------------------------
// Reducer state
// ---------------------------------------------------------------------

interface State {
  jobActions: PreparedJobAction[];
  flagChanges: PreparedFlagChange[];
  alertUpdates: AlertUpdate[];
  alertStatusOverride: Record<string, AlertStatus>;
  alertOwnerOverride: Record<string, string>;
  manualIncidents: ManualIncident[];
  timeline: TimelineEntry[];
}

const EMPTY: State = {
  jobActions: [],
  flagChanges: [],
  alertUpdates: [],
  alertStatusOverride: {},
  alertOwnerOverride: {},
  manualIncidents: [],
  timeline: [],
};

type Action =
  | { type: "prepare_job_action"; payload: PreparedJobAction; tl: TimelineEntry }
  | { type: "prepare_flag_change"; payload: PreparedFlagChange; tl: TimelineEntry }
  | {
      type: "alert_update";
      payload: AlertUpdate;
      tl: TimelineEntry;
      statusOverride?: { id: string; status: AlertStatus };
      ownerOverride?: { id: string; owner: string };
    }
  | { type: "add_manual_incident"; payload: ManualIncident; tl: TimelineEntry };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "prepare_job_action":
      return {
        ...state,
        jobActions: [...state.jobActions, action.payload],
        timeline: [...state.timeline, action.tl],
      };
    case "prepare_flag_change":
      return {
        ...state,
        flagChanges: [...state.flagChanges, action.payload],
        timeline: [...state.timeline, action.tl],
      };
    case "alert_update":
      return {
        ...state,
        alertUpdates: [...state.alertUpdates, action.payload],
        alertStatusOverride: action.statusOverride
          ? {
              ...state.alertStatusOverride,
              [action.statusOverride.id]: action.statusOverride.status,
            }
          : state.alertStatusOverride,
        alertOwnerOverride: action.ownerOverride
          ? { ...state.alertOwnerOverride, [action.ownerOverride.id]: action.ownerOverride.owner }
          : state.alertOwnerOverride,
        timeline: [...state.timeline, action.tl],
      };
    case "add_manual_incident":
      return {
        ...state,
        manualIncidents: [...state.manualIncidents, action.payload],
        timeline: [...state.timeline, action.tl],
      };
    default:
      return state;
  }
}

// ---------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------

export function useSystemSession(actorName = "Aman Jha", actorRole = "Operations Lead") {
  const [state, dispatch] = useReducer(reducer, EMPTY);

  const prepareJobAction = useCallback(
    (jobId: string, jobRef: string, kind: JobActionKind, note?: string) => {
      const at = new Date().toISOString();
      const payload: PreparedJobAction = { id: uid("ja"), jobId, kind, note, at, actor: actorName };
      const tl: TimelineEntry = {
        id: uid("tl"),
        at,
        actor: actorName,
        kind: "job",
        detail: `${JOB_ACTION_LABEL[kind]} on ${jobRef}${note ? ` — ${note}` : ""}`,
      };
      dispatch({ type: "prepare_job_action", payload, tl });
      return payload;
    },
    [actorName],
  );

  const prepareFlagChange = useCallback(
    (
      flagId: string,
      flagName: string,
      nextState: FlagState,
      nextRolloutPct: number,
      note?: string,
    ) => {
      const at = new Date().toISOString();
      const payload: PreparedFlagChange = {
        id: uid("fc"),
        flagId,
        nextState,
        nextRolloutPct,
        note,
        at,
        actor: actorName,
      };
      const tl: TimelineEntry = {
        id: uid("tl"),
        at,
        actor: actorName,
        kind: "flag",
        detail: `Prepared flag change — ${flagName} → ${FLAG_STATE_LABEL[nextState]}${nextState === "rollout" ? ` (${nextRolloutPct}%)` : ""}${note ? ` — ${note}` : ""}`,
      };
      dispatch({ type: "prepare_flag_change", payload, tl });
      return payload;
    },
    [actorName],
  );

  const updateAlert = useCallback(
    (
      alert: AlertRecord,
      kind: AlertActionKind,
      detail: string,
      opts?: { nextStatus?: AlertStatus; nextOwner?: string },
    ) => {
      const at = new Date().toISOString();
      const payload: AlertUpdate = {
        id: uid("au"),
        alertId: alert.id,
        kind,
        detail,
        at,
        actor: actorName,
      };
      const tl: TimelineEntry = {
        id: uid("tl"),
        at,
        actor: actorName,
        kind: "alert",
        detail: `${ALERT_ACTION_LABEL[kind]} — ${alert.title}${detail ? ` (${detail})` : ""}`,
      };
      dispatch({
        type: "alert_update",
        payload,
        tl,
        statusOverride: opts?.nextStatus ? { id: alert.id, status: opts.nextStatus } : undefined,
        ownerOverride: opts?.nextOwner ? { id: alert.id, owner: opts.nextOwner } : undefined,
      });
      return payload;
    },
    [actorName],
  );

  const addManualIncident = useCallback(
    (title: string, impact: string, severity: ManualIncident["severity"]) => {
      const at = new Date().toISOString();
      const payload: ManualIncident = {
        id: uid("inc"),
        title,
        impact,
        severity,
        createdAt: at,
        actor: actorName,
      };
      const tl: TimelineEntry = {
        id: uid("tl"),
        at,
        actor: actorName,
        kind: "incident",
        detail: `Manual incident prepared — ${title}`,
      };
      dispatch({ type: "add_manual_incident", payload, tl });
      return payload;
    },
    [actorName],
  );

  // ---------------- Overlays ----------------
  const overlayJob = useCallback(
    (job: BackgroundJob): BackgroundJob => {
      const prep = state.jobActions.filter((a) => a.jobId === job.id);
      const latest = prep[prep.length - 1];
      if (!latest) return job;
      return { ...job, preparedAction: latest.kind };
    },
    [state.jobActions],
  );

  const overlayFlag = useCallback(
    (flag: FeatureFlag): FeatureFlag => {
      const changes = state.flagChanges.filter((c) => c.flagId === flag.id);
      const latest = changes[changes.length - 1];
      if (!latest) return flag;
      return { ...flag, state: latest.nextState, rolloutPct: latest.nextRolloutPct };
    },
    [state.flagChanges],
  );

  const overlayAlert = useCallback(
    (alert: AlertRecord): AlertRecord => {
      const status = state.alertStatusOverride[alert.id];
      const owner = state.alertOwnerOverride[alert.id];
      if (!status && !owner) return alert;
      return { ...alert, status: status ?? alert.status, owner: owner ?? alert.owner };
    },
    [state.alertStatusOverride, state.alertOwnerOverride],
  );

  const jobActionsFor = useCallback(
    (jobId: string) => state.jobActions.filter((a) => a.jobId === jobId),
    [state.jobActions],
  );
  const alertUpdatesFor = useCallback(
    (alertId: string) => state.alertUpdates.filter((u) => u.alertId === alertId),
    [state.alertUpdates],
  );

  // ---------------- Aggregate views ----------------
  const preparedFlagsWithMeta = useMemo(
    () =>
      state.flagChanges.map((c) => {
        const flag = mockFeatureFlags.find((f) => f.id === c.flagId);
        return { change: c, flag };
      }),
    [state.flagChanges],
  );

  const alertsWithOverlay = useMemo(() => mockAlerts.map(overlayAlert), [overlayAlert]);

  const hasUnsavedChanges = useMemo(
    () =>
      state.jobActions.length > 0 ||
      state.flagChanges.length > 0 ||
      state.alertUpdates.length > 0 ||
      state.manualIncidents.length > 0,
    [state],
  );

  const unsavedSummary = useMemo(() => {
    const parts: string[] = [];
    if (state.jobActions.length) parts.push(`${state.jobActions.length} prepared job action(s)`);
    if (state.flagChanges.length)
      parts.push(`${state.flagChanges.length} prepared feature-flag change(s)`);
    if (state.alertUpdates.length) parts.push(`${state.alertUpdates.length} alert update(s)`);
    if (state.manualIncidents.length)
      parts.push(`${state.manualIncidents.length} prepared incident(s)`);
    return parts;
  }, [state]);

  return {
    state,
    actorName,
    actorRole,
    // mutators
    prepareJobAction,
    prepareFlagChange,
    updateAlert,
    addManualIncident,
    // overlays
    overlayJob,
    overlayFlag,
    overlayAlert,
    jobActionsFor,
    alertUpdatesFor,
    // views
    preparedFlagsWithMeta,
    alertsWithOverlay,
    hasUnsavedChanges,
    unsavedSummary,
    // constants
    labels: {
      JOB_ACTION_LABEL,
      ALERT_ACTION_LABEL,
      JOB_STATUS_LABEL,
      ALERT_STATUS_LABEL,
      ALERT_KIND_LABEL,
      FLAG_STATE_LABEL,
    },
  };
}

export type SystemSession = ReturnType<typeof useSystemSession>;
