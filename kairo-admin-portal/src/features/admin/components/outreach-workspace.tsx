/**
 * OutreachWorkspace — the outreach preparation, dispatch simulation,
 * delivery simulator, employer-response recording and failed-outreach
 * resolution surface for a single case.
 *
 * Everything is session-only. Nothing sends real email.
 */
import { useMemo, useState } from "react";
import { toast } from "sonner";
import {
  AlertCircle,
  CheckCircle2,
  Mail,
  MailWarning,
  Send,
  UserCheck,
  UserPlus,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { WorkspaceSection } from "./workspace-section";
import { EmptyState } from "./states";
import type { VerificationCaseDetail, VerificationContact } from "@/features/admin/data/cases";
import { CONTACT_SOURCE_LABEL, CONTACT_STATE_LABEL } from "@/features/admin/data/cases";
import {
  DELIVERY_STATE_LABEL,
  EMPLOYER_RESPONSE_LABEL,
  FAILED_OUTREACH_REASON_LABEL,
  OUTREACH_TEMPLATES,
  evaluateOutreachReadiness,
  isTerminalDelivery,
  nextDeliveryStates,
  renderTemplatePreview,
  type DeliveryState,
  type EmployerResponseOutcome,
  type FailedOutreachReason,
  type OutreachTemplate,
  type OutreachTemplateId,
} from "@/features/admin/workflow/outreach";
import type { UseOutreachSessionResult } from "@/features/admin/workflow/use-outreach-session";
import type { WorkflowActor } from "@/features/admin/workflow/types";
import { formatRelativeTime } from "@/features/admin/lib/format";
import { ContactReviewDialog } from "./contact-review-dialog";

const IS_DEV = import.meta.env.DEV;

interface Props {
  detail: VerificationCaseDetail;
  outreach: UseOutreachSessionResult;
  actor: WorkflowActor;
  acknowledgedFlagIds: Set<string>;
}

export function OutreachWorkspace({ detail, outreach, actor, acknowledgedFlagIds }: Props) {
  const [dialogMode, setDialogMode] = useState<
    { kind: "review"; contact: VerificationContact } | { kind: "add"; organization: string } | null
  >(null);

  // Combine mock contacts with any session-added contacts.
  const combinedContacts: VerificationContact[] = useMemo(
    () => [...detail.contacts, ...outreach.sessionAddedContacts],
    [detail.contacts, outreach.sessionAddedContacts],
  );

  const readiness = useMemo(
    () =>
      evaluateOutreachReadiness(detail, {
        actor,
        sessionApprovedContactIds: outreach.sessionApprovedContactIds,
        sessionRejectedContactIds: outreach.sessionRejectedContactIds,
        acknowledgedFlagIds,
        orgResolvedInSession: outreach.orgResolvedInSession,
      }),
    [
      detail,
      actor,
      outreach.sessionApprovedContactIds,
      outreach.sessionRejectedContactIds,
      outreach.orgResolvedInSession,
      acknowledgedFlagIds,
    ],
  );

  return (
    <WorkspaceSection
      id="outreach"
      title="Outreach & communications"
      description="Prepare simulated outreach and record delivery events. No real email is sent from this workspace."
      action={
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium",
            readiness.ready
              ? "bg-emerald-50 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200"
              : "bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200",
          )}
        >
          {readiness.ready ? "Outreach ready" : "Outreach not ready"}
        </span>
      }
    >
      <div className="space-y-5">
        <ReadinessSummary readiness={readiness} />
        <ContactDirectory
          contacts={combinedContacts}
          outreach={outreach}
          onReview={(c) => setDialogMode({ kind: "review", contact: c })}
          onAdd={() =>
            setDialogMode({ kind: "add", organization: detail.summary.organizationName })
          }
        />
        <OutreachPreparation
          detail={detail}
          contacts={combinedContacts}
          outreach={outreach}
          readiness={readiness}
        />
        <AttemptsList detail={detail} outreach={outreach} contacts={combinedContacts} />
      </div>

      <ContactReviewDialog
        open={dialogMode !== null}
        onOpenChange={(v) => !v && setDialogMode(null)}
        mode={dialogMode}
        outreach={outreach}
      />
    </WorkspaceSection>
  );
}

// ---------------------------------------------------------------------
// Readiness summary
// ---------------------------------------------------------------------

function ReadinessSummary({
  readiness,
}: {
  readiness: ReturnType<typeof evaluateOutreachReadiness>;
}) {
  if (readiness.ready && readiness.warnings.length === 0) {
    return (
      <div className="flex items-start gap-2 rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-[11px] text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200">
        <CheckCircle2 aria-hidden className="mt-0.5 size-3.5 shrink-0" />
        <span>
          All outreach preconditions met. Approved contact:{" "}
          <strong>{readiness.approvedContact?.name}</strong>.
        </span>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {readiness.blockers.length > 0 ? (
        <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-[11px] text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          <div className="mb-1 flex items-center gap-1.5 font-semibold">
            <AlertCircle aria-hidden className="size-3.5" />
            Not ready for outreach
          </div>
          <ul className="ml-5 list-disc space-y-0.5">
            {readiness.blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {readiness.warnings.length > 0 ? (
        <div className="rounded-md border border-border bg-muted/40 px-3 py-2 text-[11px] text-foreground">
          <div className="mb-1 font-semibold">Warnings</div>
          <ul className="ml-5 list-disc space-y-0.5 text-muted-foreground">
            {readiness.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------
// Contact directory
// ---------------------------------------------------------------------

function ContactDirectory({
  contacts,
  outreach,
  onReview,
  onAdd,
}: {
  contacts: VerificationContact[];
  outreach: UseOutreachSessionResult;
  onReview: (c: VerificationContact) => void;
  onAdd: () => void;
}) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Contact directory
        </h3>
        <button
          type="button"
          onClick={onAdd}
          className="inline-flex h-7 items-center gap-1 rounded-md border border-border bg-background px-2 text-[11px] font-medium text-foreground hover:bg-accent"
        >
          <UserPlus aria-hidden className="size-3" />
          Add contact
        </button>
      </div>
      {contacts.length === 0 ? (
        <EmptyState title="No contacts on file" description="Add one to enable outreach." />
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border">
          {contacts.map((c) => {
            const isSessionApproved = outreach.sessionApprovedContactIds.has(c.id);
            const isSessionRejected = outreach.sessionRejectedContactIds.has(c.id);
            const effectiveState = isSessionRejected
              ? "rejected"
              : isSessionApproved
                ? "approved"
                : c.state;
            return (
              <li
                key={c.id}
                className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium text-foreground">{c.name}</span>
                    <span className="text-muted-foreground">· {c.role}</span>
                    {outreach.sessionAddedContacts.some((x) => x.id === c.id) ? (
                      <span className="rounded bg-sky-50 px-1.5 py-0.5 text-[10px] font-medium text-sky-800 ring-1 ring-inset ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:ring-sky-900/60">
                        Session
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                    {c.emailMasked}
                    {c.phoneMasked ? ` · ${c.phoneMasked}` : ""}
                  </div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">
                    {CONTACT_SOURCE_LABEL[c.source]} · Confidence {Math.round(c.confidence * 100)}%
                    {c.bounceCount > 0
                      ? ` · ${c.bounceCount} bounce${c.bounceCount === 1 ? "" : "s"}`
                      : ""}
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  <StateChip state={effectiveState} />
                  <button
                    type="button"
                    onClick={() => onReview(c)}
                    className="inline-flex h-7 items-center gap-1 rounded-md border border-border bg-background px-2 text-[11px] font-medium text-foreground hover:bg-accent"
                  >
                    <UserCheck aria-hidden className="size-3" />
                    Review
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function StateChip({ state }: { state: string }) {
  const map: Record<string, string> = {
    approved:
      "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-900/60",
    bounced:
      "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60",
    rejected:
      "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60",
    unverified:
      "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60",
    needs_review:
      "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60",
    previously_successful:
      "bg-sky-50 text-sky-900 ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:ring-sky-900/60",
    inactive: "bg-muted text-muted-foreground ring-border",
  };
  const label = CONTACT_STATE_LABEL[state as keyof typeof CONTACT_STATE_LABEL] ?? state;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset",
        map[state] ?? "bg-muted text-muted-foreground ring-border",
      )}
    >
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------
// Preparation (prepare + simulated dispatch)
// ---------------------------------------------------------------------

function OutreachPreparation({
  detail,
  contacts,
  outreach,
  readiness,
}: {
  detail: VerificationCaseDetail;
  contacts: VerificationContact[];
  outreach: UseOutreachSessionResult;
  readiness: ReturnType<typeof evaluateOutreachReadiness>;
}) {
  const eligibleContacts = contacts.filter(
    (c) =>
      (outreach.sessionApprovedContactIds.has(c.id) || c.internalApprovalStatus === "approved") &&
      !outreach.sessionRejectedContactIds.has(c.id) &&
      c.state !== "bounced" &&
      c.state !== "rejected" &&
      c.state !== "inactive",
  );

  const [contactId, setContactId] = useState<string>(eligibleContacts[0]?.id ?? "");
  const [templateId, setTemplateId] = useState<OutreachTemplateId>(
    "employer_verification_request_v3",
  );

  // Keep contactId valid when the eligible list changes.
  if (contactId && !eligibleContacts.find((c) => c.id === contactId)) {
    if (eligibleContacts[0]) setContactId(eligibleContacts[0].id);
    else if (contactId !== "") setContactId("");
  }

  const template = OUTREACH_TEMPLATES.find((t) => t.id === templateId)!;
  const contact = eligibleContacts.find((c) => c.id === contactId);

  const preview = renderTemplatePreview(template, {
    candidateName: detail.candidate.name,
    contactName: contact?.name ?? "there",
    organizationName: detail.summary.organizationName,
    credentialName: detail.summary.roleOrProgram,
  });

  const canPrepare = readiness.ready && Boolean(contact);

  function handlePrepareAndSend() {
    if (!contact) return;
    const attempt = outreach.prepareAttempt({
      contactId: contact.id,
      contactName: contact.name,
      templateId,
      subject: preview.subject,
      bodyPreview: preview.body,
    });
    outreach.simulateNextEvent(attempt.id, "sent");
    toast("Simulated sent", {
      description: "No real email dispatched. Advance delivery events below.",
    });
  }

  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Prepare outreach
      </h3>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <SelectField
          label="Recipient"
          value={contactId}
          onChange={setContactId}
          disabled={eligibleContacts.length === 0}
          options={
            eligibleContacts.length === 0
              ? [{ value: "", label: "No approved contact available" }]
              : eligibleContacts.map((c) => ({
                  value: c.id,
                  label: `${c.name} — ${c.emailMasked}`,
                }))
          }
        />
        <SelectField
          label="Template"
          value={templateId}
          onChange={(v) => setTemplateId(v as OutreachTemplateId)}
          options={OUTREACH_TEMPLATES.map((t: OutreachTemplate) => ({
            value: t.id,
            label: t.name,
          }))}
        />
      </div>
      <div className="mt-3 rounded-md border border-border bg-muted/30 p-3">
        <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold text-foreground">
          <Mail aria-hidden className="size-3.5" />
          Message preview
        </div>
        <div className="text-[11px] text-muted-foreground">
          <div>
            <span className="text-foreground">Subject:</span> {preview.subject}
          </div>
          <pre className="mt-1 whitespace-pre-wrap font-sans text-[11px] text-foreground">
            {preview.body}
          </pre>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={!canPrepare}
          onClick={handlePrepareAndSend}
          className="inline-flex h-8 items-center gap-1.5 rounded-md bg-foreground px-3 text-xs font-medium text-background hover:bg-foreground/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Send aria-hidden className="size-3.5" />
          Prepare and simulate send
        </button>
        <span className="text-[11px] text-muted-foreground">
          Dispatch is simulated. No real email is sent.
        </span>
      </div>
    </div>
  );
}

function SelectField({
  label,
  value,
  onChange,
  options,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  disabled?: boolean;
}) {
  return (
    <div>
      <label className="block text-[11px] font-medium text-foreground">{label}</label>
      <select
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

// ---------------------------------------------------------------------
// Attempts list (delivery simulator + response + failure)
// ---------------------------------------------------------------------

function AttemptsList({
  detail,
  outreach,
  contacts,
}: {
  detail: VerificationCaseDetail;
  outreach: UseOutreachSessionResult;
  contacts: VerificationContact[];
}) {
  const attempts = outreach.outreachAttempts;
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Simulated outreach attempts
      </h3>
      {attempts.length === 0 && detail.communications.length === 0 ? (
        <EmptyState title="No outreach yet" description="Prepare an outreach above to begin." />
      ) : (
        <ol className="space-y-3">
          {attempts.map((a) => (
            <AttemptCard key={a.id} attempt={a} outreach={outreach} contacts={contacts} />
          ))}
        </ol>
      )}
      {detail.communications.length > 0 ? (
        <div className="mt-4">
          <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Historical outreach (mock)
          </h4>
          <ul className="divide-y divide-border rounded-md border border-border text-[11px]">
            {detail.communications.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-2 px-3 py-1.5">
                <span className="text-foreground">
                  {c.template} — {c.recipientDisplay}
                </span>
                <span className="text-muted-foreground">
                  {c.state} · {formatRelativeTime(c.at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function AttemptCard({
  attempt,
  outreach,
  contacts,
}: {
  attempt: ReturnType<UseOutreachSessionResult["prepareAttempt"]>;
  outreach: UseOutreachSessionResult;
  contacts: VerificationContact[];
}) {
  const last = attempt.events[attempt.events.length - 1];
  const nextStates = nextDeliveryStates(last.state);
  const isTerminal = isTerminalDelivery(last.state) || attempt.failedResolution;

  const [showResponse, setShowResponse] = useState(false);
  const [showFail, setShowFail] = useState(false);

  return (
    <li className="rounded-md border border-border bg-card p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5 text-xs font-medium text-foreground">
            <Zap aria-hidden className="size-3.5 text-muted-foreground" />
            {attempt.contactName}
            <span className="rounded bg-sky-50 px-1.5 py-0.5 text-[10px] font-medium text-sky-800 ring-1 ring-inset ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:ring-sky-900/60">
              Session
            </span>
            {attempt.followUpOfId ? (
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                Follow-up
              </span>
            ) : null}
          </div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">
            {attempt.subject} · {attempt.templateId}
          </div>
        </div>
        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-foreground">
          {DELIVERY_STATE_LABEL[last.state]}
        </span>
      </div>

      <ol className="mt-3 space-y-1.5 border-l border-border pl-3 text-[11px]">
        {attempt.events.map((e) => (
          <li key={e.id} className="text-muted-foreground">
            <span className="text-foreground">{DELIVERY_STATE_LABEL[e.state]}</span> ·{" "}
            {formatRelativeTime(e.at)} · by {e.actorName}
            {e.note ? ` — ${e.note}` : ""}
          </li>
        ))}
      </ol>

      {attempt.employerResponse ? (
        <div className="mt-2 rounded-md border border-emerald-300 bg-emerald-50 px-2.5 py-1.5 text-[11px] text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200">
          <div className="font-semibold">
            Employer response — {EMPLOYER_RESPONSE_LABEL[attempt.employerResponse.outcome]}
          </div>
          <div className="mt-0.5">{attempt.employerResponse.summary}</div>
        </div>
      ) : null}

      {attempt.failedResolution ? (
        <div className="mt-2 rounded-md border border-rose-300 bg-rose-50 px-2.5 py-1.5 text-[11px] text-rose-900 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-200">
          <div className="font-semibold">
            Marked failed — {FAILED_OUTREACH_REASON_LABEL[attempt.failedResolution.reason]}
          </div>
          <div className="mt-0.5">{attempt.failedResolution.narrative}</div>
          {attempt.failedResolution.alternativeContactId ? (
            <div className="mt-0.5">
              Alternative selected:{" "}
              {contacts.find((c) => c.id === attempt.failedResolution!.alternativeContactId)
                ?.name ?? attempt.failedResolution.alternativeContactId}
            </div>
          ) : null}
        </div>
      ) : null}

      {!isTerminal && (nextStates.length > 0 || IS_DEV) ? (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {IS_DEV ? (
            <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-900 ring-1 ring-inset ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60">
              Dev simulator
            </span>
          ) : null}
          {nextStates.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => outreach.simulateNextEvent(attempt.id, s)}
              className="inline-flex h-7 items-center rounded-md border border-border bg-background px-2 text-[11px] text-foreground hover:bg-accent"
            >
              Simulate {DELIVERY_STATE_LABEL[s]}
            </button>
          ))}
        </div>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {!attempt.employerResponse ? (
          <button
            type="button"
            onClick={() => setShowResponse((v) => !v)}
            className="inline-flex h-7 items-center rounded-md border border-border bg-background px-2 text-[11px] text-foreground hover:bg-accent"
          >
            Record employer response
          </button>
        ) : null}
        {!attempt.failedResolution ? (
          <button
            type="button"
            onClick={() => setShowFail((v) => !v)}
            className="inline-flex h-7 items-center rounded-md border border-rose-300 bg-background px-2 text-[11px] text-rose-800 hover:bg-rose-50 dark:border-rose-800 dark:text-rose-200 dark:hover:bg-rose-950/40"
          >
            <MailWarning aria-hidden className="mr-1 size-3" />
            Mark outreach failed
          </button>
        ) : null}
        <button
          type="button"
          onClick={() => {
            outreach.prepareAttempt({
              contactId: attempt.contactId,
              contactName: attempt.contactName,
              templateId: "employer_verification_follow_up_v1",
              subject: `Reminder — ${attempt.subject}`,
              bodyPreview: attempt.bodyPreview,
              followUpOfId: attempt.id,
            });
            toast("Follow-up prepared", { description: "Session-only." });
          }}
          className="inline-flex h-7 items-center rounded-md border border-border bg-background px-2 text-[11px] text-foreground hover:bg-accent"
        >
          Schedule follow-up
        </button>
      </div>

      {showResponse ? (
        <EmployerResponseForm
          onSubmit={(payload) => {
            outreach.recordEmployerResponse(attempt.id, payload);
            setShowResponse(false);
          }}
          onCancel={() => setShowResponse(false)}
        />
      ) : null}
      {showFail ? (
        <FailedOutreachForm
          contacts={contacts.filter((c) => c.id !== attempt.contactId)}
          onSubmit={(payload) => {
            outreach.markFailedOutreach(attempt.id, payload);
            setShowFail(false);
          }}
          onCancel={() => setShowFail(false)}
        />
      ) : null}
    </li>
  );
}

// ---------- Inline forms ----------

function EmployerResponseForm({
  onSubmit,
  onCancel,
}: {
  onSubmit: (payload: { outcome: EmployerResponseOutcome; summary: string }) => void;
  onCancel: () => void;
}) {
  const [outcome, setOutcome] = useState<EmployerResponseOutcome>("confirmed");
  const [summary, setSummary] = useState("");
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="mt-3 rounded-md border border-border bg-background p-3">
      <div className="mb-2 text-[11px] font-semibold text-foreground">Record employer response</div>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        <SelectField
          label="Outcome"
          value={outcome}
          onChange={(v) => setOutcome(v as EmployerResponseOutcome)}
          options={Object.entries(EMPLOYER_RESPONSE_LABEL).map(([k, v]) => ({
            value: k,
            label: v,
          }))}
        />
      </div>
      <div className="mt-2">
        <label className="block text-[11px] font-medium text-foreground">Summary</label>
        <textarea
          rows={2}
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-[11px] text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          placeholder="Short description of the response."
        />
        {err ? <p className="mt-1 text-[11px] text-destructive">{err}</p> : null}
      </div>
      <div className="mt-2 flex justify-end gap-1.5">
        <button
          type="button"
          onClick={onCancel}
          className="h-7 rounded-md border border-border bg-background px-2 text-[11px] text-foreground hover:bg-accent"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={() => {
            if (summary.trim().length < 10) {
              setErr("Provide a summary of at least 10 characters.");
              return;
            }
            onSubmit({ outcome, summary: summary.trim() });
          }}
          className="h-7 rounded-md bg-foreground px-2 text-[11px] font-medium text-background hover:bg-foreground/90"
        >
          Record response
        </button>
      </div>
    </div>
  );
}

function FailedOutreachForm({
  contacts,
  onSubmit,
  onCancel,
}: {
  contacts: VerificationContact[];
  onSubmit: (payload: {
    reason: FailedOutreachReason;
    narrative: string;
    alternativeContactId?: string;
  }) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState<FailedOutreachReason>("hard_bounce");
  const [narrative, setNarrative] = useState("");
  const [alt, setAlt] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="mt-3 rounded-md border border-rose-300 bg-rose-50/60 p-3 dark:border-rose-800 dark:bg-rose-950/20">
      <div className="mb-2 text-[11px] font-semibold text-foreground">Mark outreach as failed</div>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        <SelectField
          label="Reason"
          value={reason}
          onChange={(v) => setReason(v as FailedOutreachReason)}
          options={Object.entries(FAILED_OUTREACH_REASON_LABEL).map(([k, v]) => ({
            value: k,
            label: v,
          }))}
        />
        <SelectField
          label="Alternative contact (optional)"
          value={alt}
          onChange={setAlt}
          options={[
            { value: "", label: "None" },
            ...contacts.map((c) => ({ value: c.id, label: `${c.name} — ${c.emailMasked}` })),
          ]}
        />
      </div>
      <div className="mt-2">
        <label className="block text-[11px] font-medium text-foreground">Narrative</label>
        <textarea
          rows={2}
          value={narrative}
          onChange={(e) => setNarrative(e.target.value)}
          className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-[11px] text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          placeholder="What happened? What did you try?"
        />
        {err ? <p className="mt-1 text-[11px] text-destructive">{err}</p> : null}
      </div>
      <div className="mt-2 flex justify-end gap-1.5">
        <button
          type="button"
          onClick={onCancel}
          className="h-7 rounded-md border border-border bg-background px-2 text-[11px] text-foreground hover:bg-accent"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={() => {
            if (narrative.trim().length < 10) {
              setErr("Provide a narrative of at least 10 characters.");
              return;
            }
            onSubmit({
              reason,
              narrative: narrative.trim(),
              alternativeContactId: alt || undefined,
            });
          }}
          className="h-7 rounded-md bg-rose-600 px-2 text-[11px] font-medium text-white hover:bg-rose-700"
        >
          Mark failed
        </button>
      </div>
    </div>
  );
}
