import { useMemo, useState } from "react";
import { createFileRoute, Link, notFound, useRouter } from "@tanstack/react-router";
import { toast } from "sonner";
import {
  ArrowLeft,
  ChevronRight,
  Clock,
  ExternalLink,
  Flag,
  MailWarning,
  Shield,
  StickyNote,
  UserPlus,
  ArrowUp,
  Wrench,
  CheckCircle2,
  AlertTriangle,
  Building2,
  Users,
  X,
  MessageSquare,
  Info,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { OutreachWorkspace } from "@/features/admin/components/outreach-workspace";
import { OrganizationResolutionPanel } from "@/features/admin/components/organization-resolution-panel";
import { useOutreachSession } from "@/features/admin/workflow/use-outreach-session";

import { StatusBadge } from "@/features/admin/components/status-badge";
import { PriorityBadge } from "@/features/admin/components/priority-badge";
import { WorkspaceSection, SourceBadge } from "@/features/admin/components/workspace-section";
import { EvidencePanel } from "@/features/admin/components/evidence-panel";
import { CaseTimeline } from "@/features/admin/components/case-timeline";
import { InternalNotesPanel } from "@/features/admin/components/internal-notes-panel";
import { EmptyState, ErrorState, LoadingSkeleton } from "@/features/admin/components/states";
import {
  useAdminAccess,
  setDevAdminRole,
  getDevAdminRole,
} from "@/features/admin/auth/admin-access";
import { formatAge, formatRelativeTime } from "@/features/admin/lib/format";
import {
  ALL_ASSIGNEES,
  ATTENTION_FLAG_LABEL,
  ORGANIZATION_STATUS_LABEL,
  SLA_LABEL,
  VERIFICATION_TYPE_LABEL,
  type Assignee,
} from "@/features/admin/data/verifications";
import {
  COMMUNICATION_STATE_LABEL,
  CORRECTION_STATE_LABEL,
  CONTACT_SOURCE_LABEL,
  CONTACT_STATE_LABEL,
  PRIORITY_LABEL,
  getVerificationCaseDetail,
  type AttentionFlagRecord,
  type OrganizationSuggestion,
  type VerificationCaseDetail,
} from "@/features/admin/data/cases";
import type { Priority } from "@/features/admin/data/types";
import {
  useVerificationWorkflow,
  type UseVerificationWorkflowResult,
} from "@/features/admin/workflow/use-verification-workflow";
import {
  FIELD_CONFIRMATION_LABEL,
  type WorkflowAction,
  type AdminRoleKey,
} from "@/features/admin/workflow/types";
import { ROLE_LABEL } from "@/features/admin/workflow/permissions";
import {
  CorrectionDialog,
  OutreachDialog,
  VerifyDialog,
  RejectDialog,
  UnableDialog,
  ClarificationRequestDialog,
  ClarificationResponseDialog,
} from "@/features/admin/components/workflow-dialogs";
import { UnsavedChangesDialog } from "@/features/admin/components/unsaved-changes-dialog";

export const Route = createFileRoute("/admin/verifications/$caseId")({
  head: () => ({
    meta: [
      { title: "Verification case — Kairo Admin" },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  loader: ({ params }) => {
    const detail = getVerificationCaseDetail(params.caseId);
    if (!detail) throw notFound();
    return { detail };
  },
  component: CaseWorkspace,
  pendingComponent: () => (
    <div className="mx-auto max-w-5xl">
      <LoadingSkeleton rows={8} />
    </div>
  ),
  errorComponent: CaseWorkspaceErrorBoundary,
  notFoundComponent: CaseWorkspaceNotFound,
});

function CaseWorkspaceErrorBoundary({ error, reset }: { error: Error; reset: () => void }) {
  const router = useRouter();

  return (
    <div className="mx-auto max-w-2xl">
      <ErrorState
        title="Case failed to load"
        description={error.message}
        action={
          <button
            onClick={() => {
              router.invalidate();
              reset();
            }}
            className="inline-flex h-8 items-center rounded-md bg-foreground px-3 text-xs font-medium text-background hover:bg-foreground/90"
          >
            Try again
          </button>
        }
      />
    </div>
  );
}

function CaseWorkspaceNotFound() {
  const { caseId } = Route.useParams();

  return (
    <div className="mx-auto max-w-2xl">
      <EmptyState
        title={`Case ${caseId} not found`}
        description="The case may have been merged, removed, or the identifier is incorrect."
        action={
          <Link
            to="/admin/verifications"
            search={{ view: "all-active" }}
            className="inline-flex h-8 items-center rounded-md bg-foreground px-3 text-xs font-medium text-background hover:bg-foreground/90"
          >
            Back to Verifications
          </Link>
        }
      />
    </div>
  );
}

function CaseWorkspace() {
  const { detail } = Route.useLoaderData() as { detail: VerificationCaseDetail };
  const { admin } = useAdminAccess();

  const actor = useMemo(
    () => ({
      name: admin?.name ?? "Reviewer",
      role: admin?.role ?? "Reviewer",
      roleKey: admin?.roleKey ?? ("reviewer" as const),
      permissions: admin?.permissions ?? [],
    }),
    [admin],
  );

  const workflow = useVerificationWorkflow(detail, actor);
  const outreach = useOutreachSession(detail, actor);

  const [dialog, setDialog] = useState<WorkflowAction | null>(null);
  const [pendingLeaveHref, setPendingLeaveHref] = useState<null | (() => void)>(null);

  const anySessionChanges = workflow.hasSessionChanges || outreach.hasSessionChanges;

  function handleAssign(next: Assignee) {
    if (next === workflow.assignedReviewer) return;
    workflow.setAssignedReviewer(next);
    toast(`Assigned to ${next}`, {
      description: "Session-only change. Not persisted to the backend.",
    });
  }
  function handlePriority(next: Priority) {
    if (next === workflow.priority) return;
    workflow.setPriority(next);
    toast(`Priority set to ${PRIORITY_LABEL[next]}`, {
      description: "Session-only change. Not persisted to the backend.",
    });
  }
  function handleAckFlag(f: AttentionFlagRecord) {
    if (workflow.acknowledgedFlagIds.has(f.id)) return;
    workflow.acknowledgeFlag(f.id, f.label);
    toast(`Flag acknowledged: ${f.label}`, {
      description: "Session-only change. Not persisted to the backend.",
    });
  }

  const timeline = useMemo(
    () => [...detail.timeline, ...workflow.extraTimelineEvents, ...outreach.extraTimelineEvents],
    [detail.timeline, workflow.extraTimelineEvents, outreach.extraTimelineEvents],
  );

  const ageHours = Math.max(
    0,
    Math.round((Date.now() - new Date(detail.summary.submittedAt).getTime()) / 3_600_000),
  );

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-4">
      {/* Breadcrumbs */}
      <nav
        aria-label="Breadcrumb"
        className="flex items-center gap-1.5 text-xs text-muted-foreground"
      >
        <Link
          to="/admin/verifications"
          search={{ view: "all-active" }}
          className="inline-flex items-center gap-1 hover:text-foreground"
          onClick={(e) => {
            if (anySessionChanges) {
              e.preventDefault();
              const target = e.currentTarget as HTMLAnchorElement;
              const href = target.getAttribute("href") ?? "/admin/verifications?view=all-active";
              setPendingLeaveHref(() => () => {
                window.location.assign(href);
              });
            }
          }}
        >
          <ArrowLeft aria-hidden className="size-3" />
          Verifications
        </Link>
        <ChevronRight aria-hidden className="size-3" />
        <span className="font-mono text-foreground">{detail.summary.reference}</span>
      </nav>

      {anySessionChanges ? (
        <div
          role="status"
          className="flex items-start gap-2 rounded-md border border-sky-300 bg-sky-50 px-3 py-2 text-[11px] text-sky-900 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-200"
        >
          <Info aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          <span>
            <strong>Session-only workspace.</strong> Changes on this page are visible here for the
            current browser session. They are not saved to the backend and will reset on reload or
            when leaving the case.
          </span>
        </div>
      ) : null}

      {/* Sticky header */}
      <header className="sticky top-14 z-20 -mx-3 border-b border-border bg-background/95 px-3 py-3 backdrop-blur sm:-mx-6 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] font-medium text-muted-foreground">
                {detail.summary.reference}
              </span>
              <StatusBadge status={workflow.currentStatus} />
              <PriorityBadge priority={workflow.priority} />
              <SlaBadge state={detail.summary.slaState} />
              {workflow.currentStatus !== detail.summary.status ? (
                <span className="rounded bg-sky-50 px-1.5 py-0.5 text-[10px] font-medium text-sky-800 ring-1 ring-inset ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:ring-sky-900/60">
                  Session status
                </span>
              ) : null}
            </div>
            <h1 className="mt-1.5 truncate text-lg font-semibold tracking-tight text-foreground">
              {detail.candidate.name}
            </h1>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {VERIFICATION_TYPE_LABEL[detail.summary.verificationType]} ·{" "}
              {detail.summary.organizationName} · {detail.summary.roleOrProgram}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Menu
              label="Assign"
              icon={UserPlus}
              current={workflow.assignedReviewer}
              options={ALL_ASSIGNEES}
              onSelect={(k) => handleAssign(k as Assignee)}
            />
            <Menu
              label="Priority"
              icon={ArrowUp}
              current={PRIORITY_LABEL[workflow.priority]}
              options={(["urgent", "high", "normal", "low"] as Priority[]).map((p) => ({
                key: p,
                label: PRIORITY_LABEL[p],
              }))}
              onSelect={(k) => handlePriority(k as Priority)}
            />
            <button
              onClick={() => document.getElementById("internal-note-body")?.focus()}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-2 text-xs text-foreground hover:bg-accent"
            >
              <StickyNote aria-hidden className="size-3.5" />
              Add note
            </button>
            <DevRoleMenu />
          </div>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
          <span>
            <Users aria-hidden className="mr-1 inline size-3" />
            Assigned to <span className="text-foreground">{workflow.assignedReviewer}</span>
          </span>
          <span>
            <Clock aria-hidden className="mr-1 inline size-3" />
            Age {formatAge(ageHours)}
          </span>
          <span>Last updated {formatRelativeTime(detail.summary.updatedAt)}</span>
          {admin ? (
            <span>
              Acting as <span className="text-foreground">{admin.name}</span> · {admin.role}
            </span>
          ) : null}
        </div>
      </header>

      {/* Two-column workspace */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex min-w-0 flex-col gap-4">
          <ClaimSummarySection detail={detail} />
          <WorkspaceSection
            id="evidence"
            title="Evidence"
            description={`${detail.evidence.length} document${detail.evidence.length === 1 ? "" : "s"} attached to this case.`}
          >
            <EvidencePanel items={detail.evidence} />
          </WorkspaceSection>

          <OrganizationResolutionPanel detail={detail} outreach={outreach} />
          <OutreachWorkspace
            detail={detail}
            outreach={outreach}
            actor={actor}
            acknowledgedFlagIds={workflow.acknowledgedFlagIds}
          />

          <CorrectionsSection
            detail={detail}
            workflow={workflow}
            onOpenCorrection={() => setDialog("request_correction")}
          />

          <WorkspaceSection
            id="timeline"
            title="Case timeline"
            description="Append-only history of everything that has happened on this case."
          >
            <CaseTimeline events={timeline} />
          </WorkspaceSection>
        </div>

        {/* Right sidebar */}
        <aside className="flex min-w-0 flex-col gap-4">
          <CaseStatusSidebar detail={detail} workflow={workflow} ageHours={ageHours} />
          {workflow.sessionDecision ? (
            <DecisionSummaryPanel workflow={workflow} detail={detail} />
          ) : null}
          <AttentionFlagsPanel
            flags={detail.flags}
            acknowledged={workflow.acknowledgedFlagIds}
            onAck={handleAckFlag}
          />
          <CandidateSummaryPanel detail={detail} />

          <WorkspaceSection
            id="notes"
            title="Internal notes"
            description="Visible only to Kairo operators."
          >
            <InternalNotesPanel
              notes={workflow.notes}
              onAdd={(body, cat) => {
                workflow.addNote(body, cat);
                toast("Internal note added", {
                  description: "Session-only.",
                });
              }}
              author={admin?.name ?? "Reviewer"}
              role={admin?.role ?? "Reviewer"}
            />
          </WorkspaceSection>
          <DecisionPreparationPanel
            detail={detail}
            workflow={workflow}
            onOpen={(a) => setDialog(a)}
          />
        </aside>
      </div>

      {/* Dialogs */}
      <CorrectionDialog
        open={dialog === "request_correction"}
        onOpenChange={(o) => !o && setDialog(null)}
        detail={detail}
        workflow={workflow}
      />
      <OutreachDialog
        open={dialog === "approve_outreach"}
        onOpenChange={(o) => !o && setDialog(null)}
        detail={detail}
        workflow={workflow}
      />
      <VerifyDialog
        open={dialog === "verify"}
        onOpenChange={(o) => !o && setDialog(null)}
        detail={detail}
        workflow={workflow}
      />
      <RejectDialog
        open={dialog === "reject"}
        onOpenChange={(o) => !o && setDialog(null)}
        detail={detail}
        workflow={workflow}
      />
      <UnableDialog
        open={dialog === "unable_to_verify"}
        onOpenChange={(o) => !o && setDialog(null)}
        detail={detail}
        workflow={workflow}
      />
      <ClarificationRequestDialog
        open={dialog === "record_clarification_request"}
        onOpenChange={(o) => !o && setDialog(null)}
        detail={detail}
        workflow={workflow}
      />
      <ClarificationResponseDialog
        open={dialog === "record_clarification_response"}
        onOpenChange={(o) => !o && setDialog(null)}
        detail={detail}
        workflow={workflow}
      />
      <UnsavedChangesDialog
        open={pendingLeaveHref !== null}
        onOpenChange={(o) => !o && setPendingLeaveHref(null)}
        onConfirm={() => {
          const fn = pendingLeaveHref;
          setPendingLeaveHref(null);
          if (fn) fn();
        }}
      />
    </div>
  );
}

// =====================================================================
// Section components
// =====================================================================

function ClaimSummarySection({ detail }: { detail: VerificationCaseDetail }) {
  return (
    <WorkspaceSection
      id="claim"
      title="Claim summary"
      description={detail.claim.headline}
      action={
        <div className="hidden gap-1.5 sm:flex">
          <SourceBadge source="candidate" />
          <SourceBadge source="kairo_derived" />
          <SourceBadge source="verifier_confirmed" />
        </div>
      }
    >
      <dl className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
        {detail.claim.fields.map((f) => (
          <div key={f.key} className="min-w-0">
            <dt className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {f.label}
            </dt>
            <dd className="mt-0.5 truncate text-sm text-foreground" title={f.value}>
              {f.value}
            </dd>
            <div className="mt-1">
              <SourceBadge source={f.source} />
            </div>
          </div>
        ))}
      </dl>
      <p className="mt-4 text-[11px] text-muted-foreground">
        Fields are labelled by their source. A field is not treated as verified just because it was
        provided.
      </p>
    </WorkspaceSection>
  );
}

function CorrectionsSection({
  detail,

  workflow,
  onOpenCorrection,
}: {
  detail: VerificationCaseDetail;
  workflow: UseVerificationWorkflowResult;
  onOpenCorrection: () => void;
}) {
  const eligibility = workflow.getEligibility("request_correction");
  const disabled = !eligibility.allowed;
  return (
    <WorkspaceSection
      id="corrections"
      title="Corrections & clarifications"
      description="Requests sent to the candidate and their responses."
      action={
        <button
          type="button"
          onClick={onOpenCorrection}
          disabled={disabled}
          title={
            disabled
              ? (eligibility.blockingReasons[0] ?? "Not available")
              : "Request a correction from the candidate."
          }
          className={cn(
            "inline-flex h-7 items-center gap-1 rounded-md border border-border bg-background px-2 text-xs",
            disabled ? "text-muted-foreground opacity-60" : "text-foreground hover:bg-accent",
          )}
        >
          <Wrench aria-hidden className="size-3" />
          Request correction
        </button>
      }
    >
      {detail.corrections.length + workflow.sessionCorrections.length === 0 ? (
        <EmptyState
          title="No corrections requested"
          description="No corrections or clarifications have been issued for this case."
        />
      ) : (
        <ul className="space-y-3">
          {detail.corrections.map((c) => (
            <li key={c.id} className="rounded-md border border-border bg-background p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-xs font-medium text-foreground">
                  {c.requestedBy}
                  <span className="font-normal text-muted-foreground"> requested a correction</span>
                </p>
                <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                  {CORRECTION_STATE_LABEL[c.state]}
                </span>
              </div>
              <p className="mt-1 text-xs text-foreground">{c.reason}</p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Fields: {c.fields.join(", ")} · {formatRelativeTime(c.requestedAt)}
              </p>
              {c.candidateResponse ? (
                <div className="mt-2 rounded bg-muted/60 p-2 text-xs text-foreground">
                  <p className="font-medium">Candidate response</p>
                  <p className="mt-0.5 text-muted-foreground">{c.candidateResponse}</p>
                </div>
              ) : null}
            </li>
          ))}
          {workflow.sessionCorrections.map((c) => (
            <li
              key={c.id}
              className="rounded-md border border-sky-300 bg-sky-50/40 p-3 dark:border-sky-800 dark:bg-sky-950/20"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-xs font-medium text-foreground">
                  {c.actorName}
                  <span className="font-normal text-muted-foreground"> requested a correction</span>
                </p>
                <span className="rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-medium text-sky-800 dark:bg-sky-900/40 dark:text-sky-200">
                  Session-only
                </span>
              </div>
              <p className="mt-1 text-xs text-foreground">{c.reasonLabels.join(", ")}</p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Fields: {c.affectedFieldKeys.join(", ")} · {formatRelativeTime(c.at)}
              </p>
              {c.requestedItems.length > 0 ? (
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  Requested: {c.requestedItems.join(", ")}
                </p>
              ) : null}
              <div className="mt-2 rounded bg-background/60 p-2 text-xs text-foreground">
                <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                  Candidate-facing message
                </p>
                <p className="mt-0.5 whitespace-pre-wrap text-xs">{c.candidateMessage}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </WorkspaceSection>
  );
}

function CaseStatusSidebar({
  detail,
  workflow,
  ageHours,
}: {
  detail: VerificationCaseDetail;
  workflow: UseVerificationWorkflowResult;
  ageHours: number;
}) {
  const statusChanged = workflow.currentStatus !== detail.summary.status;
  return (
    <WorkspaceSection id="status" title="Case status">
      <div className="space-y-2 text-xs">
        <StatusRow label="Status" value={<StatusBadge status={workflow.currentStatus} />} />
        <p className="text-[11px] text-muted-foreground">
          {statusChanged
            ? "Session-only status change on this workspace."
            : detail.statusMeta.description}
        </p>
        <StatusRow
          label="Stage"
          value={<span className="text-foreground">{detail.statusMeta.stage}</span>}
        />
        <StatusRow label="Priority" value={<PriorityBadge priority={workflow.priority} />} />
        <StatusRow
          label="Assigned"
          value={
            <span
              className={cn(
                "text-foreground",
                workflow.assignedReviewer === "Unassigned" && "italic text-muted-foreground",
              )}
            >
              {workflow.assignedReviewer}
            </span>
          }
        />
        <StatusRow
          label="Submitted"
          value={
            <span className="text-foreground">
              {formatRelativeTime(detail.summary.submittedAt)}
            </span>
          }
        />
        <StatusRow
          label="Age"
          value={<span className="text-foreground">{formatAge(ageHours)}</span>}
        />
        <StatusRow
          label="SLA target"
          value={<span className="text-foreground">{detail.statusMeta.slaTargetHours}h</span>}
        />
        <StatusRow label="SLA state" value={<SlaBadge state={detail.summary.slaState} />} />
        <div className="mt-2 rounded-md bg-muted/60 p-2">
          <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Next expected action
          </p>
          <p className="mt-0.5 text-xs text-foreground">{workflow.nextExpectedAction}</p>
        </div>
      </div>
    </WorkspaceSection>
  );
}

function StatusRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-muted-foreground">{label}</span>
      <div className="text-right">{value}</div>
    </div>
  );
}

function AttentionFlagsPanel({
  flags,
  acknowledged,
  onAck,
}: {
  flags: AttentionFlagRecord[];
  acknowledged: Set<string>;
  onAck: (f: AttentionFlagRecord) => void;
}) {
  return (
    <WorkspaceSection id="attention" title="Attention & risk">
      {flags.length === 0 ? (
        <EmptyState
          title="No attention flags"
          description="Nothing needs reviewer attention right now."
        />
      ) : (
        <ul className="space-y-2">
          {flags.map((f) => {
            const isAck = acknowledged.has(f.id);
            const state = isAck ? "acknowledged" : f.state;
            return (
              <li key={f.id} className="rounded-md border border-border bg-background p-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="flex items-center gap-1.5 text-xs font-medium text-foreground">
                      <Flag
                        aria-hidden
                        className={cn(
                          "size-3",
                          f.severity === "high" ? "text-rose-500" : "text-amber-500",
                        )}
                      />
                      {ATTENTION_FLAG_LABEL[f.flag]}
                    </p>
                    <p className="mt-0.5 text-[11px] text-muted-foreground">{f.reason}</p>
                    <p className="mt-1 text-[10px] text-muted-foreground">
                      {formatRelativeTime(f.createdAt)} · {f.source} · severity {f.severity}
                    </p>
                  </div>
                  <span
                    className={cn(
                      "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium",
                      state === "open" &&
                        "bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200",
                      state === "acknowledged" &&
                        "bg-sky-50 text-sky-900 dark:bg-sky-950/40 dark:text-sky-200",
                      state === "resolved" &&
                        "bg-emerald-50 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200",
                    )}
                  >
                    {state}
                  </span>
                </div>
                {!isAck && f.state === "open" ? (
                  <button
                    type="button"
                    onClick={() => onAck(f)}
                    className="mt-2 inline-flex h-6 items-center gap-1 rounded border border-border bg-background px-1.5 text-[11px] text-foreground hover:bg-accent"
                  >
                    <CheckCircle2 aria-hidden className="size-3" />
                    Acknowledge (session-only)
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </WorkspaceSection>
  );
}

function CandidateSummaryPanel({ detail }: { detail: VerificationCaseDetail }) {
  const c = detail.candidate;
  return (
    <WorkspaceSection id="candidate" title="Candidate">
      <div className="space-y-2 text-xs">
        <div>
          <p className="text-sm font-medium text-foreground">{c.name}</p>
          <p className="text-[11px] text-muted-foreground">{c.email}</p>
          <p className="font-mono text-[11px] text-muted-foreground">{c.phoneMasked}</p>
        </div>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5">
          <StatusRow
            label="Profile"
            value={<span className="text-foreground">{c.profileType}</span>}
          />
          <StatusRow
            label="Signed up"
            value={<span className="text-foreground">{formatRelativeTime(c.signupAt)}</span>}
          />
          <StatusRow
            label="Trust score"
            value={<span className="text-foreground tabular-nums">{c.trustScore}</span>}
          />
          <StatusRow
            label="Passport"
            value={
              <span className="text-foreground capitalize">
                {c.trustPassportStatus.replace(/_/g, " ")}
              </span>
            }
          />
          <StatusRow
            label="Records"
            value={<span className="text-foreground tabular-nums">{c.employmentRecordCount}</span>}
          />
          <StatusRow
            label="Prior verifications"
            value={
              <span className="text-foreground tabular-nums">{c.previousVerificationCount}</span>
            }
          />
        </dl>
        {c.riskFlags.length > 0 ? (
          <div className="rounded bg-amber-50 p-2 text-[11px] text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
            <p className="font-medium">Risk flags</p>
            <ul className="mt-0.5 list-inside list-disc">
              {c.riskFlags.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <Link
          to="/admin/users"
          className="mt-1 inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
        >
          Open candidate profile
          <ExternalLink aria-hidden className="size-3" />
        </Link>
      </div>
    </WorkspaceSection>
  );
}

function DecisionSummaryPanel({
  workflow,
  detail,
}: {
  workflow: UseVerificationWorkflowResult;
  detail: VerificationCaseDetail;
}) {
  const d = workflow.sessionDecision!;
  const tone =
    d.kind === "verify"
      ? "border-emerald-300 bg-emerald-50/60 dark:border-emerald-800 dark:bg-emerald-950/30"
      : d.kind === "reject"
        ? "border-destructive/40 bg-destructive/5"
        : "border-zinc-300 bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900/40";
  return (
    <WorkspaceSection
      id="decision-summary"
      title="Decision summary"
      description={`Terminal decision recorded for ${detail.summary.reference}.`}
    >
      <div className={cn("rounded-md border p-3", tone)}>
        <p className="text-xs font-semibold text-foreground">
          {d.kind === "verify" ? "Verified" : d.kind === "reject" ? "Rejected" : "Unable to Verify"}
        </p>
        <dl className="mt-2 space-y-1 text-[11px]">
          <SummaryRow label="Reason" value={d.reasonLabel} />
          {d.basisLabel ? <SummaryRow label="Basis" value={d.basisLabel} /> : null}
          <SummaryRow label="Performed by" value={`${d.actorName} · ${d.actorRole}`} />
          <SummaryRow label="Performed at" value={new Date(d.at).toLocaleString()} />
          <SummaryRow
            label="Candidate communication"
            value={d.candidateMessage ? "Prepared (not sent)" : "Not required"}
          />
          <SummaryRow label="Persistence" value="Session-only — not saved to backend" />
        </dl>
        {d.fieldConfirmations ? (
          <div className="mt-3">
            <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              Field confirmation
            </p>
            <ul className="mt-1 space-y-0.5 text-[11px]">
              {detail.claim.fields.map((f) => (
                <li key={f.key} className="flex justify-between gap-2">
                  <span className="text-muted-foreground">{f.label}</span>
                  <span className="text-foreground">
                    {FIELD_CONFIRMATION_LABEL[d.fieldConfirmations?.[f.key] ?? "not_applicable"]}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {d.decisionSummary ? (
          <div className="mt-3">
            <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              Summary
            </p>
            <p className="mt-1 whitespace-pre-wrap text-[11px] text-foreground">
              {d.decisionSummary}
            </p>
          </div>
        ) : null}
      </div>
    </WorkspaceSection>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right text-foreground">{value}</dd>
    </div>
  );
}

function DecisionPreparationPanel({
  detail,
  workflow,
  onOpen,
}: {
  detail: VerificationCaseDetail;
  workflow: UseVerificationWorkflowResult;
  onOpen: (a: WorkflowAction) => void;
}) {
  const evidenceReviewed = detail.evidence.filter((e) => e.reviewStatus === "reviewed").length;
  const evidenceAttention = detail.evidence.filter(
    (e) => e.reviewStatus === "needs_attention",
  ).length;
  const openFlags = detail.flags.filter(
    (f) => f.state === "open" && !workflow.acknowledgedFlagIds.has(f.id),
  ).length;
  const outreachContact = detail.contacts.find(
    (c) => c.outreachEligible && c.internalApprovalStatus === "approved",
  );

  const rows: { label: string; value: React.ReactNode }[] = [
    {
      label: "Evidence reviewed",
      value: (
        <span className="tabular-nums text-foreground">
          {evidenceReviewed} / {detail.evidence.length}
        </span>
      ),
    },
    {
      label: "Evidence needing attention",
      value: <span className="tabular-nums text-foreground">{evidenceAttention}</span>,
    },
    {
      label: "Open attention flags",
      value: <span className="tabular-nums text-foreground">{openFlags}</span>,
    },
    {
      label: "Organization",
      value: (
        <span className="text-foreground">
          {ORGANIZATION_STATUS_LABEL[detail.summary.organizationStatus]}
        </span>
      ),
    },
    {
      label: "Approved contact",
      value: (
        <span className={cn("text-foreground", !outreachContact && "text-muted-foreground")}>
          {outreachContact ? "Available" : "None"}
        </span>
      ),
    },
    {
      label: "Outreach",
      value: (
        <span className="text-foreground capitalize">
          {detail.summary.outreachStatus.replace(/_/g, " ")}
        </span>
      ),
    },
    { label: "SLA", value: <SlaBadge state={detail.summary.slaState} /> },
  ];

  const primaryActions: {
    action: WorkflowAction;
    label: string;
    icon: typeof Wrench;
    destructive?: boolean;
  }[] = [
    { action: "request_correction", label: "Request Correction", icon: Wrench },
    { action: "approve_outreach", label: "Approve for Outreach", icon: Shield },
    { action: "verify", label: "Verify", icon: CheckCircle2 },
    { action: "reject", label: "Reject", icon: X, destructive: true },
    { action: "unable_to_verify", label: "Unable to Verify", icon: AlertTriangle },
  ];

  const clarActions: {
    action: WorkflowAction;
    label: string;
  }[] = [
    { action: "record_clarification_request", label: "Record employer clarification" },
    { action: "record_clarification_response", label: "Record candidate response" },
  ];

  if (workflow.isTerminal) {
    return (
      <WorkspaceSection
        id="decision"
        title="Decision preparation"
        description="Case is in a terminal state. No further workflow transitions are permitted."
      >
        <div className="rounded-md border border-dashed border-border bg-muted/40 p-3 text-[11px] text-muted-foreground">
          Reopening completed cases is not available in this build.
        </div>
      </WorkspaceSection>
    );
  }

  return (
    <WorkspaceSection
      id="decision"
      title="Decision preparation"
      description="Actions are gated by explicit workflow rules and your permissions."
    >
      <dl className="space-y-1.5 text-xs">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center justify-between gap-2">
            <dt className="text-muted-foreground">{r.label}</dt>
            <dd>{r.value}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-3 flex flex-col gap-1.5">
        {primaryActions.map(({ action, label, icon: Icon, destructive }) => {
          const el = workflow.getEligibility(action);
          if (el.irrelevant && !el.allowed) return null;
          return (
            <ActionButton
              key={action}
              icon={Icon}
              label={label}
              destructive={destructive}
              eligibility={el}
              onClick={() => onOpen(action)}
            />
          );
        })}
      </div>
      <div className="mt-4">
        <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          Clarification (secondary)
        </p>
        <div className="flex flex-col gap-1.5">
          {clarActions.map(({ action, label }) => {
            const el = workflow.getEligibility(action);
            if (el.irrelevant && !el.allowed) return null;
            return (
              <ActionButton
                key={action}
                icon={MessageSquare}
                label={label}
                eligibility={el}
                onClick={() => onOpen(action)}
              />
            );
          })}
        </div>
      </div>
      <p className="mt-3 text-[11px] italic text-muted-foreground">
        Every action is session-only. Nothing is sent, persisted, or forwarded to candidate-facing
        surfaces.
      </p>
    </WorkspaceSection>
  );
}

function ActionButton({
  label,
  icon: Icon,
  eligibility,
  destructive,
  onClick,
}: {
  label: string;
  icon: typeof Wrench;
  eligibility: ReturnType<UseVerificationWorkflowResult["getEligibility"]>;
  destructive?: boolean;
  onClick: () => void;
}) {
  const disabled = !eligibility.allowed;
  const [showWhy, setShowWhy] = useState(false);
  return (
    <div>
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={onClick}
          disabled={disabled}
          aria-disabled={disabled}
          title={disabled ? eligibility.blockingReasons[0] : undefined}
          className={cn(
            "inline-flex h-8 flex-1 items-center gap-1.5 rounded-md border px-2 text-xs font-medium",
            disabled
              ? "border-border bg-background text-muted-foreground"
              : destructive
                ? "border-destructive/40 bg-destructive/5 text-destructive hover:bg-destructive/10"
                : "border-border bg-background text-foreground hover:bg-accent",
          )}
        >
          <Icon aria-hidden className="size-3.5" />
          {label}
        </button>
        {disabled ? (
          <button
            type="button"
            onClick={() => setShowWhy((v) => !v)}
            aria-expanded={showWhy}
            className="rounded-md border border-border bg-background px-1.5 py-1 text-[10px] text-muted-foreground hover:bg-accent"
          >
            {showWhy ? "Hide" : "Why?"}
          </button>
        ) : null}
      </div>
      {disabled && showWhy ? (
        <ul className="mt-1 list-inside list-disc space-y-0.5 rounded-md border border-border bg-muted/50 p-2 text-[11px] text-muted-foreground">
          {eligibility.blockingReasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// =====================================================================
// Small header helpers
// =====================================================================

function SlaBadge({ state }: { state: VerificationCaseDetail["summary"]["slaState"] }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium",
        state === "breached" && "bg-rose-50 text-rose-900 dark:bg-rose-950/40 dark:text-rose-200",
        state === "approaching" &&
          "bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200",
        state === "within" &&
          "bg-emerald-50 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200",
      )}
    >
      {SLA_LABEL[state]}
    </span>
  );
}

type MenuOption = string | { key: string; label: string };

function Menu({
  label,
  icon: Icon,
  current,
  options,
  onSelect,
}: {
  label: string;
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  current: string;
  options: MenuOption[];
  onSelect: (key: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-2 text-xs text-foreground hover:bg-accent"
      >
        <Icon aria-hidden className="size-3.5" />
        {label}
        <span className="hidden text-muted-foreground sm:inline">· {current}</span>
      </button>
      {open ? (
        <>
          <button
            aria-label="Close menu"
            className="fixed inset-0 z-10 cursor-default"
            onClick={() => setOpen(false)}
          />
          <div
            role="menu"
            className="absolute right-0 z-20 mt-1 w-44 rounded-md border border-border bg-popover p-1 text-xs shadow-md"
          >
            {options.map((o) => {
              const key = typeof o === "string" ? o : o.key;
              const label = typeof o === "string" ? o : o.label;
              return (
                <button
                  key={key}
                  role="menuitem"
                  onClick={() => {
                    onSelect(key);
                    setOpen(false);
                  }}
                  className="block w-full rounded px-2 py-1.5 text-left text-foreground hover:bg-accent"
                >
                  {label}
                </button>
              );
            })}
          </div>
        </>
      ) : null}
    </div>
  );
}

/**
 * Dev-only role switcher for testing permission-blocked states. Uses
 * localStorage; never surfaced as a production feature.
 */
function DevRoleMenu() {
  if (!import.meta.env.DEV) return null;
  const roles: AdminRoleKey[] = [
    "admin",
    "operations_lead",
    "trust_safety",
    "reviewer",
    "read_only",
  ];
  const current: AdminRoleKey =
    (typeof window !== "undefined" ? getDevAdminRole() : null) ?? "admin";
  return (
    <Menu
      label="Dev role"
      icon={Users}
      current={ROLE_LABEL[current]}
      options={roles.map((r) => ({ key: r, label: ROLE_LABEL[r] }))}
      onSelect={(k) => {
        setDevAdminRole(k as AdminRoleKey);
        toast(`Dev role: ${ROLE_LABEL[k as AdminRoleKey]}`, {
          description: "Session-only. For testing permission-blocked states.",
        });
      }}
    />
  );
}
