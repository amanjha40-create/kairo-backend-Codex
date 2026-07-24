/**
 * useInvestigationSession — session-only state for a Trust & Safety
 * investigation workspace.
 *
 * Owns:
 *   - internal investigation notes (categorized)
 *   - evidence selections for the current review
 *   - duplicate-review decisions
 *   - simulated status changes and prepared recommended actions
 *   - a timeline overlay merged on read
 *
 * Never mutates imported mock data. Resets on unmount / reload.
 */

import { useCallback, useMemo, useState } from "react";
import {
  EVENT_KIND_LABEL,
  INVESTIGATION_STATUS_LABEL,
  RECOMMENDED_ACTION_LABEL,
  type Investigation,
  type InvestigationEventKind,
  type InvestigationNote,
  type InvestigationStatus,
  type InvestigationTimelineEvent,
  type NoteCategory,
  type RecommendedActionKind,
} from "../data/risk";

function uid(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export type DuplicateDecision =
  "not_duplicate" | "continue_investigation" | "recommend_merge_review" | "escalate";

export const DUPLICATE_DECISION_LABEL: Record<DuplicateDecision, string> = {
  not_duplicate: "Marked not a duplicate",
  continue_investigation: "Continue investigation",
  recommend_merge_review: "Recommend merge review",
  escalate: "Escalated to Trust & Safety",
};

export interface PreparedAction {
  id: string;
  kind: RecommendedActionKind;
  rationale: string;
  at: string;
  actor: string;
}

interface State {
  notes: Record<string, InvestigationNote[]>;
  selectedEvidence: Record<string, Set<string>>;
  duplicateDecisions: Record<
    string,
    { decision: DuplicateDecision; rationale: string; at: string; actor: string }
  >;
  statusOverride: Record<string, InvestigationStatus>;
  preparedActions: Record<string, PreparedAction[]>;
  extraEvents: Record<string, InvestigationTimelineEvent[]>;
}

const EMPTY: State = {
  notes: {},
  selectedEvidence: {},
  duplicateDecisions: {},
  statusOverride: {},
  preparedActions: {},
  extraEvents: {},
};

export function useInvestigationSession(actorName = "Aman Jha", actorRole = "Operations Lead") {
  const [state, setState] = useState<State>(EMPTY);

  const appendEvent = useCallback(
    (invId: string, kind: InvestigationEventKind, detail: string) => {
      const evt: InvestigationTimelineEvent = {
        id: uid("evt"),
        at: new Date().toISOString(),
        kind,
        actor: actorName,
        detail,
        sessionOnly: true,
      };
      setState((s) => ({
        ...s,
        extraEvents: {
          ...s.extraEvents,
          [invId]: [...(s.extraEvents[invId] ?? []), evt],
        },
      }));
      return evt;
    },
    [actorName],
  );

  const addNote = useCallback(
    (invId: string, body: string, category: NoteCategory) => {
      const note: InvestigationNote = {
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
        notes: { ...s.notes, [invId]: [...(s.notes[invId] ?? []), note] },
        extraEvents: {
          ...s.extraEvents,
          [invId]: [
            ...(s.extraEvents[invId] ?? []),
            {
              id: uid("evt"),
              at: note.at,
              kind: "note_added",
              actor: actorName,
              detail: `${EVENT_KIND_LABEL.note_added} (${category})`,
              sessionOnly: true,
            },
          ],
        },
      }));
      return note;
    },
    [actorName, actorRole],
  );

  const toggleEvidence = useCallback((invId: string, evId: string) => {
    setState((s) => {
      const current = new Set(s.selectedEvidence[invId] ?? []);
      if (current.has(evId)) current.delete(evId);
      else current.add(evId);
      return {
        ...s,
        selectedEvidence: { ...s.selectedEvidence, [invId]: current },
      };
    });
  }, []);

  const recordDuplicateDecision = useCallback(
    (invId: string, decision: DuplicateDecision, rationale: string) => {
      const at = new Date().toISOString();
      setState((s) => ({
        ...s,
        duplicateDecisions: {
          ...s.duplicateDecisions,
          [invId]: { decision, rationale, at, actor: actorName },
        },
        extraEvents: {
          ...s.extraEvents,
          [invId]: [
            ...(s.extraEvents[invId] ?? []),
            {
              id: uid("evt"),
              at,
              kind: decision === "escalate" ? "escalated" : "note_added",
              actor: actorName,
              detail:
                `Duplicate review — ${DUPLICATE_DECISION_LABEL[decision]}. ${rationale}`.trim(),
              sessionOnly: true,
            },
          ],
        },
      }));
    },
    [actorName],
  );

  const simulateStatus = useCallback(
    (invId: string, next: InvestigationStatus) => {
      const at = new Date().toISOString();
      setState((s) => ({
        ...s,
        statusOverride: { ...s.statusOverride, [invId]: next },
        extraEvents: {
          ...s.extraEvents,
          [invId]: [
            ...(s.extraEvents[invId] ?? []),
            {
              id: uid("evt"),
              at,
              kind: "status_changed",
              actor: actorName,
              detail: `Status simulated → ${INVESTIGATION_STATUS_LABEL[next]}`,
              sessionOnly: true,
            },
          ],
        },
      }));
    },
    [actorName],
  );

  const prepareAction = useCallback(
    (invId: string, kind: RecommendedActionKind, rationale: string) => {
      const action: PreparedAction = {
        id: uid("act"),
        kind,
        rationale,
        at: new Date().toISOString(),
        actor: actorName,
      };
      setState((s) => ({
        ...s,
        preparedActions: {
          ...s.preparedActions,
          [invId]: [...(s.preparedActions[invId] ?? []), action],
        },
        extraEvents: {
          ...s.extraEvents,
          [invId]: [
            ...(s.extraEvents[invId] ?? []),
            {
              id: uid("evt"),
              at: action.at,
              kind: "recommended_action",
              actor: actorName,
              detail: `Prepared: ${RECOMMENDED_ACTION_LABEL[kind]}. ${rationale}`.trim(),
              sessionOnly: true,
            },
          ],
        },
      }));
      return action;
    },
    [actorName],
  );

  const hasUnsavedChanges = useMemo(() => {
    return (
      Object.values(state.notes).some((n) => n.length > 0) ||
      Object.values(state.selectedEvidence).some((s) => s.size > 0) ||
      Object.keys(state.duplicateDecisions).length > 0 ||
      Object.keys(state.statusOverride).length > 0 ||
      Object.values(state.preparedActions).some((a) => a.length > 0)
    );
  }, [state]);

  const overlay = useCallback(
    (inv: Investigation): Investigation => {
      const extraNotes = state.notes[inv.id] ?? [];
      const extraEvents = state.extraEvents[inv.id] ?? [];
      const nextStatus = state.statusOverride[inv.id];
      const timeline = [...inv.timeline, ...extraEvents].sort(
        (a, b) => new Date(a.at).getTime() - new Date(b.at).getTime(),
      );
      return {
        ...inv,
        status: nextStatus ?? inv.status,
        notes: [...inv.notes, ...extraNotes],
        timeline,
      };
    },
    [state],
  );

  const getSelectedEvidence = useCallback(
    (invId: string) => state.selectedEvidence[invId] ?? new Set<string>(),
    [state],
  );
  const getDuplicateDecision = useCallback(
    (invId: string) => state.duplicateDecisions[invId],
    [state],
  );
  const getPreparedActions = useCallback(
    (invId: string) => state.preparedActions[invId] ?? [],
    [state],
  );

  return {
    state,
    addNote,
    appendEvent,
    toggleEvidence,
    recordDuplicateDecision,
    simulateStatus,
    prepareAction,
    hasUnsavedChanges,
    overlay,
    getSelectedEvidence,
    getDuplicateDecision,
    getPreparedActions,
  };
}

export type InvestigationSession = ReturnType<typeof useInvestigationSession>;
