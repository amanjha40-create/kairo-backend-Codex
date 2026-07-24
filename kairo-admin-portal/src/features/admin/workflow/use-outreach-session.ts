/**
 * useOutreachSession — session-only state for the outreach workflow layer
 * on a single case workspace.
 *
 * Owns:
 *   - session-approved / session-rejected contact ids
 *   - session-added contacts (new contact records that don't exist on the
 *     underlying deterministic mock)
 *   - proposed organization records (session-only, not merged into the
 *     real registry mock)
 *   - simulated outreach attempts and their delivery event stream
 *   - simulated employer responses
 *   - failed-outreach resolution state
 *
 * All state resets on unmount / reload. Nothing is persisted or sent.
 */

import { useCallback, useMemo, useState } from "react";
import type { VerificationCaseDetail, VerificationContact } from "../data/cases";
import type { CaseTimelineEvent } from "../data/cases";
import type { WorkflowActor } from "./types";
import {
  DELIVERY_STATE_LABEL,
  EMPLOYER_RESPONSE_LABEL,
  FAILED_OUTREACH_REASON_LABEL,
  isTerminalDelivery,
  nextDeliveryStates,
  type DeliveryState,
  type EmployerResponseOutcome,
  type FailedOutreachReason,
  type OutreachTemplateId,
} from "./outreach";

function uid(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

// ---------------------------------------------------------------------
// Session record shapes
// ---------------------------------------------------------------------

export interface SessionContactRecord extends VerificationContact {
  sessionOnly: true;
}

export interface SessionProposedOrgRecord {
  id: string;
  name: string;
  domain?: string;
  country?: string;
  reason: string;
  actorName: string;
  at: string;
}

export interface DeliveryEventRecord {
  id: string;
  state: DeliveryState;
  at: string;
  note?: string;
  actorName: string;
}

export interface EmployerResponseRecord {
  id: string;
  outcome: EmployerResponseOutcome;
  summary: string;
  fieldConfirmations?: Record<string, "confirmed" | "denied" | "unknown">;
  actorName: string;
  at: string;
}

export interface FailedOutreachRecord {
  id: string;
  attemptId: string;
  reason: FailedOutreachReason;
  narrative: string;
  alternativeContactId?: string;
  actorName: string;
  at: string;
}

export interface OutreachAttemptRecord {
  id: string;
  contactId: string;
  contactName: string;
  templateId: OutreachTemplateId;
  subject: string;
  bodyPreview: string;
  actorName: string;
  createdAt: string;
  events: DeliveryEventRecord[];
  employerResponse?: EmployerResponseRecord;
  failedResolution?: FailedOutreachRecord;
  followUpOfId?: string;
}

// ---------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------

export interface UseOutreachSessionResult {
  // Contact review
  sessionApprovedContactIds: Set<string>;
  sessionRejectedContactIds: Set<string>;
  sessionAddedContacts: SessionContactRecord[];
  approveContact: (contactId: string, contactName: string) => void;
  rejectContact: (contactId: string, contactName: string, reason: string) => void;
  addContact: (draft: Omit<VerificationContact, "id" | "sessionOnly">) => SessionContactRecord;

  // Organization resolution
  proposedOrgs: SessionProposedOrgRecord[];
  orgResolvedInSession: boolean;
  acceptedOrgMatchId: string | null;
  rejectedSuggestionIds: Set<string>;
  uncertainSuggestionIds: Set<string>;
  duplicateFlagNotes: string[];
  acceptOrgMatch: (id: string, name: string) => void;
  rejectOrgSuggestion: (id: string, name: string, reason?: string) => void;
  markOrgUncertain: (id: string, name: string, note?: string) => void;
  proposeNewOrg: (draft: Omit<SessionProposedOrgRecord, "id" | "at" | "actorName">) => void;
  flagOrgDuplicate: (note: string) => void;

  // Outreach attempts
  outreachAttempts: OutreachAttemptRecord[];
  prepareAttempt: (input: {
    contactId: string;
    contactName: string;
    templateId: OutreachTemplateId;
    subject: string;
    bodyPreview: string;
    followUpOfId?: string;
  }) => OutreachAttemptRecord;
  simulateNextEvent: (attemptId: string, nextState: DeliveryState, note?: string) => void;
  recordEmployerResponse: (
    attemptId: string,
    payload: {
      outcome: EmployerResponseOutcome;
      summary: string;
      fieldConfirmations?: Record<string, "confirmed" | "denied" | "unknown">;
    },
  ) => void;
  markFailedOutreach: (
    attemptId: string,
    payload: {
      reason: FailedOutreachReason;
      narrative: string;
      alternativeContactId?: string;
    },
  ) => void;

  // Cross-cutting
  extraTimelineEvents: CaseTimelineEvent[];
  hasSessionChanges: boolean;
}

export function useOutreachSession(
  detail: VerificationCaseDetail,
  actor: WorkflowActor,
): UseOutreachSessionResult {
  const [approved, setApproved] = useState<Set<string>>(new Set());
  const [rejected, setRejected] = useState<Set<string>>(new Set());
  const [added, setAdded] = useState<SessionContactRecord[]>([]);
  const [proposedOrgs, setProposedOrgs] = useState<SessionProposedOrgRecord[]>([]);
  const [acceptedOrgMatchId, setAcceptedOrgMatchId] = useState<string | null>(null);
  const [rejectedSuggestionIds, setRejectedSuggestionIds] = useState<Set<string>>(new Set());
  const [uncertainSuggestionIds, setUncertainSuggestionIds] = useState<Set<string>>(new Set());
  const [duplicateFlagNotes, setDuplicateFlagNotes] = useState<string[]>([]);
  const [attempts, setAttempts] = useState<OutreachAttemptRecord[]>([]);
  const [events, setEvents] = useState<CaseTimelineEvent[]>([]);

  const appendTimeline = useCallback((ev: Omit<CaseTimelineEvent, "id" | "at" | "sessionOnly">) => {
    setEvents((prev) => [
      ...prev,
      {
        ...ev,
        id: uid("session"),
        at: new Date().toISOString(),
        sessionOnly: true,
      },
    ]);
  }, []);

  // -------------------- Contact review --------------------

  const approveContact = useCallback(
    (contactId: string, contactName: string) => {
      setRejected((prev) => {
        if (!prev.has(contactId)) return prev;
        const next = new Set(prev);
        next.delete(contactId);
        return next;
      });
      setApproved((prev) => {
        if (prev.has(contactId)) return prev;
        const next = new Set(prev);
        next.add(contactId);
        return next;
      });
      appendTimeline({
        kind: "contact_approved",
        actor: actor.name,
        actorSource: "admin",
        description: `Contact approved for outreach: ${contactName}.`,
      });
    },
    [actor.name, appendTimeline],
  );

  const rejectContact = useCallback(
    (contactId: string, contactName: string, reason: string) => {
      setApproved((prev) => {
        if (!prev.has(contactId)) return prev;
        const next = new Set(prev);
        next.delete(contactId);
        return next;
      });
      setRejected((prev) => {
        if (prev.has(contactId)) return prev;
        const next = new Set(prev);
        next.add(contactId);
        return next;
      });
      appendTimeline({
        kind: "contact_approved",
        actor: actor.name,
        actorSource: "admin",
        description: `Contact rejected: ${contactName} — ${reason}.`,
      });
    },
    [actor.name, appendTimeline],
  );

  const addContact = useCallback(
    (draft: Omit<VerificationContact, "id" | "sessionOnly">) => {
      const rec: SessionContactRecord = {
        ...draft,
        id: uid("contact"),
        sessionOnly: true,
      };
      setAdded((prev) => [...prev, rec]);
      appendTimeline({
        kind: "contact_approved",
        actor: actor.name,
        actorSource: "admin",
        description: `New verification contact added in session: ${draft.name} (${draft.emailMasked}).`,
      });
      return rec;
    },
    [actor.name, appendTimeline],
  );

  // -------------------- Organization resolution --------------------

  const acceptOrgMatch = useCallback(
    (id: string, name: string) => {
      setAcceptedOrgMatchId(id);
      appendTimeline({
        kind: "organization_match",
        actor: actor.name,
        actorSource: "admin",
        description: `Accepted suggested organization match: ${name}.`,
      });
    },
    [actor.name, appendTimeline],
  );

  const proposeNewOrg = useCallback(
    (draft: Omit<SessionProposedOrgRecord, "id" | "at" | "actorName">) => {
      const rec: SessionProposedOrgRecord = {
        ...draft,
        id: uid("proposed-org"),
        at: new Date().toISOString(),
        actorName: actor.name,
      };
      setProposedOrgs((prev) => [...prev, rec]);
      appendTimeline({
        kind: "organization_match",
        actor: actor.name,
        actorSource: "admin",
        description: `Proposed new registry organization: ${draft.name} (session-only, awaits registry approval).`,
      });
    },
    [actor.name, appendTimeline],
  );

  const flagOrgDuplicate = useCallback(
    (note: string) => {
      setDuplicateFlagNotes((prev) => [...prev, note]);
      appendTimeline({
        kind: "organization_match",
        actor: actor.name,
        actorSource: "admin",
        description: `Flagged organization for duplicate review: ${note}`,
      });
    },
    [actor.name, appendTimeline],
  );

  const rejectOrgSuggestion = useCallback(
    (id: string, name: string, reason?: string) => {
      setRejectedSuggestionIds((prev) => {
        if (prev.has(id)) return prev;
        const next = new Set(prev);
        next.add(id);
        return next;
      });
      setUncertainSuggestionIds((prev) => {
        if (!prev.has(id)) return prev;
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      appendTimeline({
        kind: "organization_match",
        actor: actor.name,
        actorSource: "admin",
        description: `Rejected suggested organization match: ${name}${reason ? ` — ${reason}` : ""}.`,
      });
    },
    [actor.name, appendTimeline],
  );

  const markOrgUncertain = useCallback(
    (id: string, name: string, note?: string) => {
      setUncertainSuggestionIds((prev) => {
        if (prev.has(id)) return prev;
        const next = new Set(prev);
        next.add(id);
        return next;
      });
      appendTimeline({
        kind: "organization_match",
        actor: actor.name,
        actorSource: "admin",
        description: `Marked organization match as uncertain: ${name}${note ? ` — ${note}` : ""}.`,
      });
    },
    [actor.name, appendTimeline],
  );

  // -------------------- Outreach attempts --------------------

  const prepareAttempt = useCallback(
    (input: {
      contactId: string;
      contactName: string;
      templateId: OutreachTemplateId;
      subject: string;
      bodyPreview: string;
      followUpOfId?: string;
    }) => {
      const attempt: OutreachAttemptRecord = {
        id: uid("out"),
        contactId: input.contactId,
        contactName: input.contactName,
        templateId: input.templateId,
        subject: input.subject,
        bodyPreview: input.bodyPreview,
        actorName: actor.name,
        createdAt: new Date().toISOString(),
        followUpOfId: input.followUpOfId,
        events: [
          {
            id: uid("evt"),
            state: "prepared",
            at: new Date().toISOString(),
            actorName: actor.name,
          },
        ],
      };
      setAttempts((prev) => [...prev, attempt]);
      appendTimeline({
        kind: "outreach_event",
        actor: actor.name,
        actorSource: "admin",
        description: `Outreach prepared for ${input.contactName} (${input.templateId}).`,
      });
      return attempt;
    },
    [actor.name, appendTimeline],
  );

  const simulateNextEvent = useCallback(
    (attemptId: string, nextState: DeliveryState, note?: string) => {
      setAttempts((prev) =>
        prev.map((a) => {
          if (a.id !== attemptId) return a;
          const last = a.events[a.events.length - 1];
          if (isTerminalDelivery(last.state)) return a;
          if (!nextDeliveryStates(last.state).includes(nextState)) return a;
          return {
            ...a,
            events: [
              ...a.events,
              {
                id: uid("evt"),
                state: nextState,
                at: new Date().toISOString(),
                note,
                actorName: actor.name,
              },
            ],
          };
        }),
      );
      appendTimeline({
        kind: "outreach_event",
        actor: actor.name,
        actorSource:
          nextState === "responded" || nextState === "opened" || nextState === "link_opened"
            ? "employer"
            : "system",
        description: `Simulated delivery event: ${DELIVERY_STATE_LABEL[nextState]}.`,
      });
    },
    [actor.name, appendTimeline],
  );

  const recordEmployerResponse = useCallback(
    (
      attemptId: string,
      payload: {
        outcome: EmployerResponseOutcome;
        summary: string;
        fieldConfirmations?: Record<string, "confirmed" | "denied" | "unknown">;
      },
    ) => {
      const rec: EmployerResponseRecord = {
        id: uid("resp"),
        outcome: payload.outcome,
        summary: payload.summary,
        fieldConfirmations: payload.fieldConfirmations,
        actorName: actor.name,
        at: new Date().toISOString(),
      };
      setAttempts((prev) =>
        prev.map((a) => (a.id === attemptId ? { ...a, employerResponse: rec } : a)),
      );
      appendTimeline({
        kind: "employer_response",
        actor: actor.name,
        actorSource: "employer",
        description: `Employer response recorded: ${EMPLOYER_RESPONSE_LABEL[payload.outcome]}.`,
      });
    },
    [actor.name, appendTimeline],
  );

  const markFailedOutreach = useCallback(
    (
      attemptId: string,
      payload: {
        reason: FailedOutreachReason;
        narrative: string;
        alternativeContactId?: string;
      },
    ) => {
      const rec: FailedOutreachRecord = {
        id: uid("fail"),
        attemptId,
        reason: payload.reason,
        narrative: payload.narrative,
        alternativeContactId: payload.alternativeContactId,
        actorName: actor.name,
        at: new Date().toISOString(),
      };
      setAttempts((prev) =>
        prev.map((a) => (a.id === attemptId ? { ...a, failedResolution: rec } : a)),
      );
      appendTimeline({
        kind: "outreach_event",
        actor: actor.name,
        actorSource: "admin",
        description: `Outreach marked as failed — ${FAILED_OUTREACH_REASON_LABEL[payload.reason]}.`,
      });
    },
    [actor.name, appendTimeline],
  );

  // -------------------- Aggregates --------------------

  const orgResolvedInSession = useMemo(() => {
    if (detail.organization.state === "resolved") return true;
    if (acceptedOrgMatchId) return true;
    return false;
  }, [detail.organization.state, acceptedOrgMatchId]);

  const hasSessionChanges =
    approved.size > 0 ||
    rejected.size > 0 ||
    added.length > 0 ||
    proposedOrgs.length > 0 ||
    acceptedOrgMatchId !== null ||
    rejectedSuggestionIds.size > 0 ||
    uncertainSuggestionIds.size > 0 ||
    duplicateFlagNotes.length > 0 ||
    attempts.length > 0 ||
    events.length > 0;

  return {
    sessionApprovedContactIds: approved,
    sessionRejectedContactIds: rejected,
    sessionAddedContacts: added,
    approveContact,
    rejectContact,
    addContact,
    proposedOrgs,
    orgResolvedInSession,
    acceptedOrgMatchId,
    rejectedSuggestionIds,
    uncertainSuggestionIds,
    duplicateFlagNotes,
    acceptOrgMatch,
    rejectOrgSuggestion,
    markOrgUncertain,
    proposeNewOrg,
    flagOrgDuplicate,
    outreachAttempts: attempts,
    prepareAttempt,
    simulateNextEvent,
    recordEmployerResponse,
    markFailedOutreach,
    extraTimelineEvents: events,
    hasSessionChanges,
  };
}
