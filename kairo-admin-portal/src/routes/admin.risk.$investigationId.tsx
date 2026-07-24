import { useMemo, useState } from "react";
import { Link, createFileRoute, notFound, useRouter } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowUpRight,
  ChevronRight,
  ExternalLink,
  FileWarning,
  Flame,
  Info,
  ShieldAlert,
  ShieldCheck,
  StickyNote,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState } from "@/features/admin/components/states";
import { WorkspaceSection } from "@/features/admin/components/workspace-section";
import { UnsavedChangesDialog } from "@/features/admin/components/unsaved-changes-dialog";
import { formatRelativeTime } from "@/features/admin/lib/format";
import { useAdminAccess } from "@/features/admin/auth/admin-access";
import { hasPermission } from "@/features/admin/workflow/permissions";
import { InvestigationStatusBadge, RiskLevelBadge } from "./admin.risk.index";
import {
  DOCUMENT_ANOMALY_LABEL,
  EVENT_KIND_LABEL,
  INVESTIGATION_STATUS_LABEL,
  NOTE_CATEGORY_LABEL,
  RECOMMENDED_ACTION_LABEL,
  RISK_CATEGORY_LABEL,
  SIGNAL_CONFIDENCE_LABEL,
  SIGNAL_SEVERITY_LABEL,
  SIGNAL_SOURCE_LABEL,
  SIGNAL_STATUS_LABEL,
  SUBJECT_KIND_LABEL,
  getInvestigation,
  mockInvestigations,
  type DocumentAnomaly,
  type DuplicateReview,
  type Investigation,
  type InvestigationStatus,
  type NoteCategory,
  type RecommendedActionKind,
  type RiskSignal,
} from "@/features/admin/data/risk";
import { mockUsers } from "@/features/admin/data/users";
import { mockVerificationCases } from "@/features/admin/data/verifications";
import { mockRegistryOrganizations } from "@/features/admin/data/registry";
import {
  DUPLICATE_DECISION_LABEL,
  useInvestigationSession,
  type DuplicateDecision,
} from "@/features/admin/workflow/use-investigation-session";
import { toast } from "sonner";

export const Route = createFileRoute("/admin/risk/$investigationId")({
  loader: ({ params }) => {
    const inv = getInvestigation(params.investigationId);
    if (!inv) throw notFound();
    return { inv };
  },
  head: ({ loaderData }) => ({
    meta: [
      {
        title: loaderData
          ? `${loaderData.inv.reference} — Trust & Safety`
          : "Investigation not found — Kairo Admin",
      },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  errorComponent: InvestigationDetailErrorBoundary,
  notFoundComponent: InvestigationDetailNotFound,
  component: InvestigationDetailPage,
});

function InvestigationDetailErrorBoundary({ error, reset }: { error: Error; reset: () => void }) {
  const router = useRouter();

  return (
    <div className="mx-auto max-w-2xl p-8">
      <ErrorState
        title="Something went wrong"
        description={error.message}
        action={
          <button
            type="button"
            onClick={() => {
              router.invalidate();
              reset();
            }}
            className="inline-flex h-8 items-center rounded-md border border-border bg-background px-3 text-xs font-medium hover:bg-accent"
          >
            Retry
          </button>
        }
      />
    </div>
  );
}

function InvestigationDetailNotFound() {
  const { investigationId } = Route.useParams();

  return (
    <div className="mx-auto max-w-2xl p-8">
      <EmptyState
        title="Investigation not found"
        description={`No investigation matches "${investigationId}". Check the reference or return to the list.`}
        action={
          <Link
            to="/admin/risk"
            className="inline-flex h-8 items-center gap-1 rounded-md border border-border bg-background px-3 text-xs font-medium hover:bg-accent"
          >
            <ArrowLeft aria-hidden className="size-3" /> Back to investigations
          </Link>
        }
      />
    </div>
  );
}

function InvestigationDetailPage() {
  const { investigationId } = Route.useParams();
  const base = getInvestigation(investigationId) as Investigation;
  const { admin } = useAdminAccess();
  const permissions = admin?.permissions ?? [];
  const canView = hasPermission(permissions, "risk.view");
  const canNote = hasPermission(permissions, "risk.note");
  const canReview = hasPermission(permissions, "risk.review");
  const canEscalate = hasPermission(permissions, "risk.escalate");
  const canResolve = hasPermission(permissions, "risk.resolve");
  const canPrepareActions = hasPermission(permissions, "risk.prepare_actions");

  const session = useInvestigationSession(admin?.name ?? "Kairo Operator", admin?.role ?? "Admin");
  const inv = useMemo(() => session.overlay(base), [session, base]);

  const router = useRouter();
  const [pendingHref, setPendingHref] = useState<string | null>(null);
  function tryNavigate(href: string) {
    if (session.hasUnsavedChanges) setPendingHref(href);
    else router.navigate({ to: href });
  }

  if (!canView) {
    return (
      <div className="mx-auto max-w-2xl p-8">
        <EmptyState
          title="No access"
          description="Your role does not include the risk.view permission."
        />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-4">
      {/* Breadcrumb */}
      <nav aria-label="Breadcrumb" className="text-xs text-muted-foreground">
        <ol className="flex items-center gap-1">
          <li>
            <button
              type="button"
              onClick={() => tryNavigate("/admin/risk")}
              className="hover:text-foreground hover:underline"
            >
              Trust &amp; Safety
            </button>
          </li>
          <ChevronRight aria-hidden className="size-3" />
          <li className="font-medium text-foreground">{inv.reference}</li>
        </ol>
      </nav>

      {/* Header */}
      <div className="sticky top-0 z-10 rounded-lg border border-border bg-card/95 p-4 backdrop-blur">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              <h1 className="text-base font-semibold tracking-tight text-foreground">
                {inv.reference}
              </h1>
              <RiskLevelBadge level={inv.riskLevel} />
              <InvestigationStatusBadge status={inv.status} />
              {inv.escalated ? (
                <span className="inline-flex items-center gap-1 rounded bg-rose-50 px-1.5 py-0.5 text-[10px] font-medium text-rose-900 ring-1 ring-inset ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60">
                  <Flame aria-hidden className="size-3" /> Escalated
                </span>
              ) : null}
            </div>
            <p className="mt-1 text-sm text-foreground">{inv.reason}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {RISK_CATEGORY_LABEL[inv.category]} · Subject: {SUBJECT_KIND_LABEL[inv.subject.kind]}{" "}
              — {inv.subject.displayName}
              {inv.subject.reference ? ` (${inv.subject.reference})` : ""} · Opened{" "}
              {formatRelativeTime(inv.createdAt)} · Owner {inv.owner}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <HeaderButton
              onClick={() => session.simulateStatus(inv.id, "in_review")}
              disabled={!canReview || inv.status === "in_review"}
              disabledReason={!canReview ? "Requires risk.review" : undefined}
            >
              Mark in review
            </HeaderButton>
            <HeaderButton
              onClick={() => session.simulateStatus(inv.id, "escalated")}
              disabled={!canEscalate || inv.status === "escalated"}
              disabledReason={!canEscalate ? "Requires risk.escalate" : undefined}
              tone="danger"
            >
              Escalate to T&amp;S
            </HeaderButton>
          </div>
        </div>
        {session.hasUnsavedChanges ? (
          <p className="mt-3 rounded bg-sky-50 px-2 py-1 text-[11px] text-sky-900 dark:bg-sky-950/40 dark:text-sky-200">
            Session-only workspace — signals, notes and prepared actions here are not saved to the
            backend.
          </p>
        ) : null}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        {/* MAIN */}
        <div className="flex min-w-0 flex-col gap-4">
          <SignalsSection signals={inv.signals} />
          {inv.duplicateReview ? (
            <DuplicateReviewSection
              inv={inv}
              current={session.getDuplicateDecision(inv.id)}
              onRecord={(decision, rationale) => {
                session.recordDuplicateDecision(inv.id, decision, rationale);
                toast.success("Duplicate review recorded (session-only)");
              }}
              disabled={!canReview}
            />
          ) : null}
          {inv.documentAnomalies.length > 0 ? (
            <DocumentAnomaliesSection anomalies={inv.documentAnomalies} />
          ) : null}
          <EvidenceSection
            inv={inv}
            selected={session.getSelectedEvidence(inv.id)}
            onToggle={(id) => session.toggleEvidence(inv.id, id)}
          />
          <RelatedSection inv={inv} onNavigate={tryNavigate} />
          <NotesSection
            notes={inv.notes}
            onAdd={(body, category) => {
              session.addNote(inv.id, body, category);
              toast.success("Note added (session-only)");
            }}
            canCreate={canNote}
          />
          <TimelineSection inv={inv} />
        </div>

        {/* SIDEBAR */}
        <aside className="flex flex-col gap-4">
          <SubjectPanel inv={inv} onNavigate={tryNavigate} />
          <RecommendedActionsPanel
            inv={inv}
            preparedActions={session.getPreparedActions(inv.id)}
            onPrepare={(kind, rationale) => {
              session.prepareAction(inv.id, kind, rationale);
              toast.success(`Prepared: ${RECOMMENDED_ACTION_LABEL[kind]} (session-only)`);
            }}
            canPrepare={canPrepareActions}
          />
          <ResolutionPanel
            inv={inv}
            canResolve={canResolve}
            onResolve={(status) => {
              session.simulateStatus(inv.id, status);
              toast.success(`Resolution simulated: ${INVESTIGATION_STATUS_LABEL[status]}`);
            }}
          />
          <SummaryPanel inv={inv} />
        </aside>
      </div>

      <UnsavedChangesDialog
        open={pendingHref !== null}
        onOpenChange={(o) => {
          if (!o) setPendingHref(null);
        }}
        onConfirm={() => {
          const href = pendingHref;
          setPendingHref(null);
          if (href) router.navigate({ to: href });
        }}
        changes={sessionChangeSummary(session, inv.id)}
      />
    </div>
  );
}

// =====================================================================
function HeaderButton({
  onClick,
  disabled,
  disabledReason,
  tone,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  disabledReason?: string;
  tone?: "danger";
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={disabled && disabledReason ? disabledReason : undefined}
      className={cn(
        "inline-flex h-8 items-center rounded-md border px-2.5 text-xs font-medium disabled:opacity-50",
        tone === "danger"
          ? "border-rose-300 bg-rose-50 text-rose-900 hover:bg-rose-100 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-200"
          : "border-border bg-background text-foreground hover:bg-accent",
      )}
    >
      {children}
    </button>
  );
}

// ---- Signals -------------------------------------------------------------
function SignalsSection({ signals }: { signals: RiskSignal[] }) {
  return (
    <WorkspaceSection
      id="signals"
      title="Risk signals"
      description="Every signal explains WHY it fired. Severity and confidence are shown separately."
    >
      {signals.length === 0 ? (
        <EmptyState title="No risk signals attached to this investigation." />
      ) : (
        <ul className="space-y-2">
          {signals.map((s) => (
            <li key={s.id} className="rounded-md border border-border bg-background p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground">{s.title}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{s.explanation}</p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <SeverityChip severity={s.severity} />
                  <span className="text-[10px] text-muted-foreground">
                    {SIGNAL_CONFIDENCE_LABEL[s.confidence]}
                  </span>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
                <span className="rounded bg-muted px-1.5 py-0.5 font-medium">
                  {SIGNAL_SOURCE_LABEL[s.source]}
                </span>
                <span className="rounded bg-muted px-1.5 py-0.5 font-medium">
                  {SIGNAL_STATUS_LABEL[s.status]}
                </span>
                <span>Detected {formatRelativeTime(s.createdAt)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </WorkspaceSection>
  );
}

function SeverityChip({ severity }: { severity: RiskSignal["severity"] }) {
  const map: Record<RiskSignal["severity"], string> = {
    critical:
      "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60",
    high: "bg-orange-50 text-orange-900 ring-orange-200 dark:bg-orange-950/40 dark:text-orange-200 dark:ring-orange-900/60",
    medium:
      "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60",
    low: "bg-zinc-100 text-zinc-800 ring-zinc-200 dark:bg-zinc-800/60 dark:text-zinc-200 dark:ring-zinc-700",
    info: "bg-sky-50 text-sky-900 ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:ring-sky-900/60",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset",
        map[severity],
      )}
    >
      {SIGNAL_SEVERITY_LABEL[severity]}
    </span>
  );
}

// ---- Duplicate review ----------------------------------------------------
function DuplicateReviewSection({
  inv,
  current,
  onRecord,
  disabled,
}: {
  inv: Investigation;
  current?: { decision: DuplicateDecision; rationale: string; at: string; actor: string };
  onRecord: (d: DuplicateDecision, r: string) => void;
  disabled: boolean;
}) {
  const dr = inv.duplicateReview!;
  const [rationale, setRationale] = useState("");
  const [decision, setDecision] = useState<DuplicateDecision>("continue_investigation");

  return (
    <WorkspaceSection
      id="duplicate-review"
      title="Duplicate identity review"
      description={`Confidence ${dr.confidencePct}% based on ${dr.matchingFields.length} matching fields.`}
    >
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <CandidateCard label="Candidate A" c={dr.candidateA} />
        <CandidateCard label="Candidate B" c={dr.candidateB} />
      </div>
      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        <MatchesBlock title="Matching fields" tone="match" items={dr.matchingFields} />
        <MatchesBlock title="Differences" tone="diff" items={dr.differences} />
      </div>
      {dr.sharedIdentifiers.length > 0 ? (
        <div className="mt-3 rounded-md border border-border bg-background p-2 text-[11px] text-muted-foreground">
          Shared identifiers:{" "}
          <span className="font-mono text-foreground">{dr.sharedIdentifiers.join(" · ")}</span>
        </div>
      ) : null}

      {current ? (
        <div className="mt-3 rounded-md border border-sky-200 bg-sky-50 p-3 text-xs text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/40 dark:text-sky-200">
          <p className="font-medium">
            Session decision recorded: {DUPLICATE_DECISION_LABEL[current.decision]}
          </p>
          {current.rationale ? <p className="mt-0.5">{current.rationale}</p> : null}
          <p className="mt-0.5 text-[10px] opacity-75">
            {current.actor} · {formatRelativeTime(current.at)}
          </p>
        </div>
      ) : null}

      <div className="mt-3 rounded-md border border-border bg-background p-3">
        <label className="block text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Record duplicate decision
        </label>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <select
            value={decision}
            onChange={(e) => setDecision(e.target.value as DuplicateDecision)}
            className="h-8 rounded border border-border bg-background px-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            disabled={disabled}
            aria-label="Duplicate decision"
          >
            {(Object.keys(DUPLICATE_DECISION_LABEL) as DuplicateDecision[]).map((d) => (
              <option key={d} value={d}>
                {DUPLICATE_DECISION_LABEL[d]}
              </option>
            ))}
          </select>
          <input
            type="text"
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            placeholder="Rationale (visible only to Kairo)"
            className="h-8 flex-1 min-w-[220px] rounded border border-border bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            disabled={disabled}
          />
          <button
            type="button"
            disabled={disabled || !rationale.trim()}
            onClick={() => {
              onRecord(decision, rationale.trim());
              setRationale("");
            }}
            title={disabled ? "Requires risk.review" : undefined}
            className="inline-flex h-8 items-center rounded-md bg-foreground px-2.5 text-xs font-medium text-background hover:bg-foreground/90 disabled:opacity-50"
          >
            Record decision
          </button>
        </div>
      </div>
    </WorkspaceSection>
  );
}

function CandidateCard({ label, c }: { label: string; c: DuplicateReview["candidateA"] }) {
  return (
    <div className="rounded-md border border-border bg-background p-3">
      <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 text-sm font-semibold text-foreground">{c.displayName}</p>
      <p className="text-[11px] text-muted-foreground">{c.email}</p>
      <p className="mt-1 text-[11px] text-muted-foreground">
        {c.location ?? "Location unknown"} · Joined {new Date(c.joinedAt).toLocaleDateString()}
      </p>
      <Link
        to="/admin/users/$userId"
        params={{ userId: c.userId }}
        className="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-foreground underline-offset-2 hover:underline"
      >
        Open user <ArrowUpRight aria-hidden className="size-3" />
      </Link>
    </div>
  );
}

function MatchesBlock({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: "match" | "diff";
}) {
  return (
    <div
      className={cn(
        "rounded-md border p-3",
        tone === "match"
          ? "border-emerald-200 bg-emerald-50/50 dark:border-emerald-900/60 dark:bg-emerald-950/20"
          : "border-amber-200 bg-amber-50/50 dark:border-amber-900/60 dark:bg-amber-950/20",
      )}
    >
      <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {title}
      </p>
      <ul className="mt-1 space-y-0.5 text-xs text-foreground">
        {items.map((it) => (
          <li key={it}>· {it}</li>
        ))}
      </ul>
    </div>
  );
}

// ---- Document anomalies -------------------------------------------------
function DocumentAnomaliesSection({ anomalies }: { anomalies: DocumentAnomaly[] }) {
  return (
    <WorkspaceSection
      id="document-anomalies"
      title="Document anomalies"
      description="Findings from automated checks and reviewer flags."
    >
      <ul className="space-y-2">
        {anomalies.map((a) => (
          <li key={a.id} className="rounded-md border border-border bg-background p-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground">
                  {DOCUMENT_ANOMALY_LABEL[a.kind]}
                </p>
                <p className="text-[11px] text-muted-foreground">{a.documentLabel}</p>
                <p className="mt-1 text-xs text-foreground">{a.detail}</p>
              </div>
              <div className="flex shrink-0 flex-col items-end text-[10px] text-muted-foreground">
                <span>Detected {formatRelativeTime(a.detectedAt)}</span>
                {a.reviewedAt ? <span>Reviewed {formatRelativeTime(a.reviewedAt)}</span> : null}
              </div>
            </div>
            {a.relatedCaseId ? (
              <Link
                to="/admin/verifications/$caseId"
                params={{ caseId: a.relatedCaseId }}
                className="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-foreground underline-offset-2 hover:underline"
              >
                Related case <ExternalLink aria-hidden className="size-3" />
              </Link>
            ) : null}
          </li>
        ))}
      </ul>
    </WorkspaceSection>
  );
}

// ---- Evidence -----------------------------------------------------------
function EvidenceSection({
  inv,
  selected,
  onToggle,
}: {
  inv: Investigation;
  selected: Set<string>;
  onToggle: (id: string) => void;
}) {
  return (
    <WorkspaceSection
      id="evidence"
      title="Evidence"
      description="Select the evidence you want to reference in a decision or handover."
    >
      {inv.evidence.length === 0 ? (
        <EmptyState title="No evidence attached." />
      ) : (
        <ul className="space-y-1.5">
          {inv.evidence.map((e) => {
            const checked = selected.has(e.id);
            return (
              <li key={e.id} className="rounded-md border border-border bg-background p-2">
                <label className="flex cursor-pointer items-start gap-2">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => onToggle(e.id)}
                    className="mt-0.5 size-3.5 rounded border-border accent-foreground"
                  />
                  <span className="flex-1 min-w-0">
                    <span className="block text-xs font-medium text-foreground">{e.label}</span>
                    <span className="block text-[11px] text-muted-foreground">
                      {e.kind} · added {formatRelativeTime(e.addedAt)}
                      {e.detail ? ` · ${e.detail}` : ""}
                    </span>
                    {e.relatedCaseId ? (
                      <Link
                        to="/admin/verifications/$caseId"
                        params={{ caseId: e.relatedCaseId }}
                        className="mt-0.5 inline-flex items-center gap-1 text-[11px] font-medium text-foreground underline-offset-2 hover:underline"
                      >
                        Related case <ExternalLink aria-hidden className="size-3" />
                      </Link>
                    ) : null}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      {selected.size > 0 ? (
        <p className="mt-2 text-[11px] text-muted-foreground">
          {selected.size} item(s) selected for this session.
        </p>
      ) : null}
    </WorkspaceSection>
  );
}

// ---- Related ------------------------------------------------------------
function RelatedSection({
  inv,
  onNavigate,
}: {
  inv: Investigation;
  onNavigate: (href: string) => void;
}) {
  const users = inv.relatedUserIds.map((id) => mockUsers.find((u) => u.id === id)).filter(Boolean);
  const cases = inv.relatedCaseIds
    .map((id) => mockVerificationCases.find((c) => c.id === id))
    .filter(Boolean);
  const orgs = inv.relatedOrganizationIds
    .map((id) => mockRegistryOrganizations.find((o) => o.id === id))
    .filter(Boolean);

  if (users.length === 0 && cases.length === 0 && orgs.length === 0) return null;

  return (
    <WorkspaceSection
      id="related"
      title="Related records"
      description="Cross-links into the rest of the admin portal."
    >
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <RelatedList
          title="Users"
          items={users.map((u) => ({
            id: u!.id,
            label: u!.fullName,
            sub: u!.displayId,
            href: `/admin/users/${u!.id}`,
          }))}
          onNavigate={onNavigate}
        />
        <RelatedList
          title="Cases"
          items={cases.map((c) => ({
            id: c!.id,
            label: c!.reference,
            sub: c!.candidateName,
            href: `/admin/verifications/${c!.id}`,
          }))}
          onNavigate={onNavigate}
        />
        <RelatedList
          title="Organizations"
          items={orgs.map((o) => ({
            id: o!.id,
            label: o!.canonicalName,
            sub: o!.country,
            href: `/admin/registry/${o!.id}`,
          }))}
          onNavigate={onNavigate}
        />
      </div>
    </WorkspaceSection>
  );
}

function RelatedList({
  title,
  items,
  onNavigate,
}: {
  title: string;
  items: { id: string; label: string; sub: string; href: string }[];
  onNavigate: (href: string) => void;
}) {
  return (
    <div className="rounded-md border border-border bg-background p-3">
      <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {title}
      </p>
      {items.length === 0 ? (
        <p className="mt-1 text-[11px] text-muted-foreground">None</p>
      ) : (
        <ul className="mt-1 space-y-1">
          {items.map((it) => (
            <li key={it.id}>
              <button
                type="button"
                onClick={() => onNavigate(it.href)}
                className="w-full rounded px-1 py-0.5 text-left text-xs hover:bg-accent"
              >
                <span className="font-medium text-foreground">{it.label}</span>
                <span className="ml-1 text-[10px] text-muted-foreground">{it.sub}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---- Notes ---------------------------------------------------------------
const NOTE_CATEGORIES: NoteCategory[] = ["evidence", "risk", "decision", "escalation", "general"];

function NotesSection({
  notes,
  onAdd,
  canCreate,
}: {
  notes: Investigation["notes"];
  onAdd: (body: string, category: NoteCategory) => void;
  canCreate: boolean;
}) {
  const [body, setBody] = useState("");
  const [category, setCategory] = useState<NoteCategory>("general");

  return (
    <WorkspaceSection
      id="notes"
      title="Investigation notes"
      description="Internal only. Never visible to candidates or employers."
    >
      {canCreate ? (
        <form
          className="rounded-md border border-border bg-background p-3"
          onSubmit={(e) => {
            e.preventDefault();
            const trimmed = body.trim();
            if (!trimmed) return;
            onAdd(trimmed, category);
            setBody("");
            setCategory("general");
          }}
        >
          <label htmlFor="inv-note-body" className="sr-only">
            Investigation note
          </label>
          <textarea
            id="inv-note-body"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={3}
            placeholder="Add an investigation note. Never visible to candidates or employers."
            className="block w-full resize-y rounded border border-border bg-background px-2 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs">
              <label htmlFor="inv-note-cat" className="text-muted-foreground">
                Category
              </label>
              <select
                id="inv-note-cat"
                value={category}
                onChange={(e) => setCategory(e.target.value as NoteCategory)}
                className="h-7 rounded border border-border bg-background px-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              >
                {NOTE_CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {NOTE_CATEGORY_LABEL[c]}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="submit"
              disabled={!body.trim()}
              className="inline-flex h-7 items-center gap-1 rounded-md bg-foreground px-2 text-xs font-medium text-background hover:bg-foreground/90 disabled:opacity-50"
            >
              <StickyNote aria-hidden className="size-3" /> Add note (session-only)
            </button>
          </div>
        </form>
      ) : (
        <p className="rounded-md border border-dashed border-border bg-muted/30 p-2 text-[11px] text-muted-foreground">
          Your role does not include risk.note. Existing notes are still visible.
        </p>
      )}

      {notes.length === 0 ? (
        <div className="mt-3">
          <EmptyState title="No investigation notes yet." />
        </div>
      ) : (
        <ul className="mt-3 space-y-2">
          {notes
            .slice()
            .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime())
            .map((n) => (
              <li key={n.id} className="rounded-md border border-border bg-background p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-xs font-medium text-foreground">
                    {n.actor}{" "}
                    <span className="font-normal text-muted-foreground">· {n.actorRole}</span>
                  </p>
                  <p className="text-[11px] tabular-nums text-muted-foreground">
                    {formatRelativeTime(n.at)}
                  </p>
                </div>
                <p className="mt-1 whitespace-pre-wrap text-xs text-foreground">{n.body}</p>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                    {NOTE_CATEGORY_LABEL[n.category]}
                  </span>
                  {n.sessionOnly ? (
                    <span className="rounded bg-sky-50 px-1.5 py-0.5 text-[10px] font-medium text-sky-700 ring-1 ring-inset ring-sky-200 dark:bg-sky-950/40 dark:text-sky-300 dark:ring-sky-900/60">
                      Session-only
                    </span>
                  ) : null}
                </div>
              </li>
            ))}
        </ul>
      )}
    </WorkspaceSection>
  );
}

// ---- Timeline ------------------------------------------------------------
function TimelineSection({ inv }: { inv: Investigation }) {
  return (
    <WorkspaceSection
      id="timeline"
      title="Investigation timeline"
      description="Immutable-style event log combining system events, notes and session actions."
    >
      <ol className="relative space-y-3 border-l border-border pl-4">
        {inv.timeline
          .slice()
          .sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime())
          .map((e) => (
            <li key={e.id} className="relative">
              <span
                className="absolute -left-[19px] top-1 size-2 rounded-full bg-foreground/60"
                aria-hidden
              />
              <p className="text-xs font-medium text-foreground">
                {EVENT_KIND_LABEL[e.kind]}
                {e.sessionOnly ? (
                  <span className="ml-1.5 rounded bg-sky-50 px-1.5 py-0.5 text-[10px] font-medium text-sky-700 ring-1 ring-inset ring-sky-200 dark:bg-sky-950/40 dark:text-sky-300 dark:ring-sky-900/60">
                    Session-only
                  </span>
                ) : null}
              </p>
              <p className="text-[11px] text-muted-foreground">{e.detail}</p>
              <p className="text-[10px] text-muted-foreground">
                {e.actor} · {formatRelativeTime(e.at)}
              </p>
            </li>
          ))}
      </ol>
    </WorkspaceSection>
  );
}

// ---- Sidebar panels ------------------------------------------------------
function SubjectPanel({
  inv,
  onNavigate,
}: {
  inv: Investigation;
  onNavigate: (href: string) => void;
}) {
  const user =
    inv.subject.kind === "user" ? mockUsers.find((u) => u.id === inv.subject.id) : undefined;
  const org =
    inv.subject.kind === "organization"
      ? mockRegistryOrganizations.find((o) => o.id === inv.subject.id)
      : undefined;
  const c =
    inv.subject.kind === "case"
      ? mockVerificationCases.find((v) => v.id === inv.subject.id)
      : undefined;

  const href = user
    ? `/admin/users/${user.id}`
    : org
      ? `/admin/registry/${org.id}`
      : c
        ? `/admin/verifications/${c.id}`
        : null;

  return (
    <WorkspaceSection id="subject" title="Investigation subject">
      <p className="text-sm font-semibold text-foreground">{inv.subject.displayName}</p>
      <p className="text-[11px] text-muted-foreground">
        {SUBJECT_KIND_LABEL[inv.subject.kind]}
        {inv.subject.reference ? ` · ${inv.subject.reference}` : ""}
      </p>
      {user ? (
        <ul className="mt-2 space-y-0.5 text-[11px] text-muted-foreground">
          <li>{user.email}</li>
          <li>{user.location}</li>
          <li>Joined {new Date(user.joinedAt).toLocaleDateString()}</li>
        </ul>
      ) : null}
      {org ? (
        <ul className="mt-2 space-y-0.5 text-[11px] text-muted-foreground">
          <li>{org.country}</li>
        </ul>
      ) : null}
      {href ? (
        <button
          type="button"
          onClick={() => onNavigate(href)}
          className="mt-2 inline-flex h-7 items-center gap-1 rounded-md border border-border bg-background px-2 text-xs font-medium hover:bg-accent"
        >
          Open subject <ArrowUpRight aria-hidden className="size-3" />
        </button>
      ) : null}
    </WorkspaceSection>
  );
}

function RecommendedActionsPanel({
  inv,
  preparedActions,
  onPrepare,
  canPrepare,
}: {
  inv: Investigation;
  preparedActions: ReturnType<ReturnType<typeof useInvestigationSession>["getPreparedActions"]>;
  onPrepare: (k: RecommendedActionKind, rationale: string) => void;
  canPrepare: boolean;
}) {
  const [kind, setKind] = useState<RecommendedActionKind | "">(
    inv.recommendedActions[0]?.kind ?? "",
  );
  const [rationale, setRationale] = useState(inv.recommendedActions[0]?.rationale ?? "");

  return (
    <WorkspaceSection
      id="recommended-actions"
      title="Recommended actions"
      description="Prepared here for a Trust & Safety lead to execute — nothing is auto-applied."
    >
      {inv.recommendedActions.length > 0 ? (
        <div className="rounded-md border border-border bg-background p-2">
          <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Suggested
          </p>
          <ul className="mt-1 space-y-1 text-xs">
            {inv.recommendedActions.map((a) => (
              <li key={a.kind}>
                <span className="font-medium text-foreground">
                  {RECOMMENDED_ACTION_LABEL[a.kind]}
                </span>
                <span className="ml-1 text-muted-foreground">— {a.rationale}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-3 rounded-md border border-border bg-background p-2">
        <label className="block text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Prepare action
        </label>
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as RecommendedActionKind)}
          disabled={!canPrepare}
          className="mt-1 h-8 w-full rounded border border-border bg-background px-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          aria-label="Recommended action"
        >
          <option value="" disabled>
            Select an action…
          </option>
          {(Object.keys(RECOMMENDED_ACTION_LABEL) as RecommendedActionKind[]).map((k) => (
            <option key={k} value={k}>
              {RECOMMENDED_ACTION_LABEL[k]}
            </option>
          ))}
        </select>
        <textarea
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          rows={2}
          placeholder="Rationale (required)"
          disabled={!canPrepare}
          className="mt-2 block w-full resize-y rounded border border-border bg-background px-2 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        />
        <button
          type="button"
          disabled={!canPrepare || !kind || !rationale.trim()}
          onClick={() => {
            if (kind) {
              onPrepare(kind, rationale.trim());
              setRationale("");
            }
          }}
          title={!canPrepare ? "Requires risk.prepare_actions" : undefined}
          className="mt-2 inline-flex h-7 w-full items-center justify-center gap-1 rounded-md bg-foreground px-2 text-xs font-medium text-background hover:bg-foreground/90 disabled:opacity-50"
        >
          Prepare action (session-only)
        </button>
      </div>

      {preparedActions.length > 0 ? (
        <ul className="mt-3 space-y-1.5">
          {preparedActions.map((a) => (
            <li
              key={a.id}
              className="rounded border border-sky-200 bg-sky-50 p-2 text-[11px] text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/40 dark:text-sky-200"
            >
              <p className="font-medium">{RECOMMENDED_ACTION_LABEL[a.kind]}</p>
              <p className="opacity-90">{a.rationale}</p>
              <p className="text-[10px] opacity-75">
                {a.actor} · {formatRelativeTime(a.at)}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
    </WorkspaceSection>
  );
}

function ResolutionPanel({
  inv,
  canResolve,
  onResolve,
}: {
  inv: Investigation;
  canResolve: boolean;
  onResolve: (s: InvestigationStatus) => void;
}) {
  const disabled = !canResolve;
  return (
    <WorkspaceSection id="resolution" title="Resolution">
      <p className="text-[11px] text-muted-foreground">
        Simulate a resolution to preview downstream state. Terminal statuses cannot be reverted in
        the session.
      </p>
      <div className="mt-2 flex flex-col gap-1.5">
        <ResolveButton
          disabled={disabled}
          onClick={() => onResolve("resolved_action_taken")}
          icon={<ShieldCheck aria-hidden className="size-3.5 text-emerald-600" />}
          label="Resolve — action taken"
        />
        <ResolveButton
          disabled={disabled}
          onClick={() => onResolve("resolved_no_action")}
          icon={<Info aria-hidden className="size-3.5 text-sky-600" />}
          label="Resolve — no action"
        />
        <ResolveButton
          disabled={disabled}
          onClick={() => onResolve("closed_duplicate")}
          icon={<Users aria-hidden className="size-3.5 text-muted-foreground" />}
          label="Close as duplicate"
        />
      </div>
      {disabled ? (
        <p className="mt-2 rounded bg-muted/30 px-2 py-1 text-[11px] text-muted-foreground">
          Requires risk.resolve permission.
        </p>
      ) : null}
    </WorkspaceSection>
  );
}

function ResolveButton({
  disabled,
  onClick,
  icon,
  label,
}: {
  disabled: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-2 text-xs font-medium hover:bg-accent disabled:opacity-50"
    >
      {icon}
      {label}
    </button>
  );
}

function SummaryPanel({ inv }: { inv: Investigation }) {
  return (
    <WorkspaceSection id="summary" title="Summary">
      <p className="text-xs text-foreground">{inv.summary}</p>
      <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
        <li>Signals: {inv.signals.length}</li>
        <li>Evidence: {inv.evidence.length}</li>
        <li>Related users: {inv.relatedUserIds.length}</li>
        <li>Related cases: {inv.relatedCaseIds.length}</li>
        <li>Related orgs: {inv.relatedOrganizationIds.length}</li>
        <li>Notes: {inv.notes.length}</li>
      </ul>
    </WorkspaceSection>
  );
}

// =====================================================================
function sessionChangeSummary(
  session: ReturnType<typeof useInvestigationSession>,
  invId: string,
): string[] {
  const changes: string[] = [];
  if ((session.state.notes[invId]?.length ?? 0) > 0)
    changes.push(`${session.state.notes[invId].length} internal note(s)`);
  if ((session.state.selectedEvidence[invId]?.size ?? 0) > 0)
    changes.push(`${session.state.selectedEvidence[invId].size} evidence selection(s)`);
  if (session.state.duplicateDecisions[invId]) changes.push("Duplicate review decision");
  if (session.state.statusOverride[invId]) changes.push("Simulated status change");
  if ((session.state.preparedActions[invId]?.length ?? 0) > 0)
    changes.push(`${session.state.preparedActions[invId].length} prepared action(s)`);
  return changes;
}

// Force TS to consider the imports used even if not referenced above.
export const __ensureImports = { mockInvestigations, FileWarning, ShieldAlert, AlertTriangle };
