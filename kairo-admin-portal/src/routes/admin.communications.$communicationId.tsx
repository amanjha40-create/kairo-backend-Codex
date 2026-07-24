import { useState } from "react";
import { Link, createFileRoute, notFound } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BellRing,
  CalendarClock,
  CheckCircle2,
  ExternalLink,
  FileText,
  MailWarning,
  MessageSquare,
  PhoneCall,
  ShieldAlert,
} from "lucide-react";
import { SectionHeader } from "@/features/admin/components/section-header";
import { WorkspaceSection } from "@/features/admin/components/workspace-section";
import { EmptyState } from "@/features/admin/components/states";

import { useAdminAccess } from "@/features/admin/auth/admin-access";
import { hasPermission } from "@/features/admin/workflow/permissions";
import { formatRelativeTime } from "@/features/admin/lib/format";
import { useCommunicationsSession } from "@/features/admin/workflow/use-communications-session";
import {
  COMMUNICATION_CHANNEL_LABEL,
  COMMUNICATION_TYPE_LABEL,
  DELIVERY_EVENT_LABEL,
  FAILURE_REASON_LABEL,
  FAILURE_RECOMMENDED_ACTION,
  getCommunication,
  getTemplate,
  type Communication,
  type DeliveryEvent,
} from "@/features/admin/data/communications";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { CommStatusBadge } from "./admin.communications.index";

export const Route = createFileRoute("/admin/communications/$communicationId")({
  loader: ({ params }) => {
    const comm = getCommunication(params.communicationId);
    if (!comm) throw notFound();
    return { comm };
  },
  head: ({ loaderData }) => {
    if (!loaderData)
      return {
        meta: [
          { title: "Communication not found — Kairo Admin" },
          { name: "robots", content: "noindex, nofollow" },
        ],
      };
    return {
      meta: [
        { title: `${loaderData.comm.reference} — Communications — Kairo Admin` },
        { name: "robots", content: "noindex, nofollow" },
      ],
    };
  },
  errorComponent: ({ error }) => (
    <EmptyState title="Something went wrong" description={error.message} />
  ),
  notFoundComponent: NotFoundView,
  component: CommunicationDetailPage,
});

function NotFoundView() {
  return (
    <div className="mx-auto max-w-3xl">
      <EmptyState
        title="Communication not found"
        description="This ID does not exist in the deterministic mock catalogue."
        action={
          <Link
            to="/admin/communications"
            className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent"
          >
            <ArrowLeft aria-hidden className="size-3.5" /> Back to Communications
          </Link>
        }
      />
    </div>
  );
}

function CommunicationDetailPage() {
  const { comm: base } = Route.useLoaderData();
  const { admin } = useAdminAccess();
  const permissions = admin?.permissions ?? [];
  const canView = hasPermission(permissions, "communications.view");
  const canNote = hasPermission(permissions, "communications.notes.create");
  const canSchedule = hasPermission(permissions, "communications.followup.schedule");
  const canCancel = hasPermission(permissions, "communications.followup.cancel");
  const canLog = hasPermission(permissions, "communications.manual_contact.log");
  const canReviewFailures = hasPermission(permissions, "communications.failure.review");

  const session = useCommunicationsSession(
    admin?.name ?? "Aman Jha",
    admin?.role ?? "Operations Lead",
  );
  const comm = session.overlay(base);

  if (!canView)
    return (
      <EmptyState title="No access" description="Your role does not include communications.view." />
    );

  const template = getTemplate(comm.template);
  const manualContacts = session.getManualContacts(comm.id);
  const failureAcks = session.getFailureAcks(comm.id);

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-6">
      {/* Breadcrumbs */}
      <nav aria-label="Breadcrumb" className="text-xs text-muted-foreground">
        <ol className="flex flex-wrap items-center gap-1">
          <li>
            <Link to="/admin/communications" className="hover:text-foreground">
              Communications
            </Link>
          </li>
          <li aria-hidden>/</li>
          <li className="text-foreground">{comm.reference}</li>
        </ol>
      </nav>

      {/* Header */}
      <header className="rounded-lg border border-border bg-card p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <CommStatusBadge status={comm.status} />
              <span className="text-xs uppercase tracking-wide text-muted-foreground">
                {COMMUNICATION_CHANNEL_LABEL[comm.channel]} · {COMMUNICATION_TYPE_LABEL[comm.type]}
              </span>
            </div>
            <h1 className="mt-1 truncate text-lg font-semibold text-foreground">{comm.subject}</h1>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {comm.reference} · sent {formatRelativeTime(comm.sentAt)} · attempt #
              {comm.attemptCount}
              {comm.nextFollowUpAt && (
                <> · next follow-up {formatRelativeTime(comm.nextFollowUpAt)}</>
              )}
            </p>
          </div>
          <div className="text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-border bg-muted/40 px-2 py-1">
              <ShieldAlert aria-hidden className="size-3.5" /> Session-only workspace
            </span>
          </div>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Main column */}
        <div className="flex flex-col gap-4 lg:col-span-2">
          {/* Delivery timeline */}
          <WorkspaceSection
            id="timeline"
            title="Delivery timeline"
            description="Historical mock events and session-simulated events, in order."
          >
            <DeliveryTimeline events={comm.events} />
          </WorkspaceSection>

          {/* Follow-ups */}
          <WorkspaceSection
            id="followups"
            title="Follow-up history"
            description="Scheduled reminders. Session-scheduled reminders are labelled."
          >
            <FollowUpSection
              comm={comm}
              canSchedule={canSchedule}
              canCancel={canCancel}
              onSchedule={(iso, reason) => {
                session.scheduleFollowUp(comm.id, iso, reason);
                toast.success("Reminder scheduled (session only)");
              }}
              onCancel={(id) => {
                session.cancelFollowUp(comm.id, id);
                toast.success("Reminder cancelled (session only)");
              }}
              onReschedule={(id, iso) => {
                session.rescheduleFollowUp(comm.id, id, iso);
                toast.success("Reminder rescheduled (session only)");
              }}
              canLog={canLog}
              onLogManual={(m, s) => {
                session.logManualContact(comm.id, m, s);
                toast.success("Manual contact logged (session only)");
              }}
              manualContacts={manualContacts}
            />
          </WorkspaceSection>

          {/* Failures */}
          {(comm.failures.length > 0 || failureAcks.length > 0) && (
            <WorkspaceSection
              id="failures"
              title="Failure history"
              description="Delivery failures and reviewer resolutions."
            >
              <FailureSection
                comm={comm}
                canReview={canReviewFailures}
                onAck={(fid, res) => {
                  session.acknowledgeFailure(comm.id, fid, res);
                  toast.success("Failure review recorded (session only)");
                }}
                acks={failureAcks}
              />
            </WorkspaceSection>
          )}

          {/* Employer responses */}
          {comm.responses.length > 0 && (
            <WorkspaceSection
              id="responses"
              title="Employer responses"
              description="Verifier outcomes recorded for this communication."
            >
              <ul className="divide-y divide-border">
                {comm.responses.map((r) => (
                  <li key={r.id} className="py-3">
                    <p className="text-sm font-medium text-foreground">
                      {r.outcome.toUpperCase()} — {formatRelativeTime(r.at)}
                    </p>
                    <p className="mt-0.5 text-sm text-foreground">{r.body}</p>
                    {r.actionRequired && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        Action: {r.actionRequired}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </WorkspaceSection>
          )}

          {/* Internal notes */}
          <WorkspaceSection
            id="notes"
            title="Internal notes"
            description="Operational notes. Never visible to the candidate."
          >
            <NotesSection
              notes={comm.internalNotes}
              canAdd={canNote}
              onAdd={(body, category) => {
                session.addNote(comm.id, body, category);
                toast.success("Internal note added (session only)");
              }}
            />
          </WorkspaceSection>
        </div>

        {/* Sidebar */}
        <aside className="flex flex-col gap-4">
          {/* Recipient / Org / Case */}
          <WorkspaceSection title="Recipient & context">
            <dl className="space-y-2 text-xs">
              <Row
                label="Recipient"
                value={
                  <>
                    <div className="text-foreground">{comm.contactName ?? "—"}</div>
                    <div className="font-mono">{comm.contactEmailMasked}</div>
                  </>
                }
              />
              <Row
                label="Organization"
                value={
                  comm.organizationId ? (
                    <Link
                      to="/admin/registry/$organizationId"
                      params={{ organizationId: comm.organizationId }}
                      className="inline-flex items-center gap-1 text-foreground underline-offset-2 hover:underline"
                    >
                      {comm.organizationName} <ExternalLink aria-hidden className="size-3" />
                    </Link>
                  ) : (
                    "—"
                  )
                }
              />
              <Row
                label="Candidate"
                value={
                  comm.candidateId ? (
                    <Link
                      to="/admin/users/$userId"
                      params={{ userId: comm.candidateId }}
                      className="inline-flex items-center gap-1 text-foreground underline-offset-2 hover:underline"
                    >
                      {comm.candidateName} <ExternalLink aria-hidden className="size-3" />
                    </Link>
                  ) : (
                    "—"
                  )
                }
              />
              <Row
                label="Verification case"
                value={
                  comm.caseId ? (
                    <Link
                      to="/admin/verifications/$caseId"
                      params={{ caseId: comm.caseId }}
                      className="inline-flex items-center gap-1 text-foreground underline-offset-2 hover:underline"
                    >
                      {comm.caseReference} <ExternalLink aria-hidden className="size-3" />
                    </Link>
                  ) : (
                    "—"
                  )
                }
              />
              <Row
                label="Assigned reviewer"
                value={<span className="text-foreground">{comm.assignedReviewer}</span>}
              />
            </dl>
          </WorkspaceSection>

          {/* Template */}
          <WorkspaceSection title="Template used">
            {template ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-medium text-foreground">{template.name}</p>
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                    {template.version}
                  </span>
                </div>
                <div className="rounded-md border border-border bg-muted/30 p-2">
                  <p className="text-xs text-muted-foreground">Subject</p>
                  <p className="text-xs text-foreground">{template.subjectPreview}</p>
                </div>
                <details className="rounded-md border border-border">
                  <summary className="cursor-pointer px-2 py-1.5 text-xs font-medium text-foreground">
                    Preview body
                  </summary>
                  <pre className="whitespace-pre-wrap px-2 pb-2 font-sans text-xs text-muted-foreground">
                    {template.bodyPreview}
                  </pre>
                </details>
                <p className="text-[11px] text-muted-foreground">
                  Variables: {template.variables.map((v) => `{{${v}}}`).join(", ")}
                </p>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">Template metadata unavailable.</p>
            )}
          </WorkspaceSection>

          {/* Session activity */}
          <WorkspaceSection
            title="Session activity"
            description="Everything you have done in this browser session."
          >
            <SessionActivity comm={comm} manualContacts={manualContacts} />
          </WorkspaceSection>
        </aside>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[110px_1fr] gap-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-foreground">{value}</dd>
    </div>
  );
}

// ---------------------------------------------------------------------
// Timeline
// ---------------------------------------------------------------------
function DeliveryTimeline({ events }: { events: DeliveryEvent[] }) {
  if (events.length === 0) return <EmptyState title="No delivery events yet." />;
  return (
    <ol className="relative space-y-3 border-l border-border pl-4">
      {events.map((e) => (
        <li key={e.id} className="relative">
          <span
            className={cn(
              "absolute -left-[19px] top-1 size-2.5 rounded-full ring-2 ring-background",
              e.sessionOnly ? "bg-sky-500" : eventTone(e.kind),
            )}
            aria-hidden
          />
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div className="min-w-0">
              <p className="text-sm font-medium text-foreground">
                {DELIVERY_EVENT_LABEL[e.kind]}
                {e.sessionOnly && (
                  <span className="ml-2 rounded bg-sky-50 px-1 text-[10px] font-semibold text-sky-900 ring-1 ring-inset ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200">
                    Session
                  </span>
                )}
              </p>
              {e.detail && <p className="text-xs text-muted-foreground">{e.detail}</p>}
            </div>
            <p className="text-[11px] text-muted-foreground">
              {formatRelativeTime(e.at)}
              {e.actor && <> · {e.actor}</>}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}
function eventTone(k: DeliveryEvent["kind"]): string {
  if (k === "failed" || k === "bounce" || k === "complaint" || k === "suppressed")
    return "bg-rose-500";
  if (k === "delivered" || k === "employer_responded") return "bg-emerald-500";
  if (k === "opened" || k === "verification_link_opened" || k === "reminder_sent")
    return "bg-indigo-500";
  return "bg-muted-foreground";
}

// ---------------------------------------------------------------------
// Follow-ups
// ---------------------------------------------------------------------
function FollowUpSection({
  comm,
  canSchedule,
  canCancel,
  onSchedule,
  onCancel,
  onReschedule,
  canLog,
  onLogManual,
  manualContacts,
}: {
  comm: Communication;
  canSchedule: boolean;
  canCancel: boolean;
  onSchedule: (iso: string, reason: string) => void;
  onCancel: (id: string) => void;
  onReschedule: (id: string, iso: string) => void;
  canLog: boolean;
  onLogManual: (method: "phone" | "in_person" | "chat" | "other", summary: string) => void;
  manualContacts: ReturnType<ReturnType<typeof useCommunicationsSession>["getManualContacts"]>;
}) {
  const [when, setWhen] = useState("");
  const [reason, setReason] = useState("");
  const [manualMethod, setManualMethod] = useState<"phone" | "in_person" | "chat" | "other">(
    "phone",
  );
  const [manualSummary, setManualSummary] = useState("");

  return (
    <div className="space-y-3">
      {comm.followUps.length === 0 && manualContacts.length === 0 ? (
        <p className="text-xs text-muted-foreground">No follow-ups scheduled yet.</p>
      ) : (
        <ul className="divide-y divide-border">
          {comm.followUps.map((f) => (
            <li
              key={f.id}
              className="flex flex-wrap items-start justify-between gap-2 py-2 text-xs"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground">
                  Attempt #{f.attempt || "?"} — {new Date(f.scheduledAt).toLocaleString()}
                </p>
                <p className="text-muted-foreground">
                  {f.reason ?? "—"} · status: {f.status}
                  {f.sessionOnly && " (session)"}
                </p>
              </div>
              {f.status === "pending" || f.status === "rescheduled" ? (
                <div className="flex gap-1">
                  <input
                    type="datetime-local"
                    aria-label="Reschedule"
                    className="rounded border border-border bg-background px-1.5 py-1 text-[11px]"
                    onChange={(e) =>
                      e.target.value && onReschedule(f.id, new Date(e.target.value).toISOString())
                    }
                  />
                  {canCancel && (
                    <button
                      type="button"
                      onClick={() => onCancel(f.id)}
                      className="rounded border border-border px-2 py-1 text-[11px] text-foreground hover:bg-accent"
                    >
                      Cancel
                    </button>
                  )}
                </div>
              ) : null}
            </li>
          ))}
          {manualContacts.map((m) => (
            <li key={m.id} className="py-2 text-xs">
              <p className="text-sm font-medium text-foreground">
                Manual contact via {m.method} · {formatRelativeTime(m.at)}
              </p>
              <p className="text-muted-foreground">{m.summary}</p>
            </li>
          ))}
        </ul>
      )}

      {canSchedule && (
        <div className="rounded-md border border-border bg-muted/30 p-2">
          <p className="mb-1 flex items-center gap-1 text-xs font-medium text-foreground">
            <CalendarClock aria-hidden className="size-3.5" /> Schedule reminder
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="datetime-local"
              aria-label="When"
              value={when}
              onChange={(e) => setWhen(e.target.value)}
              className="rounded border border-border bg-background px-1.5 py-1 text-xs"
            />
            <input
              type="text"
              placeholder="Reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="min-w-40 flex-1 rounded border border-border bg-background px-2 py-1 text-xs"
            />
            <button
              type="button"
              disabled={!when}
              onClick={() => {
                onSchedule(new Date(when).toISOString(), reason || "Reminder");
                setWhen("");
                setReason("");
              }}
              className="inline-flex items-center gap-1 rounded-md border border-border bg-foreground px-2 py-1 text-xs font-medium text-background disabled:opacity-50"
            >
              <BellRing aria-hidden className="size-3" /> Schedule
            </button>
          </div>
        </div>
      )}

      {canLog && (
        <div className="rounded-md border border-border bg-muted/30 p-2">
          <p className="mb-1 flex items-center gap-1 text-xs font-medium text-foreground">
            <PhoneCall aria-hidden className="size-3.5" /> Log manual contact
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={manualMethod}
              onChange={(e) => setManualMethod(e.target.value as typeof manualMethod)}
              className="rounded border border-border bg-background px-1.5 py-1 text-xs"
            >
              <option value="phone">Phone</option>
              <option value="in_person">In person</option>
              <option value="chat">Chat</option>
              <option value="other">Other</option>
            </select>
            <input
              type="text"
              placeholder="Summary"
              value={manualSummary}
              onChange={(e) => setManualSummary(e.target.value)}
              className="min-w-40 flex-1 rounded border border-border bg-background px-2 py-1 text-xs"
            />
            <button
              type="button"
              disabled={!manualSummary.trim()}
              onClick={() => {
                onLogManual(manualMethod, manualSummary.trim());
                setManualSummary("");
              }}
              className="rounded-md border border-border px-2 py-1 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-50"
            >
              Log
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------
// Failures
// ---------------------------------------------------------------------
function FailureSection({
  comm,
  canReview,
  onAck,
  acks,
}: {
  comm: Communication;
  canReview: boolean;
  onAck: (id: string, resolution: string) => void;
  acks: ReturnType<ReturnType<typeof useCommunicationsSession>["getFailureAcks"]>;
}) {
  const [resolution, setResolution] = useState<Record<string, string>>({});
  return (
    <ul className="divide-y divide-border">
      {comm.failures.map((f) => {
        const acked = acks.find((a) => a.failureId === f.id);
        return (
          <li key={f.id} className="py-3">
            <p className="flex items-center gap-1 text-sm font-medium text-foreground">
              <MailWarning aria-hidden className="size-4 text-rose-500" />{" "}
              {FAILURE_REASON_LABEL[f.reason]}
            </p>
            <p className="text-xs text-muted-foreground">{f.detail}</p>
            <p className="mt-1 text-xs">
              <span className="text-muted-foreground">Recommended: </span>
              <span className="text-foreground">{FAILURE_RECOMMENDED_ACTION[f.reason]}</span>
            </p>
            {acked ? (
              <p className="mt-1 text-xs text-emerald-700 dark:text-emerald-400">
                Reviewed by {acked.actor}: {acked.resolution}
              </p>
            ) : canReview ? (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <input
                  type="text"
                  placeholder="Resolution note"
                  value={resolution[f.id] ?? ""}
                  onChange={(e) => setResolution({ ...resolution, [f.id]: e.target.value })}
                  className="min-w-40 flex-1 rounded border border-border bg-background px-2 py-1 text-xs"
                />
                <button
                  type="button"
                  disabled={!resolution[f.id]?.trim()}
                  onClick={() => {
                    onAck(f.id, resolution[f.id]!.trim());
                    setResolution({ ...resolution, [f.id]: "" });
                  }}
                  className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-50"
                >
                  <CheckCircle2 aria-hidden className="size-3" /> Mark reviewed
                </button>
              </div>
            ) : null}
          </li>
        );
      })}
      {comm.failures.length === 0 && (
        <li className="py-2 text-xs text-muted-foreground">No failures recorded.</li>
      )}
    </ul>
  );
}

// ---------------------------------------------------------------------
// Notes
// ---------------------------------------------------------------------
function NotesSection({
  notes,
  canAdd,
  onAdd,
}: {
  notes: Communication["internalNotes"];
  canAdd: boolean;
  onAdd: (body: string, category: "operational" | "risk" | "follow_up" | "other") => void;
}) {
  const [body, setBody] = useState("");
  const [category, setCategory] = useState<"operational" | "risk" | "follow_up" | "other">(
    "operational",
  );
  return (
    <div className="space-y-3">
      <div className="rounded-md border border-dashed border-border bg-muted/30 p-2 text-[11px] text-muted-foreground">
        Internal · Session-only · Not visible to candidate
      </div>
      {notes.length === 0 ? (
        <p className="text-xs text-muted-foreground">No notes yet.</p>
      ) : (
        <ul className="divide-y divide-border">
          {notes.map((n) => (
            <li key={n.id} className="py-2 text-xs">
              <p className="text-foreground">{n.body}</p>
              <p className="mt-0.5 text-muted-foreground">
                {n.actor} · {n.actorRole} · {formatRelativeTime(n.at)}
                {"sessionOnly" in n && n.sessionOnly ? (
                  <span className="ml-1 rounded bg-sky-50 px-1 text-[10px] font-semibold text-sky-900 ring-1 ring-inset ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200">
                    Session
                  </span>
                ) : null}
              </p>
            </li>
          ))}
        </ul>
      )}
      {canAdd && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <label className="text-xs text-muted-foreground">Category</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as typeof category)}
              className="rounded border border-border bg-background px-1.5 py-1 text-xs"
            >
              <option value="operational">Operational</option>
              <option value="risk">Risk</option>
              <option value="follow_up">Follow-up</option>
              <option value="other">Other</option>
            </select>
          </div>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={2}
            placeholder="Add an internal note…"
            className="w-full rounded border border-border bg-background p-2 text-xs"
          />
          <div className="flex justify-end">
            <button
              type="button"
              disabled={!body.trim()}
              onClick={() => {
                onAdd(body.trim(), category);
                setBody("");
              }}
              className="inline-flex items-center gap-1 rounded-md border border-border bg-foreground px-2 py-1 text-xs font-medium text-background disabled:opacity-50"
            >
              <MessageSquare aria-hidden className="size-3" /> Add note
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------
// Session activity summary
// ---------------------------------------------------------------------
function SessionActivity({
  comm,
  manualContacts,
}: {
  comm: Communication;
  manualContacts: ReturnType<ReturnType<typeof useCommunicationsSession>["getManualContacts"]>;
}) {
  const items: { id: string; at: string; label: string }[] = [];
  for (const n of comm.internalNotes)
    if ("sessionOnly" in n && n.sessionOnly)
      items.push({ id: n.id, at: n.at, label: `Note added: ${n.body.slice(0, 40)}` });
  for (const f of comm.followUps)
    if (f.sessionOnly) items.push({ id: f.id, at: f.scheduledAt, label: `Reminder scheduled` });
  for (const m of manualContacts)
    items.push({ id: m.id, at: m.at, label: `Manual contact via ${m.method}` });
  items.sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());
  if (items.length === 0)
    return <p className="text-xs text-muted-foreground">No session activity yet.</p>;
  return (
    <ul className="space-y-1.5 text-xs">
      {items.map((i) => (
        <li key={i.id} className="flex items-start justify-between gap-2">
          <span className="text-foreground">{i.label}</span>
          <span className="text-muted-foreground">{formatRelativeTime(i.at)}</span>
        </li>
      ))}
    </ul>
  );
}
