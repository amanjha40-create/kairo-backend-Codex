/**
 * useCommunicationsSession — session-only state for the Communications
 * Center and Communication detail workspaces.
 *
 * Owns:
 *   - internal notes appended in-session
 *   - scheduled / rescheduled / cancelled reminders
 *   - manual "logged as contacted" entries
 *   - failure review acknowledgements
 *   - simulated timeline event overlay
 *
 * Never mutates the imported mock data — all overlays are merged at read.
 * Resets on unmount / reload.
 */

import { useCallback, useMemo, useState } from "react";
import type {
  Communication,
  DeliveryEvent,
  FollowUpRecord,
  InternalNoteSeed,
} from "../data/communications";

function uid(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export interface SessionNote extends InternalNoteSeed {
  category: "operational" | "risk" | "follow_up" | "other";
  sessionOnly: true;
}

export interface ManualContactLog {
  id: string;
  at: string;
  method: "phone" | "in_person" | "chat" | "other";
  summary: string;
  actor: string;
  sessionOnly: true;
}

export interface FailureAcknowledgement {
  failureId: string;
  at: string;
  actor: string;
  resolution: string;
}

interface State {
  notes: Record<string, SessionNote[]>; // communicationId → notes
  scheduledFollowUps: Record<string, FollowUpRecord[]>;
  cancelledFollowUps: Record<string, string[]>; // followUpId list
  rescheduledFollowUps: Record<string, Record<string, string>>; // commId → followUpId → newIso
  manualContacts: Record<string, ManualContactLog[]>;
  failureAcks: Record<string, FailureAcknowledgement[]>;
  sessionEvents: Record<string, DeliveryEvent[]>; // extra timeline entries
}

const EMPTY: State = {
  notes: {},
  scheduledFollowUps: {},
  cancelledFollowUps: {},
  rescheduledFollowUps: {},
  manualContacts: {},
  failureAcks: {},
  sessionEvents: {},
};

export function useCommunicationsSession(actorName = "Aman Jha", actorRole = "Operations Lead") {
  const [state, setState] = useState<State>(EMPTY);

  const addNote = useCallback(
    (commId: string, body: string, category: SessionNote["category"]) => {
      const note: SessionNote = {
        id: uid("note"),
        at: new Date().toISOString(),
        actor: actorName,
        actorRole,
        body,
        category,
        sessionOnly: true,
      };
      setState((s) => ({
        ...s,
        notes: { ...s.notes, [commId]: [...(s.notes[commId] ?? []), note] },
        sessionEvents: {
          ...s.sessionEvents,
          [commId]: [
            ...(s.sessionEvents[commId] ?? []),
            {
              id: uid("evt"),
              at: note.at,
              kind: "prepared",
              detail: `Internal note added (${category})`,
              actor: actorName,
              sessionOnly: true,
            },
          ],
        },
      }));
      return note;
    },
    [actorName, actorRole],
  );

  const scheduleFollowUp = useCallback(
    (commId: string, scheduledAt: string, reason: string) => {
      const record: FollowUpRecord = {
        id: uid("fu"),
        scheduledAt,
        attempt: 0,
        status: "pending",
        reason,
        sessionOnly: true,
      };
      setState((s) => ({
        ...s,
        scheduledFollowUps: {
          ...s.scheduledFollowUps,
          [commId]: [...(s.scheduledFollowUps[commId] ?? []), record],
        },
        sessionEvents: {
          ...s.sessionEvents,
          [commId]: [
            ...(s.sessionEvents[commId] ?? []),
            {
              id: uid("evt"),
              at: new Date().toISOString(),
              kind: "reminder_sent",
              detail: `Reminder scheduled for ${new Date(scheduledAt).toLocaleString()}`,
              actor: actorName,
              sessionOnly: true,
            },
          ],
        },
      }));
      return record;
    },
    [actorName],
  );

  const cancelFollowUp = useCallback(
    (commId: string, followUpId: string) => {
      setState((s) => ({
        ...s,
        cancelledFollowUps: {
          ...s.cancelledFollowUps,
          [commId]: [...(s.cancelledFollowUps[commId] ?? []), followUpId],
        },
        sessionEvents: {
          ...s.sessionEvents,
          [commId]: [
            ...(s.sessionEvents[commId] ?? []),
            {
              id: uid("evt"),
              at: new Date().toISOString(),
              kind: "prepared",
              detail: "Reminder cancelled",
              actor: actorName,
              sessionOnly: true,
            },
          ],
        },
      }));
    },
    [actorName],
  );

  const rescheduleFollowUp = useCallback(
    (commId: string, followUpId: string, newIso: string) => {
      setState((s) => ({
        ...s,
        rescheduledFollowUps: {
          ...s.rescheduledFollowUps,
          [commId]: { ...(s.rescheduledFollowUps[commId] ?? {}), [followUpId]: newIso },
        },
        sessionEvents: {
          ...s.sessionEvents,
          [commId]: [
            ...(s.sessionEvents[commId] ?? []),
            {
              id: uid("evt"),
              at: new Date().toISOString(),
              kind: "reminder_sent",
              detail: `Reminder rescheduled to ${new Date(newIso).toLocaleString()}`,
              actor: actorName,
              sessionOnly: true,
            },
          ],
        },
      }));
    },
    [actorName],
  );

  const logManualContact = useCallback(
    (commId: string, method: ManualContactLog["method"], summary: string) => {
      const record: ManualContactLog = {
        id: uid("mc"),
        at: new Date().toISOString(),
        method,
        summary,
        actor: actorName,
        sessionOnly: true,
      };
      setState((s) => ({
        ...s,
        manualContacts: {
          ...s.manualContacts,
          [commId]: [...(s.manualContacts[commId] ?? []), record],
        },
        sessionEvents: {
          ...s.sessionEvents,
          [commId]: [
            ...(s.sessionEvents[commId] ?? []),
            {
              id: uid("evt"),
              at: record.at,
              kind: "delivered",
              detail: `Manual contact via ${method}: ${summary}`,
              actor: actorName,
              sessionOnly: true,
            },
          ],
        },
      }));
      return record;
    },
    [actorName],
  );

  const acknowledgeFailure = useCallback(
    (commId: string, failureId: string, resolution: string) => {
      const ack: FailureAcknowledgement = {
        failureId,
        at: new Date().toISOString(),
        actor: actorName,
        resolution,
      };
      setState((s) => ({
        ...s,
        failureAcks: {
          ...s.failureAcks,
          [commId]: [...(s.failureAcks[commId] ?? []), ack],
        },
        sessionEvents: {
          ...s.sessionEvents,
          [commId]: [
            ...(s.sessionEvents[commId] ?? []),
            {
              id: uid("evt"),
              at: ack.at,
              kind: "prepared",
              detail: `Failure reviewed: ${resolution}`,
              actor: actorName,
              sessionOnly: true,
            },
          ],
        },
      }));
      return ack;
    },
    [actorName],
  );

  const hasUnsavedChanges = useMemo(() => {
    const counts = [
      state.notes,
      state.scheduledFollowUps,
      state.manualContacts,
      state.failureAcks,
      state.rescheduledFollowUps,
    ].some((r) =>
      Object.values(r).some((v) => (Array.isArray(v) ? v.length > 0 : Object.keys(v).length > 0)),
    );
    const cancels = Object.values(state.cancelledFollowUps).some((v) => v.length > 0);
    return counts || cancels;
  }, [state]);

  /** Merge overlays into a communication for read-time display. */
  const overlay = useCallback(
    (comm: Communication): Communication => {
      const notes = [...comm.internalNotes, ...(state.notes[comm.id] ?? [])];
      const scheduled = state.scheduledFollowUps[comm.id] ?? [];
      const cancelled = new Set(state.cancelledFollowUps[comm.id] ?? []);
      const rescheduled = state.rescheduledFollowUps[comm.id] ?? {};
      const baseFollowUps = comm.followUps.map((f) => {
        if (cancelled.has(f.id)) return { ...f, status: "cancelled" as const };
        if (rescheduled[f.id])
          return { ...f, scheduledAt: rescheduled[f.id], status: "rescheduled" as const };
        return f;
      });
      const followUps = [...baseFollowUps, ...scheduled];
      const events = [...comm.events, ...(state.sessionEvents[comm.id] ?? [])].sort(
        (a, b) => new Date(a.at).getTime() - new Date(b.at).getTime(),
      );
      const nextPending = followUps
        .filter((f) => f.status === "pending" || f.status === "rescheduled")
        .sort((a, b) => new Date(a.scheduledAt).getTime() - new Date(b.scheduledAt).getTime())[0];
      return {
        ...comm,
        internalNotes: notes,
        followUps,
        events,
        nextFollowUpAt: nextPending?.scheduledAt,
      };
    },
    [state],
  );

  return {
    state,
    addNote,
    scheduleFollowUp,
    cancelFollowUp,
    rescheduleFollowUp,
    logManualContact,
    acknowledgeFailure,
    hasUnsavedChanges,
    overlay,
    getManualContacts: (commId: string) => state.manualContacts[commId] ?? [],
    getFailureAcks: (commId: string) => state.failureAcks[commId] ?? [],
  };
}

export type CommunicationsSession = ReturnType<typeof useCommunicationsSession>;
