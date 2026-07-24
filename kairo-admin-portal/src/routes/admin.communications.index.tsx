import { useMemo, useState } from "react";
import { Link, createFileRoute } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowRight,
  Ban,
  CheckCircle2,
  Clock,
  FileWarning,
  Inbox,
  Mail,
  MessageCircleQuestion,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import { AdminSearchField } from "@/features/admin/components/search-field";
import { FilterBar, FilterMultiSelect } from "@/features/admin/components/filter-bar";
import { SectionHeader } from "@/features/admin/components/section-header";
import { EmptyState } from "@/features/admin/components/states";
import { WorkspaceSection } from "@/features/admin/components/workspace-section";
import { useAdminAccess } from "@/features/admin/auth/admin-access";
import { hasPermission } from "@/features/admin/workflow/permissions";
import { formatRelativeTime } from "@/features/admin/lib/format";
import {
  COMMUNICATION_CHANNEL_LABEL,
  COMMUNICATION_STATUS_LABEL,
  COMMUNICATION_TYPE_LABEL,
  FAILURE_REASON_LABEL,
  FAILURE_RECOMMENDED_ACTION,
  getCommunicationMetrics,
  isFailedStatus,
  mockCommunications,
  mockTemplates,
  type Communication,
  type CommunicationChannel,
  type CommunicationStatus,
  type CommunicationType,
  type TemplateKey,
} from "@/features/admin/data/communications";
import {
  ALL_ASSIGNEES,
  mockVerificationCases,
  VERIFICATION_TYPE_LABEL,
  type Assignee,
  type VerificationType,
} from "@/features/admin/data/verifications";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/admin/communications/")({
  head: () => ({
    meta: [
      { title: "Communications — Kairo Admin" },
      {
        name: "description",
        content:
          "Global monitoring of Kairo verification outreach, delivery, follow-ups and employer responses.",
      },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  component: CommunicationsCenterPage,
});

type Tab = "all" | "followups" | "failed" | "responses" | "templates";

function CommunicationsCenterPage() {
  const { admin } = useAdminAccess();
  const permissions = admin?.permissions ?? [];
  const canView = hasPermission(permissions, "communications.view");

  const [tab, setTab] = useState<Tab>("all");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<Set<string>>(new Set());
  const [channelFilter, setChannelFilter] = useState<Set<string>>(new Set());
  const [typeFilter, setTypeFilter] = useState<Set<string>>(new Set());
  const [templateFilter, setTemplateFilter] = useState<Set<string>>(new Set());
  const [assigneeFilter, setAssigneeFilter] = useState<Set<string>>(new Set());
  const [verificationTypeFilter, setVerificationTypeFilter] = useState<Set<string>>(new Set());
  const [dateWindow, setDateWindow] = useState<"any" | "24h" | "7d" | "30d">("any");
  const [followUpDue, setFollowUpDue] = useState<"any" | "today" | "overdue">("any");
  const [failedOnly, setFailedOnly] = useState(false);
  const [awaitingOnly, setAwaitingOnly] = useState(false);

  const metrics = useMemo(() => getCommunicationMetrics(), []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const now = Date.now();
    const window =
      dateWindow === "24h"
        ? 86_400_000
        : dateWindow === "7d"
          ? 7 * 86_400_000
          : dateWindow === "30d"
            ? 30 * 86_400_000
            : Infinity;
    return mockCommunications.filter((c) => {
      if (q) {
        const haystack = [
          c.reference,
          c.id,
          c.candidateName,
          c.candidateId,
          c.organizationName,
          c.organizationId,
          c.contactName,
          c.contactEmailMasked,
          c.caseId,
          c.caseReference,
          c.template,
          c.subject,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      if (statusFilter.size && !statusFilter.has(c.status)) return false;
      if (channelFilter.size && !channelFilter.has(c.channel)) return false;
      if (typeFilter.size && !typeFilter.has(c.type)) return false;
      if (templateFilter.size && !templateFilter.has(c.template)) return false;
      if (assigneeFilter.size && !assigneeFilter.has(c.assignedReviewer)) return false;
      if (failedOnly && !isFailedStatus(c.status)) return false;
      if (awaitingOnly && !c.awaitingResponse) return false;
      if (dateWindow !== "any" && now - new Date(c.sentAt).getTime() > window) return false;
      if (followUpDue !== "any") {
        if (!c.nextFollowUpAt) return false;
        const due = new Date(c.nextFollowUpAt).getTime();
        if (followUpDue === "today" && !isSameDay(due, now)) return false;
        if (followUpDue === "overdue" && due > now) return false;
      }
      if (verificationTypeFilter.size) {
        const caseVt = getVerificationTypeForCase(c.caseId);
        if (!caseVt || !verificationTypeFilter.has(caseVt)) return false;
      }
      return true;
    });
  }, [
    query,
    statusFilter,
    channelFilter,
    typeFilter,
    templateFilter,
    assigneeFilter,
    verificationTypeFilter,
    dateWindow,
    followUpDue,
    failedOnly,
    awaitingOnly,
  ]);

  const activeCount =
    [
      statusFilter,
      channelFilter,
      typeFilter,
      templateFilter,
      assigneeFilter,
      verificationTypeFilter,
    ].reduce((n, s) => n + s.size, 0) +
    (dateWindow !== "any" ? 1 : 0) +
    (followUpDue !== "any" ? 1 : 0) +
    (failedOnly ? 1 : 0) +
    (awaitingOnly ? 1 : 0);

  if (!canView) {
    return (
      <div className="mx-auto max-w-3xl">
        <EmptyState
          title="No access"
          description="Your role does not include the communications.view permission."
        />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-foreground">Communications</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Operational monitoring of every verification message. No sending — this is a read +
            review surface.
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-border bg-muted/40 px-2 py-1 text-[11px] text-muted-foreground">
          <ShieldAlert aria-hidden className="size-3.5" /> Session-only workspace — no real emails
          are sent.
        </span>
      </header>

      {/* Metrics */}
      <section aria-labelledby="comm-metrics">
        <h2 id="comm-metrics" className="sr-only">
          Communications overview
        </h2>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
          <MetricTile icon={Mail} label="Total" value={metrics.total} />
          <MetricTile icon={Clock} label="Pending" value={metrics.pending} />
          <MetricTile icon={CheckCircle2} label="Delivered" value={metrics.delivered} tone="good" />
          <MetricTile
            icon={MessageCircleQuestion}
            label="Awaiting response"
            value={metrics.awaitingResponse}
          />
          <MetricTile icon={XCircle} label="Failed" value={metrics.failed} tone="bad" />
          <MetricTile icon={FileWarning} label="Bounced" value={metrics.bounced} tone="bad" />
          <MetricTile
            icon={AlertTriangle}
            label="Complaints"
            value={metrics.complaints}
            tone="bad"
          />
          <MetricTile icon={Inbox} label="Follow-ups due today" value={metrics.followUpsDueToday} />
        </div>
      </section>

      {/* Tabs */}
      <nav
        aria-label="Communications sections"
        className="flex flex-wrap gap-1 border-b border-border"
      >
        {(
          [
            ["all", "All communications"],
            ["followups", "Follow-up center"],
            ["failed", "Failed"],
            ["responses", "Employer responses"],
            ["templates", "Template library"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            aria-current={tab === key ? "page" : undefined}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-xs font-medium transition-colors",
              tab === key
                ? "border-foreground text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {label}
          </button>
        ))}
      </nav>

      {tab === "templates" ? (
        <TemplatesTab />
      ) : (
        <>
          {/* Search + filters (hidden on templates) */}
          <div className="flex flex-col gap-2">
            <AdminSearchField
              value={query}
              onChange={setQuery}
              placeholder="Search candidate, org, contact, email, case, template…"
              ariaLabel="Search communications"
              className="max-w-xl"
            />
            <FilterBar
              activeCount={activeCount}
              onClear={() => {
                setStatusFilter(new Set());
                setChannelFilter(new Set());
                setTypeFilter(new Set());
                setTemplateFilter(new Set());
                setAssigneeFilter(new Set());
                setVerificationTypeFilter(new Set());
                setDateWindow("any");
                setFollowUpDue("any");
                setFailedOnly(false);
                setAwaitingOnly(false);
              }}
            >
              <FilterMultiSelect
                label="Status"
                options={STATUS_OPTIONS}
                selected={statusFilter}
                onChange={setStatusFilter}
              />
              <FilterMultiSelect
                label="Channel"
                options={CHANNEL_OPTIONS}
                selected={channelFilter}
                onChange={setChannelFilter}
              />
              <FilterMultiSelect
                label="Type"
                options={TYPE_OPTIONS}
                selected={typeFilter}
                onChange={setTypeFilter}
              />
              <FilterMultiSelect
                label="Verification"
                options={VERIFICATION_TYPE_OPTIONS}
                selected={verificationTypeFilter}
                onChange={setVerificationTypeFilter}
              />
              <FilterMultiSelect
                label="Template"
                options={TEMPLATE_OPTIONS}
                selected={templateFilter}
                onChange={setTemplateFilter}
              />
              <FilterMultiSelect
                label="Reviewer"
                options={ASSIGNEE_OPTIONS}
                selected={assigneeFilter}
                onChange={setAssigneeFilter}
              />
              <SelectPill
                label="Date"
                value={dateWindow}
                onChange={(v) => setDateWindow(v as typeof dateWindow)}
                options={[
                  ["any", "Any"],
                  ["24h", "Last 24h"],
                  ["7d", "Last 7d"],
                  ["30d", "Last 30d"],
                ]}
              />
              <SelectPill
                label="Follow-up"
                value={followUpDue}
                onChange={(v) => setFollowUpDue(v as typeof followUpDue)}
                options={[
                  ["any", "Any"],
                  ["today", "Due today"],
                  ["overdue", "Overdue"],
                ]}
              />
              <TogglePill
                label="Failed only"
                active={failedOnly}
                onToggle={() => setFailedOnly((v) => !v)}
              />
              <TogglePill
                label="Awaiting response"
                active={awaitingOnly}
                onToggle={() => setAwaitingOnly((v) => !v)}
              />
            </FilterBar>
          </div>

          {tab === "all" && <CommunicationTable rows={filtered} />}
          {tab === "followups" && (
            <FollowUpCenter rows={filtered.filter((r) => r.nextFollowUpAt)} />
          )}
          {tab === "failed" && (
            <FailedCommunications
              rows={filtered.filter((r) => isFailedStatus(r.status) || r.failures.length > 0)}
            />
          )}
          {tab === "responses" && (
            <EmployerResponsesTab rows={filtered.filter((r) => r.responses.length > 0)} />
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------
// Metric tile
// ---------------------------------------------------------------------
function MetricTile({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Mail;
  label: string;
  value: number;
  tone?: "good" | "bad";
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        <Icon
          aria-hidden
          className={cn(
            "size-3.5",
            tone === "good" && "text-emerald-600",
            tone === "bad" && "text-rose-600",
          )}
        />
        <span className="truncate">{label}</span>
      </div>
      <p className="mt-1 text-lg font-semibold tabular-nums text-foreground">{value}</p>
    </div>
  );
}

// ---------------------------------------------------------------------
// Communication table (all)
// ---------------------------------------------------------------------
function CommunicationTable({ rows }: { rows: Communication[] }) {
  if (rows.length === 0) return <EmptyState title="No communications match your filters." />;
  return (
    <>
      {/* Desktop table */}
      <div className="hidden overflow-x-auto rounded-lg border border-border bg-card md:block">
        <table
          className="w-full min-w-[1080px] border-separate border-spacing-0 text-left text-sm"
          aria-label="Communications"
        >
          <thead>
            <tr className="bg-muted/60 text-xs uppercase tracking-wide text-muted-foreground">
              <th className="border-b border-border px-3 py-2 font-medium">Status</th>
              <th className="border-b border-border px-3 py-2 font-medium">Candidate</th>
              <th className="border-b border-border px-3 py-2 font-medium">Organization</th>
              <th className="border-b border-border px-3 py-2 font-medium">Contact</th>
              <th className="border-b border-border px-3 py-2 font-medium">Channel</th>
              <th className="border-b border-border px-3 py-2 font-medium">Template</th>
              <th className="border-b border-border px-3 py-2 font-medium">Case</th>
              <th className="border-b border-border px-3 py-2 font-medium">Sent</th>
              <th className="border-b border-border px-3 py-2 font-medium">Last event</th>
              <th className="border-b border-border px-3 py-2 font-medium">Next follow-up</th>
              <th className="border-b border-border px-3 py-2 font-medium">Attention</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const last = r.events[r.events.length - 1];
              return (
                <tr key={r.id} className="hover:bg-accent/40">
                  <td className="border-b border-border px-3 py-2 align-top">
                    <Link
                      to="/admin/communications/$communicationId"
                      params={{ communicationId: r.id }}
                      className="inline-block"
                    >
                      <CommStatusBadge status={r.status} />
                    </Link>
                  </td>
                  <td className="border-b border-border px-3 py-2 align-top text-sm">
                    <div className="font-medium text-foreground">{r.candidateName ?? "—"}</div>
                    <div className="text-xs text-muted-foreground">{r.reference}</div>
                  </td>
                  <td className="border-b border-border px-3 py-2 align-top text-sm text-foreground">
                    {r.organizationName ?? "—"}
                  </td>
                  <td className="border-b border-border px-3 py-2 align-top text-xs text-muted-foreground">
                    <div>{r.contactName ?? "—"}</div>
                    <div className="font-mono">{r.contactEmailMasked}</div>
                  </td>
                  <td className="border-b border-border px-3 py-2 align-top text-xs uppercase tracking-wide text-muted-foreground">
                    {COMMUNICATION_CHANNEL_LABEL[r.channel]}
                  </td>
                  <td className="border-b border-border px-3 py-2 align-top text-xs text-muted-foreground">
                    {templateName(r.template)}{" "}
                    <span className="opacity-60">{r.templateVersion}</span>
                  </td>
                  <td className="border-b border-border px-3 py-2 align-top text-xs">
                    {r.caseId ? (
                      <Link
                        to="/admin/verifications/$caseId"
                        params={{ caseId: r.caseId }}
                        className="text-foreground underline-offset-2 hover:underline"
                      >
                        {r.caseReference}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="border-b border-border px-3 py-2 align-top text-xs text-muted-foreground">
                    {formatRelativeTime(r.sentAt)}
                  </td>
                  <td className="border-b border-border px-3 py-2 align-top text-xs text-muted-foreground">
                    {last ? formatRelativeTime(last.at) : "—"}
                  </td>
                  <td className="border-b border-border px-3 py-2 align-top text-xs text-muted-foreground">
                    {r.nextFollowUpAt ? formatRelativeTime(r.nextFollowUpAt) : "—"}
                  </td>
                  <td className="border-b border-border px-3 py-2 align-top text-xs">
                    {r.attentionTags.length ? (
                      <div className="flex flex-wrap gap-1">
                        {r.attentionTags.map((t) => (
                          <span
                            key={t}
                            className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-900 ring-1 ring-inset ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60"
                          >
                            {t.replaceAll("_", " ")}
                          </span>
                        ))}
                      </div>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <ul className="grid grid-cols-1 gap-2 md:hidden">
        {rows.map((r) => (
          <li key={r.id}>
            <Link
              to="/admin/communications/$communicationId"
              params={{ communicationId: r.id }}
              className="block rounded-lg border border-border bg-card p-3 hover:bg-accent/40"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-foreground">
                    {r.candidateName}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {r.organizationName} · {templateName(r.template)}
                  </p>
                </div>
                <CommStatusBadge status={r.status} />
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                <span>Sent {formatRelativeTime(r.sentAt)}</span>
                {r.nextFollowUpAt && <span>Next {formatRelativeTime(r.nextFollowUpAt)}</span>}
                {r.caseReference && <span>{r.caseReference}</span>}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}

// ---------------------------------------------------------------------
// Follow-up center
// ---------------------------------------------------------------------
function FollowUpCenter({ rows }: { rows: Communication[] }) {
  const now = Date.now();
  if (rows.length === 0)
    return (
      <EmptyState
        title="No follow-ups scheduled."
        description="When outreach is awaiting a response, upcoming reminders appear here."
      />
    );
  return (
    <WorkspaceSection
      title="Follow-up center"
      description="Communications requiring reviewer action."
    >
      <ul className="divide-y divide-border">
        {rows.map((r) => {
          const due = r.nextFollowUpAt ? new Date(r.nextFollowUpAt).getTime() : null;
          const overdue = due != null && due < now;
          const days = Math.max(0, Math.round((now - new Date(r.sentAt).getTime()) / 86_400_000));
          return (
            <li key={r.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <CommStatusBadge status={r.status} />
                  <Link
                    to="/admin/communications/$communicationId"
                    params={{ communicationId: r.id }}
                    className="text-sm font-medium text-foreground underline-offset-2 hover:underline"
                  >
                    {r.candidateName} · {r.organizationName}
                  </Link>
                </div>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {days}d since outreach · attempt #{r.attemptCount} · next reminder{" "}
                  {r.nextFollowUpAt ? formatRelativeTime(r.nextFollowUpAt) : "—"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Recommended: {recommendedFollowUpAction(r)}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {overdue && (
                  <span className="rounded bg-rose-50 px-1.5 py-0.5 text-[10px] font-semibold text-rose-900 ring-1 ring-inset ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200">
                    Overdue
                  </span>
                )}
                <Link
                  to="/admin/communications/$communicationId"
                  params={{ communicationId: r.id }}
                  className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs font-medium text-foreground hover:bg-accent"
                >
                  Open <ArrowRight aria-hidden className="size-3" />
                </Link>
              </div>
            </li>
          );
        })}
      </ul>
    </WorkspaceSection>
  );
}

// ---------------------------------------------------------------------
// Failed communications
// ---------------------------------------------------------------------
function FailedCommunications({ rows }: { rows: Communication[] }) {
  if (rows.length === 0) return <EmptyState title="No failed communications." />;
  return (
    <WorkspaceSection
      title="Failed communications"
      description="Bounces, complaints, suppressions and delivery failures."
    >
      <ul className="divide-y divide-border">
        {rows.map((r) => {
          const failure = r.failures[0];
          return (
            <li key={r.id} className="py-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <CommStatusBadge status={r.status} />
                    <Link
                      to="/admin/communications/$communicationId"
                      params={{ communicationId: r.id }}
                      className="text-sm font-medium text-foreground underline-offset-2 hover:underline"
                    >
                      {r.candidateName} · {r.organizationName}
                    </Link>
                  </div>
                  {failure && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">
                        {FAILURE_REASON_LABEL[failure.reason]}
                      </span>{" "}
                      · {failure.detail}
                    </p>
                  )}
                  {failure && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      Recommended action: {FAILURE_RECOMMENDED_ACTION[failure.reason]}
                    </p>
                  )}
                </div>
                <Link
                  to="/admin/communications/$communicationId"
                  params={{ communicationId: r.id }}
                  className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs font-medium text-foreground hover:bg-accent"
                >
                  Review <ArrowRight aria-hidden className="size-3" />
                </Link>
              </div>
            </li>
          );
        })}
      </ul>
    </WorkspaceSection>
  );
}

// ---------------------------------------------------------------------
// Employer responses
// ---------------------------------------------------------------------
function EmployerResponsesTab({ rows }: { rows: Communication[] }) {
  if (rows.length === 0) return <EmptyState title="No employer responses recorded." />;
  return (
    <WorkspaceSection title="Employer responses" description="Verifier outcomes across all cases.">
      <ul className="divide-y divide-border">
        {rows.map((r) => {
          const resp = r.responses[0];
          return (
            <li key={r.id} className="py-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
                        resp.outcome === "confirmed" &&
                          "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200",
                        resp.outcome === "denied" &&
                          "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200",
                        resp.outcome === "partial" &&
                          "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200",
                        resp.outcome === "unable" &&
                          "bg-zinc-100 text-zinc-800 ring-zinc-200 dark:bg-zinc-800/60 dark:text-zinc-200",
                      )}
                    >
                      {resp.outcome.toUpperCase()}
                    </span>
                    <span className="text-sm font-medium text-foreground">
                      {r.organizationName}
                    </span>
                    <span className="text-xs text-muted-foreground">· {r.contactEmailMasked}</span>
                  </div>
                  <p className="mt-1 text-sm text-foreground">{resp.body}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {formatRelativeTime(resp.at)} · Candidate {r.candidateName}
                    {resp.actionRequired && (
                      <>
                        {" "}
                        · <span className="text-foreground">Action: {resp.actionRequired}</span>
                      </>
                    )}
                  </p>
                </div>
                {r.caseId && (
                  <Link
                    to="/admin/verifications/$caseId"
                    params={{ caseId: r.caseId }}
                    className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border px-2 py-1 text-xs font-medium text-foreground hover:bg-accent"
                  >
                    Open case <ArrowRight aria-hidden className="size-3" />
                  </Link>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </WorkspaceSection>
  );
}

// ---------------------------------------------------------------------
// Templates tab
// ---------------------------------------------------------------------
function TemplatesTab() {
  return (
    <div className="flex flex-col gap-3">
      <SectionHeader
        title="Template library"
        description="Read-only catalog. Editing is not available in the admin portal."
      />
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {mockTemplates.map((t) => (
          <article key={t.key} className="rounded-lg border border-border bg-card p-4">
            <header className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold text-foreground">{t.name}</h3>
                <p className="text-xs text-muted-foreground">
                  {COMMUNICATION_TYPE_LABEL[t.category]} · {COMMUNICATION_CHANNEL_LABEL[t.channel]}
                </p>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                  {t.version}
                </span>
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset",
                    t.status === "active" &&
                      "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200",
                    t.status === "draft" &&
                      "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200",
                    t.status === "deprecated" &&
                      "bg-zinc-100 text-zinc-800 ring-zinc-200 dark:bg-zinc-800/60 dark:text-zinc-200",
                  )}
                >
                  {t.status}
                </span>
              </div>
            </header>
            <div className="mt-3 rounded-md border border-border bg-muted/30 p-3">
              <p className="text-xs font-medium text-muted-foreground">Subject preview</p>
              <p className="mt-0.5 text-sm text-foreground">{t.subjectPreview}</p>
              <p className="mt-2 text-xs font-medium text-muted-foreground">Body preview</p>
              <pre className="mt-0.5 whitespace-pre-wrap font-sans text-xs text-foreground">
                {t.bodyPreview}
              </pre>
            </div>
            <div className="mt-3">
              <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Variables
              </p>
              <div className="mt-1 flex flex-wrap gap-1">
                {t.variables.map((v) => (
                  <code
                    key={v}
                    className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-foreground"
                  >{`{{${v}}}`}</code>
                ))}
              </div>
            </div>
          </article>
        ))}
      </div>
      <div className="rounded-md border border-dashed border-border bg-card/50 p-3">
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Ban aria-hidden className="size-3.5" /> Template editing is intentionally not available
          in this workspace.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------
export function CommStatusBadge({
  status,
  className,
}: {
  status: CommunicationStatus;
  className?: string;
}) {
  const tone: Record<CommunicationStatus, string> = {
    pending: "bg-zinc-100 text-zinc-800 ring-zinc-200 dark:bg-zinc-800/60 dark:text-zinc-200",
    queued: "bg-sky-50 text-sky-900 ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200",
    delivered:
      "bg-indigo-50 text-indigo-900 ring-indigo-200 dark:bg-indigo-950/40 dark:text-indigo-200",
    opened:
      "bg-violet-50 text-violet-900 ring-violet-200 dark:bg-violet-950/40 dark:text-violet-200",
    awaiting_response:
      "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200",
    responded:
      "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200",
    failed: "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200",
    bounced: "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200",
    complaint: "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200",
    suppressed: "bg-zinc-100 text-zinc-800 ring-zinc-200 dark:bg-zinc-800/60 dark:text-zinc-200",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        tone[status],
        className,
      )}
    >
      <span aria-hidden className="size-1.5 rounded-full bg-current opacity-70" />
      {COMMUNICATION_STATUS_LABEL[status]}
    </span>
  );
}

function SelectPill({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
}) {
  return (
    <label className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-2 text-xs font-medium">
      <span className="text-muted-foreground">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-full bg-transparent text-foreground focus:outline-none"
      >
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </label>
  );
}
function TogglePill({
  label,
  active,
  onToggle,
}: {
  label: string;
  active: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-md border px-2 text-xs font-medium",
        active
          ? "border-foreground bg-foreground text-background"
          : "border-border bg-background text-foreground hover:bg-accent",
      )}
    >
      {label}
    </button>
  );
}

function templateName(k: TemplateKey) {
  return mockTemplates.find((t) => t.key === k)?.name ?? k;
}

function isSameDay(a: number, b: number) {
  const A = new Date(a);
  const B = new Date(b);
  return (
    A.getUTCFullYear() === B.getUTCFullYear() &&
    A.getUTCMonth() === B.getUTCMonth() &&
    A.getUTCDate() === B.getUTCDate()
  );
}

function recommendedFollowUpAction(c: Communication): string {
  if (isFailedStatus(c.status)) return "Resolve failure and use alternative approved contact.";
  if (c.attemptCount >= 3) return "Escalate case — attempt limit approaching.";
  if (c.awaitingResponse) return "Wait for scheduled reminder or manually contact organization.";
  return "Monitor — no action required yet.";
}

const CASE_TYPE_BY_ID = new Map(mockVerificationCases.map((c) => [c.id, c.verificationType]));
function getVerificationTypeForCase(caseId?: string): VerificationType | null {
  if (!caseId) return null;
  return CASE_TYPE_BY_ID.get(caseId) ?? null;
}

// ---------------------------------------------------------------------
// Filter option lists
// ---------------------------------------------------------------------
const STATUS_OPTIONS = (
  Object.entries(COMMUNICATION_STATUS_LABEL) as [CommunicationStatus, string][]
).map(([v, l]) => ({ value: v, label: l }));
const CHANNEL_OPTIONS = (
  Object.entries(COMMUNICATION_CHANNEL_LABEL) as [CommunicationChannel, string][]
).map(([v, l]) => ({ value: v, label: l }));
const TYPE_OPTIONS = (
  Object.entries(COMMUNICATION_TYPE_LABEL) as [CommunicationType, string][]
).map(([v, l]) => ({ value: v, label: l }));
const TEMPLATE_OPTIONS = mockTemplates.map((t) => ({ value: t.key, label: t.name }));
const ASSIGNEE_OPTIONS: { value: string; label: string }[] = (
  ALL_ASSIGNEES as readonly Assignee[]
).map((a) => ({ value: a, label: a }));
const VERIFICATION_TYPE_OPTIONS = (
  Object.entries(VERIFICATION_TYPE_LABEL) as [VerificationType, string][]
).map(([v, l]) => ({ value: v, label: l }));
