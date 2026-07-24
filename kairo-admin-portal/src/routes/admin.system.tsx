/**
 * /admin/system — System Operations & Platform Control Center.
 *
 * Internal observability + control preparation surface. All values are
 * deterministic mock data. No infrastructure is actually mutated here.
 */
import { useMemo, useState, type ReactNode } from "react";
import { Link, createFileRoute, useRouter } from "@tanstack/react-router";
import { toast } from "sonner";
import {
  Activity,
  AlertTriangle,
  BadgeInfo,
  Bell,
  CheckCircle2,
  ChevronRight,
  Clock,
  Copy,
  Database,
  ExternalLink,
  FileClock,
  Flag,
  Info,
  KeySquare,
  Mail,
  MessageSquare,
  Rocket,
  Search,
  Server,
  Shield,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  Smartphone,
  X,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { EmptyState } from "@/features/admin/components/states";
import { AdminSearchField } from "@/features/admin/components/search-field";
import { FilterBar, FilterMultiSelect } from "@/features/admin/components/filter-bar";
import { UnsavedChangesDialog } from "@/features/admin/components/unsaved-changes-dialog";
import { useAdminAccess } from "@/features/admin/auth/admin-access";
import { hasPermission } from "@/features/admin/workflow/permissions";
import { formatRelativeTime } from "@/features/admin/lib/format";
import {
  useSystemSession,
  type JobActionKind,
  type SystemSession,
} from "@/features/admin/workflow/use-system-session";
import {
  ALERT_KIND_LABEL,
  ALERT_SEVERITY_LABEL,
  ALERT_STATUS_LABEL,
  AUDIT_RESOURCE_LABEL,
  FLAG_STATE_LABEL,
  JOB_STATUS_LABEL,
  JOB_TYPE_LABEL,
  MESSAGE_KIND_LABEL,
  MESSAGE_STATUS_LABEL,
  SERVICE_HEALTH_LABEL,
  getJobById,
  getSystemOverviewMetrics,
  mockAlerts,
  mockAuditEvents,
  mockBackgroundJobs,
  mockConfigReference,
  mockDeployments,
  mockFeatureFlags,
  mockMessageLogs,
  mockPlatformServices,
  type AlertRecord,
  type AlertStatus,
  type BackgroundJob,
  type FeatureFlag,
  type FlagState,
  type JobStatus,
  type JobType,
  type MessageChannel,
  type MessageKind,
  type MessageLog,
  type MessageStatus,
  type PlatformService,
  type ServiceHealthState,
} from "@/features/admin/data/system";

export const Route = createFileRoute("/admin/system")({
  head: () => ({
    meta: [
      { title: "System Operations — Kairo Admin" },
      {
        name: "description",
        content:
          "Platform health, background jobs, feature flags, delivery logs, audit trails and operational alerts.",
      },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  component: SystemOperationsPage,
});

// ---------------------------------------------------------------------
// Page shell + tabs
// ---------------------------------------------------------------------
type TabKey =
  "overview" | "health" | "jobs" | "flags" | "messaging" | "audit" | "alerts" | "configuration";

interface TabDef {
  key: TabKey;
  label: string;
  icon: typeof Activity;
  requires: string;
}

const TABS: TabDef[] = [
  { key: "overview", label: "Overview", icon: Activity, requires: "system.view" },
  { key: "health", label: "Platform Health", icon: Server, requires: "system.view" },
  { key: "jobs", label: "Background Jobs", icon: Zap, requires: "system.jobs.view" },
  { key: "flags", label: "Feature Flags", icon: Flag, requires: "system.flags.view" },
  { key: "messaging", label: "Email & SMS Logs", icon: Mail, requires: "system.messaging.view" },
  { key: "audit", label: "Audit Logs", icon: FileClock, requires: "system.audit.view" },
  { key: "alerts", label: "Alerts & Incidents", icon: Bell, requires: "system.view" },
  {
    key: "configuration",
    label: "Configuration Reference",
    icon: KeySquare,
    requires: "system.configuration.view",
  },
];

function SystemOperationsPage() {
  const { admin } = useAdminAccess();
  const permissions = admin?.permissions ?? [];
  const canView = hasPermission(permissions, "system.view");

  const session = useSystemSession(admin?.name ?? "Kairo Operator", admin?.role ?? "Admin");

  const [tab, setTab] = useState<TabKey>("overview");
  const router = useRouter();
  const [pendingHref, setPendingHref] = useState<string | null>(null);

  function tryNavigate(href: string) {
    if (session.hasUnsavedChanges) setPendingHref(href);
    else router.navigate({ to: href });
  }

  if (!canView) {
    return (
      <div className="mx-auto max-w-3xl">
        <EmptyState
          title="No access"
          description="Your role does not include the system.view permission."
        />
      </div>
    );
  }

  const availableTabs = TABS.filter(
    (t) => hasPermission(permissions, t.requires as never) || t.requires === "system.view",
  );

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-foreground">
            System Operations
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Monitor platform health, review background activity, inspect audit logs and prepare safe
            operational actions.
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-border bg-muted/40 px-2 py-1 text-[11px] text-muted-foreground">
          <ShieldOff aria-hidden className="size-3.5" /> Mock operational data — no production
          infrastructure is affected.
        </span>
      </header>

      {session.hasUnsavedChanges ? (
        <div className="rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/40 dark:text-sky-200">
          Session-only workspace — {session.unsavedSummary.join(", ")}. Changes are discarded on
          reload.
        </div>
      ) : null}

      {/* Tab strip */}
      <div className="border-b border-border">
        <div
          role="tablist"
          aria-label="System sections"
          className="-mb-px flex flex-wrap gap-x-0.5 gap-y-1 overflow-x-auto"
        >
          {availableTabs.map((t) => {
            const Icon = t.icon;
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                role="tab"
                aria-selected={active}
                aria-controls={`sys-panel-${t.key}`}
                id={`sys-tab-${t.key}`}
                onClick={() => setTab(t.key)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-t-md border-b-2 px-3 py-2 text-xs font-medium transition-colors",
                  active
                    ? "border-foreground text-foreground"
                    : "border-transparent text-muted-foreground hover:border-border hover:text-foreground",
                )}
              >
                <Icon aria-hidden className="size-3.5" />
                {t.label}
              </button>
            );
          })}
        </div>
      </div>

      <div
        role="tabpanel"
        id={`sys-panel-${tab}`}
        aria-labelledby={`sys-tab-${tab}`}
        className="min-w-0"
      >
        {tab === "overview" && <OverviewTab session={session} onOpenTab={setTab} />}
        {tab === "health" && <HealthTab />}
        {tab === "jobs" && <JobsTab session={session} permissions={permissions} />}
        {tab === "flags" && <FlagsTab session={session} permissions={permissions} />}
        {tab === "messaging" && <MessagingTab tryNavigate={tryNavigate} />}
        {tab === "audit" && <AuditTab tryNavigate={tryNavigate} />}
        {tab === "alerts" && <AlertsTab session={session} permissions={permissions} />}
        {tab === "configuration" && <ConfigurationTab />}
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
        changes={session.unsavedSummary}
      />
    </div>
  );
}

// ---------------------------------------------------------------------
// Overview tab
// ---------------------------------------------------------------------
function OverviewTab({
  session,
  onOpenTab,
}: {
  session: SystemSession;
  onOpenTab: (t: TabKey) => void;
}) {
  const m = useMemo(() => getSystemOverviewMetrics(), []);
  const openAlertsWithOverlay = session.alertsWithOverlay.filter(
    (a) => a.status !== "resolved",
  ).length;
  const deployment = mockDeployments[0];

  return (
    <div className="flex flex-col gap-6">
      <section aria-labelledby="ov-services">
        <h2
          id="ov-services"
          className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
        >
          Service health
        </h2>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">
          <OverviewHealthTile
            label="API"
            state={m.api}
            icon={Activity}
            onClick={() => onOpenTab("health")}
          />
          <OverviewHealthTile
            label="Database"
            state={m.database}
            icon={Database}
            onClick={() => onOpenTab("health")}
          />
          <OverviewHealthTile
            label="Redis"
            state={m.redis}
            icon={Zap}
            onClick={() => onOpenTab("health")}
          />
          <OverviewHealthTile
            label="Document storage"
            state={m.documentStorage}
            icon={Copy}
            onClick={() => onOpenTab("health")}
          />
          <OverviewHealthTile
            label="Email"
            state={m.emailDelivery}
            icon={Mail}
            onClick={() => onOpenTab("messaging")}
          />
          <OverviewHealthTile
            label="SMS"
            state={m.smsDelivery}
            icon={Smartphone}
            onClick={() => onOpenTab("messaging")}
          />
          <OverviewHealthTile
            label="Background jobs"
            state={m.backgroundJobs}
            icon={Server}
            onClick={() => onOpenTab("jobs")}
          />
        </div>
      </section>

      <section aria-labelledby="ov-numbers">
        <h2
          id="ov-numbers"
          className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
        >
          Activity (last 24 hours)
        </h2>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
          <OverviewMetricTile
            label="Failed jobs"
            value={m.failedJobs}
            tone="bad"
            icon={AlertTriangle}
            onClick={() => onOpenTab("jobs")}
          />
          <OverviewMetricTile
            label="Pending jobs"
            value={m.pendingJobs}
            tone="warn"
            icon={Clock}
            onClick={() => onOpenTab("jobs")}
          />
          <OverviewMetricTile
            label="Open alerts"
            value={openAlertsWithOverlay}
            tone={openAlertsWithOverlay > 0 ? "bad" : "good"}
            icon={Bell}
            onClick={() => onOpenTab("alerts")}
          />
          <OverviewMetricTile
            label="Audit events (24h)"
            value={m.auditEvents24h}
            icon={FileClock}
            onClick={() => onOpenTab("audit")}
          />
          <OverviewMetricTile
            label="Deployments (7d)"
            value={m.recentDeployments}
            icon={Rocket}
            onClick={() => onOpenTab("configuration")}
          />
        </div>
      </section>

      <section aria-labelledby="ov-deploy" className="rounded-lg border border-border bg-card p-4">
        <h2
          id="ov-deploy"
          className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
        >
          Recent deployment
        </h2>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-sm font-medium text-foreground">{deployment.version}</p>
            <p className="text-xs text-muted-foreground">
              {deployment.summary} — {deployment.environment} ·{" "}
              {formatRelativeTime(deployment.deployedAt)} · {deployment.deployedBy}
            </p>
          </div>
          <button
            type="button"
            onClick={() => onOpenTab("configuration")}
            className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs font-medium text-foreground hover:bg-accent"
          >
            View configuration <ChevronRight aria-hidden className="size-3" />
          </button>
        </div>
      </section>
    </div>
  );
}

function OverviewHealthTile({
  label,
  state,
  icon: Icon,
  onClick,
}: {
  label: string;
  state: ServiceHealthState;
  icon: typeof Activity;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex flex-col gap-1 rounded-lg border border-border bg-card p-3 text-left hover:bg-accent/40"
    >
      <span className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        <Icon aria-hidden className="size-3.5" />
        <span className="truncate">{label}</span>
      </span>
      <HealthBadge state={state} />
    </button>
  );
}

function OverviewMetricTile({
  label,
  value,
  icon: Icon,
  tone = "neutral",
  onClick,
}: {
  label: string;
  value: number;
  icon: typeof Activity;
  tone?: "good" | "warn" | "bad" | "neutral";
  onClick?: () => void;
}) {
  const toneCls =
    tone === "bad"
      ? "text-rose-700 dark:text-rose-300"
      : tone === "warn"
        ? "text-amber-700 dark:text-amber-300"
        : tone === "good"
          ? "text-emerald-700 dark:text-emerald-300"
          : "text-foreground";
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex flex-col gap-1 rounded-lg border border-border bg-card p-3 text-left hover:bg-accent/40"
    >
      <span className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        <Icon aria-hidden className="size-3.5" />
        <span className="truncate">{label}</span>
      </span>
      <span className={cn("text-xl font-semibold tabular-nums", toneCls)}>{value}</span>
    </button>
  );
}

// ---------------------------------------------------------------------
// Platform health tab
// ---------------------------------------------------------------------
function HealthTab() {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table
        className="w-full min-w-[900px] border-separate border-spacing-0 text-left text-sm"
        aria-label="Platform services"
      >
        <thead>
          <tr className="bg-muted/60 text-xs uppercase tracking-wide text-muted-foreground">
            <Th>Service</Th>
            <Th>Status</Th>
            <Th>Last checked</Th>
            <Th>Latency</Th>
            <Th>Error rate</Th>
            <Th>Dependency</Th>
            <Th>Recent incident / note</Th>
          </tr>
        </thead>
        <tbody>
          {mockPlatformServices.map((s: PlatformService) => (
            <tr key={s.id} className="hover:bg-accent/40">
              <Td className="font-medium text-foreground">{s.name}</Td>
              <Td>
                <HealthBadge state={s.state} />
              </Td>
              <Td className="text-xs text-muted-foreground">{formatRelativeTime(s.lastChecked)}</Td>
              <Td className="text-xs tabular-nums">
                {s.latencyMs === 0 ? "—" : `${s.latencyMs} ms`}
              </Td>
              <Td className="text-xs tabular-nums">{s.errorRatePct.toFixed(2)}%</Td>
              <Td className="text-xs text-muted-foreground">{s.dependency ?? "—"}</Td>
              <Td className="text-xs text-muted-foreground">{s.recentIncident ?? s.note ?? "—"}</Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------
// Jobs tab
// ---------------------------------------------------------------------
function JobsTab({ session, permissions }: { session: SystemSession; permissions: string[] }) {
  const canPrepare = hasPermission(permissions as never, "system.jobs.prepare_actions");
  const [query, setQuery] = useState("");
  const [statuses, setStatuses] = useState<Set<string>>(new Set());
  const [types, setTypes] = useState<Set<string>>(new Set());
  const [failedOnly, setFailedOnly] = useState(false);
  const [retryableOnly, setRetryableOnly] = useState(false);
  const [dateWindow, setDateWindow] = useState<"any" | "1h" | "24h" | "7d">("any");
  const [openJob, setOpenJob] = useState<string | null>(null);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const window =
      dateWindow === "1h"
        ? 3_600_000
        : dateWindow === "24h"
          ? 86_400_000
          : dateWindow === "7d"
            ? 7 * 86_400_000
            : Infinity;
    const now = Date.now();
    return mockBackgroundJobs.map(session.overlayJob).filter((j) => {
      if (q) {
        const hay = [
          j.id,
          j.reference,
          JOB_TYPE_LABEL[j.type],
          j.owner,
          j.lastError ?? "",
          ...j.related.map((r) => r.label),
        ]
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (statuses.size && !statuses.has(j.status)) return false;
      if (types.size && !types.has(j.type)) return false;
      if (failedOnly && j.status !== "failed") return false;
      if (retryableOnly && !j.retryable) return false;
      if (dateWindow !== "any" && now - new Date(j.createdAt).getTime() > window) return false;
      return true;
    });
  }, [query, statuses, types, failedOnly, retryableOnly, dateWindow, session]);

  const activeCount =
    statuses.size +
    types.size +
    (failedOnly ? 1 : 0) +
    (retryableOnly ? 1 : 0) +
    (dateWindow !== "any" ? 1 : 0);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <AdminSearchField
          value={query}
          onChange={setQuery}
          placeholder="Search job ID, type, related record, error…"
          ariaLabel="Search jobs"
          className="max-w-xl"
        />
        <FilterBar
          activeCount={activeCount}
          onClear={() => {
            setStatuses(new Set());
            setTypes(new Set());
            setFailedOnly(false);
            setRetryableOnly(false);
            setDateWindow("any");
          }}
        >
          <FilterMultiSelect
            label="Status"
            options={JOB_STATUS_OPTIONS}
            selected={statuses}
            onChange={setStatuses}
          />
          <FilterMultiSelect
            label="Type"
            options={JOB_TYPE_OPTIONS}
            selected={types}
            onChange={setTypes}
          />
          <SelectPill
            label="Date"
            value={dateWindow}
            onChange={(v) => setDateWindow(v as typeof dateWindow)}
            options={[
              ["any", "Any"],
              ["1h", "Last hour"],
              ["24h", "Last 24h"],
              ["7d", "Last 7d"],
            ]}
          />
          <TogglePill
            label="Failed only"
            active={failedOnly}
            onToggle={() => setFailedOnly((v) => !v)}
          />
          <TogglePill
            label="Retryable only"
            active={retryableOnly}
            onToggle={() => setRetryableOnly((v) => !v)}
          />
        </FilterBar>
      </div>

      {rows.length === 0 ? (
        <EmptyState title="No jobs match your filters." />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table
            className="w-full min-w-[1100px] border-separate border-spacing-0 text-left text-sm"
            aria-label="Background jobs"
          >
            <thead>
              <tr className="bg-muted/60 text-xs uppercase tracking-wide text-muted-foreground">
                <Th>Job</Th>
                <Th>Type</Th>
                <Th>Status</Th>
                <Th>Created</Th>
                <Th>Started</Th>
                <Th>Completed</Th>
                <Th>Attempts</Th>
                <Th>Owner</Th>
                <Th>Related</Th>
                <Th>Last error</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {rows.map((j) => (
                <tr key={j.id} className="hover:bg-accent/40">
                  <Td className="font-medium text-foreground">
                    <button
                      onClick={() => setOpenJob(j.id)}
                      className="text-left underline-offset-2 hover:underline"
                    >
                      {j.reference}
                    </button>
                    {j.preparedAction ? (
                      <div className="text-[10px] text-sky-700 dark:text-sky-300">
                        Prepared: {j.preparedAction}
                      </div>
                    ) : null}
                  </Td>
                  <Td className="text-xs text-muted-foreground">{JOB_TYPE_LABEL[j.type]}</Td>
                  <Td>
                    <JobStatusBadge status={j.status} />
                  </Td>
                  <Td className="text-xs text-muted-foreground">
                    {formatRelativeTime(j.createdAt)}
                  </Td>
                  <Td className="text-xs text-muted-foreground">
                    {j.startedAt ? formatRelativeTime(j.startedAt) : "—"}
                  </Td>
                  <Td className="text-xs text-muted-foreground">
                    {j.completedAt ? formatRelativeTime(j.completedAt) : "—"}
                  </Td>
                  <Td className="text-xs tabular-nums">
                    {j.attempts}/{j.maxAttempts}
                  </Td>
                  <Td className="text-xs text-muted-foreground">{j.owner}</Td>
                  <Td className="text-xs text-muted-foreground">
                    {j.related.length === 0 ? "—" : j.related.map((r) => r.label).join(", ")}
                  </Td>
                  <Td className="max-w-[280px] truncate text-xs text-rose-700 dark:text-rose-300">
                    {j.lastError ?? "—"}
                  </Td>
                  <Td>
                    <button
                      onClick={() => setOpenJob(j.id)}
                      className="text-xs font-medium text-foreground underline-offset-2 hover:underline"
                    >
                      Open
                    </button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {openJob ? (
        <JobDetailDrawer
          jobId={openJob}
          onClose={() => setOpenJob(null)}
          session={session}
          canPrepare={canPrepare}
        />
      ) : null}
    </div>
  );
}

function JobDetailDrawer({
  jobId,
  onClose,
  session,
  canPrepare,
}: {
  jobId: string;
  onClose: () => void;
  session: SystemSession;
  canPrepare: boolean;
}) {
  const [note, setNote] = useState("");
  const base = getJobById(jobId);
  if (!base) {
    return (
      <SlideOver onClose={onClose} title="Job not found">
        <EmptyState title="Unknown job" description="This job ID is not in the mock dataset." />
      </SlideOver>
    );
  }
  const job = session.overlayJob(base);
  const preps = session.jobActionsFor(job.id);

  function prepare(kind: JobActionKind, label: string) {
    session.prepareJobAction(job.id, job.reference, kind, note.trim() || undefined);
    setNote("");
    toast.success(`${label} (session-only)`);
  }

  return (
    <SlideOver onClose={onClose} title={`Job ${job.reference}`}>
      <div className="flex flex-col gap-4 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <JobStatusBadge status={job.status} />
          <span className="text-xs text-muted-foreground">
            {JOB_TYPE_LABEL[job.type]} · owner {job.owner}
          </span>
        </div>

        <Section title="Summary">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <DT>Created</DT>
            <DD>{formatRelativeTime(job.createdAt)}</DD>
            <DT>Started</DT>
            <DD>{job.startedAt ? formatRelativeTime(job.startedAt) : "—"}</DD>
            <DT>Completed</DT>
            <DD>{job.completedAt ? formatRelativeTime(job.completedAt) : "—"}</DD>
            <DT>Attempts</DT>
            <DD>
              {job.attempts} / {job.maxAttempts}
            </DD>
            <DT>Retry eligible</DT>
            <DD>{job.retryable ? "Yes" : "No"}</DD>
            <DT>Duration</DT>
            <DD>{job.durationMs ? `${(job.durationMs / 1000).toFixed(1)}s` : "—"}</DD>
          </dl>
        </Section>

        <Section title="Payload preview">
          <pre className="max-h-40 overflow-auto rounded bg-muted/60 p-2 text-[11px] text-foreground">
            {JSON.stringify(job.payloadPreview, null, 2)}
          </pre>
        </Section>

        {job.related.length > 0 && (
          <Section title="Related records">
            <ul className="flex flex-col gap-1 text-xs">
              {job.related.map((r) => (
                <li key={`${r.kind}-${r.id}`} className="flex items-center gap-1">
                  {r.linkTo ? (
                    <Link
                      to={r.linkTo}
                      className="inline-flex items-center gap-1 text-foreground underline-offset-2 hover:underline"
                    >
                      {r.label} <ExternalLink aria-hidden className="size-3" />
                    </Link>
                  ) : (
                    <span className="text-muted-foreground">{r.label}</span>
                  )}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {job.lastError && (
          <Section title="Error details">
            <p className="rounded bg-rose-50 px-2 py-1 text-xs text-rose-900 ring-1 ring-inset ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60">
              {job.lastError}
            </p>
          </Section>
        )}

        <Section title="Attempt history">
          {job.attemptHistory.length === 0 ? (
            <p className="text-xs text-muted-foreground">No attempts yet.</p>
          ) : (
            <ul className="flex flex-col gap-1 text-xs">
              {job.attemptHistory.map((a) => (
                <li
                  key={a.attempt}
                  className="flex items-start justify-between gap-2 rounded border border-border p-2"
                >
                  <div>
                    <p className="font-medium">
                      Attempt {a.attempt} — {a.outcome}
                    </p>
                    <p className="text-muted-foreground">
                      {formatRelativeTime(a.startedAt)} · {(a.durationMs / 1000).toFixed(1)}s
                    </p>
                    {a.error ? <p className="text-rose-700 dark:text-rose-300">{a.error}</p> : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Prepared operational actions">
          {preps.length === 0 ? (
            <p className="text-xs text-muted-foreground">Nothing prepared yet in this session.</p>
          ) : (
            <ul className="flex flex-col gap-1 text-xs">
              {preps.map((p) => (
                <li
                  key={p.id}
                  className="rounded border border-sky-200 bg-sky-50/60 px-2 py-1 text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/40 dark:text-sky-200"
                >
                  {session.labels.JOB_ACTION_LABEL[p.kind]} — {p.actor} · {formatRelativeTime(p.at)}
                  {p.note ? <div className="text-[11px] opacity-90">{p.note}</div> : null}
                </li>
              ))}
            </ul>
          )}
          {canPrepare ? (
            <div className="mt-2 flex flex-col gap-2">
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Optional operator note"
                aria-label="Operator note"
                rows={2}
                className="w-full rounded border border-border bg-background p-2 text-xs"
              />
              <div className="flex flex-wrap gap-1.5">
                <ActionBtn
                  onClick={() => prepare("retry", "Retry prepared")}
                  disabled={!job.retryable}
                  disabledReason={!job.retryable ? "Job not marked retryable" : undefined}
                >
                  Prepare retry
                </ActionBtn>
                <ActionBtn
                  onClick={() => prepare("cancel", "Cancellation prepared")}
                  disabled={job.status === "succeeded" || job.status === "cancelled"}
                  disabledReason={job.status === "succeeded" ? "Job already succeeded" : undefined}
                >
                  Prepare cancellation
                </ActionBtn>
                <ActionBtn onClick={() => prepare("reviewed", "Marked reviewed")}>
                  Mark reviewed
                </ActionBtn>
                <ActionBtn onClick={() => prepare("escalate", "Escalated")} tone="danger">
                  Escalate
                </ActionBtn>
              </div>
              <p className="text-[11px] text-muted-foreground">
                Actions are session-only. Nothing is actually rerun or cancelled.
              </p>
            </div>
          ) : (
            <p className="mt-2 text-[11px] text-muted-foreground">
              Your role does not include system.jobs.prepare_actions.
            </p>
          )}
        </Section>
      </div>
    </SlideOver>
  );
}

// ---------------------------------------------------------------------
// Feature flags tab
// ---------------------------------------------------------------------
function FlagsTab({ session, permissions }: { session: SystemSession; permissions: string[] }) {
  const canPrepare = hasPermission(permissions as never, "system.flags.prepare_changes");
  const [openFlag, setOpenFlag] = useState<string | null>(null);
  const flags = mockFeatureFlags.map(session.overlayFlag);

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <table
          className="w-full min-w-[1100px] border-separate border-spacing-0 text-left text-sm"
          aria-label="Feature flags"
        >
          <thead>
            <tr className="bg-muted/60 text-xs uppercase tracking-wide text-muted-foreground">
              <Th>Flag</Th>
              <Th>Environment</Th>
              <Th>State</Th>
              <Th>Rollout</Th>
              <Th>Owner</Th>
              <Th>Risk</Th>
              <Th>Last updated</Th>
              <Th>Dependencies</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {flags.map((f) => (
              <tr key={f.id} className="hover:bg-accent/40">
                <Td>
                  <div className="font-medium text-foreground">{f.name}</div>
                  <div className="text-[11px] text-muted-foreground">{f.description}</div>
                  <code className="text-[10px] text-muted-foreground">{f.key}</code>
                </Td>
                <Td className="text-xs capitalize text-muted-foreground">{f.environment}</Td>
                <Td>
                  <FlagStateBadge state={f.state} />
                </Td>
                <Td className="text-xs tabular-nums">
                  {f.state === "rollout" ? `${f.rolloutPct}%` : f.state === "on" ? "100%" : "0%"}
                </Td>
                <Td className="text-xs text-muted-foreground">{f.owner}</Td>
                <Td className="text-xs">
                  <RiskChip level={f.risk} />
                </Td>
                <Td className="text-xs text-muted-foreground">
                  {formatRelativeTime(f.lastUpdated)}
                </Td>
                <Td className="text-xs text-muted-foreground">
                  {f.dependencies.length === 0 ? "—" : f.dependencies.join(", ")}
                </Td>
                <Td>
                  <button
                    onClick={() => setOpenFlag(f.id)}
                    className="text-xs font-medium text-foreground underline-offset-2 hover:underline"
                  >
                    {canPrepare ? "Prepare change" : "Details"}
                  </button>
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {openFlag ? (
        <FlagChangeDialog
          flag={session.overlayFlag(mockFeatureFlags.find((f) => f.id === openFlag)!)}
          onClose={() => setOpenFlag(null)}
          onConfirm={(nextState, pct, note) => {
            session.prepareFlagChange(
              openFlag,
              mockFeatureFlags.find((f) => f.id === openFlag)!.name,
              nextState,
              pct,
              note,
            );
            toast.success("Feature flag change prepared (session-only)");
            setOpenFlag(null);
          }}
          canPrepare={canPrepare}
        />
      ) : null}
    </div>
  );
}

function FlagChangeDialog({
  flag,
  onClose,
  onConfirm,
  canPrepare,
}: {
  flag: FeatureFlag;
  onClose: () => void;
  onConfirm: (nextState: FlagState, pct: number, note?: string) => void;
  canPrepare: boolean;
}) {
  const [nextState, setNextState] = useState<FlagState>(flag.state);
  const [pct, setPct] = useState<number>(flag.rolloutPct);
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  return (
    <AlertDialog
      open
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Prepare change — {flag.name}</AlertDialogTitle>
          <AlertDialogDescription>
            This does not modify any real feature flag. It records a prepared change in your session
            workspace.
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="flex flex-col gap-3 text-sm">
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium">Next state</span>
            <select
              value={nextState}
              onChange={(e) => setNextState(e.target.value as FlagState)}
              disabled={!canPrepare}
              className="h-8 rounded border border-border bg-background px-2"
            >
              <option value="off">Off</option>
              <option value="on">On</option>
              <option value="rollout">Rollout</option>
            </select>
          </label>
          {nextState === "rollout" && (
            <label className="flex flex-col gap-1 text-xs">
              <span className="font-medium">Rollout percentage: {pct}%</span>
              <input
                type="range"
                min={0}
                max={100}
                step={5}
                value={pct}
                onChange={(e) => setPct(Number(e.target.value))}
                disabled={!canPrepare}
              />
            </label>
          )}
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium">Internal note (optional)</span>
            <textarea
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className="rounded border border-border bg-background p-2"
              disabled={!canPrepare}
            />
          </label>
          <label className="flex items-start gap-2 text-xs">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              className="mt-0.5"
              disabled={!canPrepare}
            />
            <span>
              I understand this is a session-only preparation and will not modify any real feature
              flag.
            </span>
          </label>
          {flag.risk === "critical" || flag.risk === "high" ? (
            <p className="rounded bg-amber-50 px-2 py-1 text-[11px] text-amber-900 ring-1 ring-inset ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60">
              This flag is marked <strong>{flag.risk}</strong> risk. Real changes require sign-off
              outside this UI.
            </p>
          ) : null}
        </div>

        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={!canPrepare || !confirmed}
            onClick={() =>
              onConfirm(
                nextState,
                nextState === "rollout" ? pct : nextState === "on" ? 100 : 0,
                note.trim() || undefined,
              )
            }
          >
            Prepare change
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

// ---------------------------------------------------------------------
// Messaging tab
// ---------------------------------------------------------------------
function MessagingTab({ tryNavigate }: { tryNavigate: (href: string) => void }) {
  const [query, setQuery] = useState("");
  const [channels, setChannels] = useState<Set<string>>(new Set());
  const [statuses, setStatuses] = useState<Set<string>>(new Set());
  const [kinds, setKinds] = useState<Set<string>>(new Set());
  const [providers, setProviders] = useState<Set<string>>(new Set());
  const [failedOnly, setFailedOnly] = useState(false);
  const [dateWindow, setDateWindow] = useState<"any" | "1h" | "24h" | "7d">("any");

  const providerOptions = useMemo(
    () =>
      Array.from(new Set(mockMessageLogs.map((m) => m.provider)))
        .sort()
        .map((p) => ({ value: p, label: p })),
    [],
  );

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const window =
      dateWindow === "1h"
        ? 3_600_000
        : dateWindow === "24h"
          ? 86_400_000
          : dateWindow === "7d"
            ? 7 * 86_400_000
            : Infinity;
    const now = Date.now();
    return mockMessageLogs.filter((m) => {
      if (q) {
        const hay = [
          m.reference,
          m.recipientMasked,
          m.provider,
          MESSAGE_KIND_LABEL[m.kind],
          m.failureReason ?? "",
          m.relatedUserId ?? "",
          m.relatedCaseId ?? "",
          m.relatedOrganizationId ?? "",
        ]
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (channels.size && !channels.has(m.channel)) return false;
      if (statuses.size && !statuses.has(m.status)) return false;
      if (kinds.size && !kinds.has(m.kind)) return false;
      if (providers.size && !providers.has(m.provider)) return false;
      if (
        failedOnly &&
        !(
          m.status === "failed" ||
          m.status === "bounced" ||
          m.status === "rejected" ||
          m.status === "spam_complaint"
        )
      )
        return false;
      if (dateWindow !== "any" && now - new Date(m.createdAt).getTime() > window) return false;
      return true;
    });
  }, [query, channels, statuses, kinds, providers, failedOnly, dateWindow]);

  const activeCount =
    channels.size +
    statuses.size +
    kinds.size +
    providers.size +
    (failedOnly ? 1 : 0) +
    (dateWindow !== "any" ? 1 : 0);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <AdminSearchField
          value={query}
          onChange={setQuery}
          placeholder="Search reference, recipient, provider, related record…"
          ariaLabel="Search messages"
          className="max-w-xl"
        />
        <FilterBar
          activeCount={activeCount}
          onClear={() => {
            setChannels(new Set());
            setStatuses(new Set());
            setKinds(new Set());
            setProviders(new Set());
            setFailedOnly(false);
            setDateWindow("any");
          }}
        >
          <FilterMultiSelect
            label="Channel"
            options={CHANNEL_OPTIONS}
            selected={channels}
            onChange={setChannels}
          />
          <FilterMultiSelect
            label="Status"
            options={MESSAGE_STATUS_OPTIONS}
            selected={statuses}
            onChange={setStatuses}
          />
          <FilterMultiSelect
            label="Type"
            options={MESSAGE_KIND_OPTIONS}
            selected={kinds}
            onChange={setKinds}
          />
          <FilterMultiSelect
            label="Provider"
            options={providerOptions}
            selected={providers}
            onChange={setProviders}
          />
          <SelectPill
            label="Date"
            value={dateWindow}
            onChange={(v) => setDateWindow(v as typeof dateWindow)}
            options={[
              ["any", "Any"],
              ["1h", "Last hour"],
              ["24h", "Last 24h"],
              ["7d", "Last 7d"],
            ]}
          />
          <TogglePill
            label="Failed only"
            active={failedOnly}
            onToggle={() => setFailedOnly((v) => !v)}
          />
        </FilterBar>
      </div>
      <p className="rounded border border-border bg-muted/40 px-2 py-1 text-[11px] text-muted-foreground">
        <BadgeInfo aria-hidden className="mr-1 inline size-3" /> Recipients are masked. OTP values,
        tokens and secrets are never displayed here.
      </p>

      {rows.length === 0 ? (
        <EmptyState title="No messages match your filters." />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table
            className="w-full min-w-[1100px] border-separate border-spacing-0 text-left text-sm"
            aria-label="Message logs"
          >
            <thead>
              <tr className="bg-muted/60 text-xs uppercase tracking-wide text-muted-foreground">
                <Th>Reference</Th>
                <Th>Type</Th>
                <Th>Channel</Th>
                <Th>Recipient</Th>
                <Th>Provider</Th>
                <Th>Status</Th>
                <Th>Created</Th>
                <Th>Delivered</Th>
                <Th>Failed reason</Th>
                <Th>Related</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.id} className="hover:bg-accent/40">
                  <Td className="font-medium text-foreground">{m.reference}</Td>
                  <Td className="text-xs text-muted-foreground">{MESSAGE_KIND_LABEL[m.kind]}</Td>
                  <Td className="text-xs capitalize">{m.channel}</Td>
                  <Td className="text-xs">
                    <code>{m.recipientMasked}</code>
                  </Td>
                  <Td className="text-xs text-muted-foreground">{m.provider}</Td>
                  <Td>
                    <MessageStatusBadge status={m.status} />
                  </Td>
                  <Td className="text-xs text-muted-foreground">
                    {formatRelativeTime(m.createdAt)}
                  </Td>
                  <Td className="text-xs text-muted-foreground">
                    {m.deliveredAt ? formatRelativeTime(m.deliveredAt) : "—"}
                  </Td>
                  <Td className="max-w-[260px] truncate text-xs text-rose-700 dark:text-rose-300">
                    {m.failureReason ?? "—"}
                  </Td>
                  <Td className="text-xs">
                    <RelatedLinks m={m} tryNavigate={tryNavigate} />
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function RelatedLinks({ m, tryNavigate }: { m: MessageLog; tryNavigate: (h: string) => void }) {
  const links: { label: string; href: string }[] = [];
  if (m.relatedUserId) links.push({ label: "User", href: `/admin/users/${m.relatedUserId}` });
  if (m.relatedCaseId)
    links.push({ label: "Case", href: `/admin/verifications/${m.relatedCaseId}` });
  if (m.relatedOrganizationId)
    links.push({ label: "Org", href: `/admin/registry/${m.relatedOrganizationId}` });
  if (links.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {links.map((l) => (
        <button
          key={l.href}
          onClick={() => tryNavigate(l.href)}
          className="rounded border border-border px-1.5 py-0.5 text-[10px] hover:bg-accent"
        >
          {l.label}
        </button>
      ))}
    </span>
  );
}

// ---------------------------------------------------------------------
// Audit tab
// ---------------------------------------------------------------------
function AuditTab({ tryNavigate }: { tryNavigate: (h: string) => void }) {
  const [query, setQuery] = useState("");
  const [resources, setResources] = useState<Set<string>>(new Set());
  const [actors, setActors] = useState<Set<string>>(new Set());
  const [results, setResults] = useState<Set<string>>(new Set());

  const actorOptions = useMemo(
    () =>
      Array.from(new Set(mockAuditEvents.map((e) => e.actor)))
        .sort()
        .map((a) => ({ value: a, label: a })),
    [],
  );

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return mockAuditEvents.filter((e) => {
      if (q) {
        const hay = [
          e.id,
          e.actor,
          e.action,
          e.resourceId,
          e.resourceLabel,
          e.reason ?? "",
          e.source,
        ]
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (resources.size && !resources.has(e.resourceKind)) return false;
      if (actors.size && !actors.has(e.actor)) return false;
      if (results.size && !results.has(e.result)) return false;
      return true;
    });
  }, [query, resources, actors, results]);

  const activeCount = resources.size + actors.size + results.size;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <AdminSearchField
          value={query}
          onChange={setQuery}
          placeholder="Search actor, action, resource ID…"
          ariaLabel="Search audit log"
          className="max-w-xl"
        />
        <FilterBar
          activeCount={activeCount}
          onClear={() => {
            setResources(new Set());
            setActors(new Set());
            setResults(new Set());
          }}
        >
          <FilterMultiSelect
            label="Resource"
            options={AUDIT_RESOURCE_OPTIONS}
            selected={resources}
            onChange={setResources}
          />
          <FilterMultiSelect
            label="Actor"
            options={actorOptions}
            selected={actors}
            onChange={setActors}
          />
          <FilterMultiSelect
            label="Result"
            options={[
              { value: "success", label: "Success" },
              { value: "failure", label: "Failure" },
              { value: "prepared", label: "Prepared" },
            ]}
            selected={results}
            onChange={setResults}
          />
          <button
            type="button"
            onClick={() => toast.info("Export prepared (session-only). No file was generated.")}
            className="inline-flex h-8 items-center gap-1 rounded-md border border-border bg-background px-2 text-xs font-medium text-foreground hover:bg-accent"
          >
            Prepare export
          </button>
        </FilterBar>
      </div>
      <p className="rounded border border-border bg-muted/40 px-2 py-1 text-[11px] text-muted-foreground">
        <Shield aria-hidden className="mr-1 inline size-3" /> Audit records are immutable in this
        UI. Records cannot be edited or deleted.
      </p>

      {rows.length === 0 ? (
        <EmptyState title="No audit events match your filters." />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table
            className="w-full min-w-[1100px] border-separate border-spacing-0 text-left text-sm"
            aria-label="Audit log"
          >
            <thead>
              <tr className="bg-muted/60 text-xs uppercase tracking-wide text-muted-foreground">
                <Th>Timestamp</Th>
                <Th>Actor</Th>
                <Th>Role</Th>
                <Th>Action</Th>
                <Th>Resource</Th>
                <Th>Result</Th>
                <Th>Source</Th>
                <Th>IP</Th>
                <Th>Reason</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id} className="hover:bg-accent/40">
                  <Td className="text-xs text-muted-foreground">{formatRelativeTime(e.at)}</Td>
                  <Td className="text-xs font-medium text-foreground">{e.actor}</Td>
                  <Td className="text-xs text-muted-foreground">{e.actorRole}</Td>
                  <Td className="text-xs">{e.action}</Td>
                  <Td className="text-xs text-muted-foreground">
                    {AUDIT_RESOURCE_LABEL[e.resourceKind]} · <code>{e.resourceLabel}</code>
                  </Td>
                  <Td>
                    <ResultBadge result={e.result} />
                  </Td>
                  <Td className="text-xs text-muted-foreground">{e.source}</Td>
                  <Td className="text-xs text-muted-foreground">{e.ipSummary}</Td>
                  <Td className="text-xs text-muted-foreground">{e.reason ?? "—"}</Td>
                  <Td>
                    {e.linkTo ? (
                      <button
                        onClick={() => tryNavigate(e.linkTo!)}
                        className="text-xs font-medium text-foreground underline-offset-2 hover:underline"
                      >
                        Open
                      </button>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------
// Alerts & incidents tab
// ---------------------------------------------------------------------
function AlertsTab({ session, permissions }: { session: SystemSession; permissions: string[] }) {
  const canManage = hasPermission(permissions as never, "system.alerts.manage");
  const alerts = session.alertsWithOverlay;
  const [open, setOpen] = useState<string | null>(null);
  const [manualOpen, setManualOpen] = useState(false);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          {alerts.filter((a) => a.status !== "resolved").length} open · {alerts.length} total
        </p>
        {canManage ? (
          <button
            type="button"
            onClick={() => setManualOpen(true)}
            className="inline-flex h-8 items-center gap-1 rounded-md border border-border bg-background px-2 text-xs font-medium text-foreground hover:bg-accent"
          >
            Prepare manual incident
          </button>
        ) : null}
      </div>

      <ul className="grid grid-cols-1 gap-2">
        {alerts.map((a) => (
          <li key={a.id} className="rounded-lg border border-border bg-card p-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <SeverityBadge severity={a.severity} />
                  <AlertStatusBadge status={a.status} />
                  <span className="text-[11px] text-muted-foreground">
                    {ALERT_KIND_LABEL[a.kind]}
                  </span>
                </div>
                <p className="mt-1 text-sm font-medium text-foreground">{a.title}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {a.impact} · Service: {a.affectedService.replace(/_/g, " ")} · Opened{" "}
                  {formatRelativeTime(a.createdAt)} · Last update {formatRelativeTime(a.lastUpdate)}
                  {a.owner ? ` · Owner ${a.owner}` : ""}
                </p>
                {a.relatedJobIds && a.relatedJobIds.length > 0 ? (
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    Related jobs: {a.relatedJobIds.join(", ")}
                  </p>
                ) : null}
              </div>
              <button
                onClick={() => setOpen(a.id)}
                className="rounded border border-border px-2 py-1 text-xs font-medium hover:bg-accent"
              >
                Open
              </button>
            </div>
          </li>
        ))}
        {session.state.manualIncidents.map((inc) => (
          <li
            key={inc.id}
            className="rounded-lg border border-sky-200 bg-sky-50/60 p-3 dark:border-sky-900/60 dark:bg-sky-950/40"
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <SeverityBadge severity={inc.severity} />
                  <span className="rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-medium text-sky-900 dark:bg-sky-900/60 dark:text-sky-100">
                    Session-only
                  </span>
                </div>
                <p className="mt-1 text-sm font-medium text-foreground">{inc.title}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {inc.impact} · Prepared by {inc.actor} · {formatRelativeTime(inc.createdAt)}
                </p>
              </div>
            </div>
          </li>
        ))}
      </ul>

      {open ? (
        <AlertActionDialog
          alert={alerts.find((x) => x.id === open)!}
          session={session}
          canManage={canManage}
          onClose={() => setOpen(null)}
        />
      ) : null}

      {manualOpen ? (
        <ManualIncidentDialog
          onClose={() => setManualOpen(false)}
          onConfirm={(title, impact, severity) => {
            session.addManualIncident(title, impact, severity);
            toast.success("Manual incident prepared (session-only)");
            setManualOpen(false);
          }}
        />
      ) : null}
    </div>
  );
}

function AlertActionDialog({
  alert,
  session,
  canManage,
  onClose,
}: {
  alert: AlertRecord;
  session: SystemSession;
  canManage: boolean;
  onClose: () => void;
}) {
  const [note, setNote] = useState("");
  const [owner, setOwner] = useState(alert.owner ?? "");
  const updates = session.alertUpdatesFor(alert.id);

  function act(
    kind: Parameters<typeof session.updateAlert>[1],
    detail: string,
    opts?: { nextStatus?: AlertStatus; nextOwner?: string },
  ) {
    session.updateAlert(alert, kind, detail, opts);
    toast.success(`${session.labels.ALERT_ACTION_LABEL[kind]} (session-only)`);
  }

  return (
    <SlideOver onClose={onClose} title={alert.title}>
      <div className="flex flex-col gap-4 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={alert.severity} />
          <AlertStatusBadge status={alert.status} />
          <span className="text-xs text-muted-foreground">{ALERT_KIND_LABEL[alert.kind]}</span>
        </div>
        <p className="text-xs text-muted-foreground">{alert.impact}</p>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <DT>Service</DT>
          <DD className="capitalize">{alert.affectedService.replace(/_/g, " ")}</DD>
          <DT>Opened</DT>
          <DD>{formatRelativeTime(alert.createdAt)}</DD>
          <DT>Last update</DT>
          <DD>{formatRelativeTime(alert.lastUpdate)}</DD>
          <DT>Owner</DT>
          <DD>{alert.owner ?? "—"}</DD>
        </dl>

        <Section title="Session updates">
          {updates.length === 0 ? (
            <p className="text-xs text-muted-foreground">No session updates.</p>
          ) : (
            <ul className="flex flex-col gap-1 text-xs">
              {updates.map((u) => (
                <li
                  key={u.id}
                  className="rounded border border-sky-200 bg-sky-50/60 px-2 py-1 text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/40 dark:text-sky-200"
                >
                  {session.labels.ALERT_ACTION_LABEL[u.kind]} — {u.actor} ·{" "}
                  {formatRelativeTime(u.at)}
                  {u.detail ? <div className="text-[11px] opacity-90">{u.detail}</div> : null}
                </li>
              ))}
            </ul>
          )}
        </Section>

        {canManage ? (
          <Section title="Prepare action">
            <div className="flex flex-col gap-2">
              <label className="flex flex-col gap-1 text-xs">
                <span className="font-medium">Owner (optional)</span>
                <input
                  value={owner}
                  onChange={(e) => setOwner(e.target.value)}
                  className="h-8 rounded border border-border bg-background px-2"
                  placeholder="Assign to…"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs">
                <span className="font-medium">Note</span>
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  rows={2}
                  className="rounded border border-border bg-background p-2"
                />
              </label>
              <div className="flex flex-wrap gap-1.5">
                <ActionBtn
                  onClick={() =>
                    act("acknowledged", note || "Acknowledged", { nextStatus: "acknowledged" })
                  }
                  disabled={alert.status !== "open"}
                >
                  Acknowledge
                </ActionBtn>
                <ActionBtn
                  onClick={() =>
                    act(
                      "assigned",
                      owner ? `Assigned to ${owner}` : "Owner assigned",
                      owner ? { nextOwner: owner } : undefined,
                    )
                  }
                  disabled={!owner.trim()}
                >
                  Assign owner
                </ActionBtn>
                <ActionBtn
                  onClick={() => act("note_added", note || "(no detail)")}
                  disabled={!note.trim()}
                >
                  Add note
                </ActionBtn>
                <ActionBtn onClick={() => act("prepared_incident", note || "Incident prepared")}>
                  Prepare incident
                </ActionBtn>
                <ActionBtn
                  onClick={() =>
                    act("escalated", note || "Escalated", { nextStatus: "investigating" })
                  }
                  tone="danger"
                >
                  Escalate
                </ActionBtn>
                <ActionBtn
                  onClick={() =>
                    act("resolved_simulation", note || "Resolved (simulation)", {
                      nextStatus: "resolved",
                    })
                  }
                >
                  Resolve (simulation)
                </ActionBtn>
              </div>
              <p className="text-[11px] text-muted-foreground">
                No real incident-response action occurs. All updates are session-only.
              </p>
            </div>
          </Section>
        ) : (
          <p className="text-[11px] text-muted-foreground">
            Your role does not include system.alerts.manage.
          </p>
        )}
      </div>
    </SlideOver>
  );
}

function ManualIncidentDialog({
  onClose,
  onConfirm,
}: {
  onClose: () => void;
  onConfirm: (title: string, impact: string, severity: "info" | "warning" | "critical") => void;
}) {
  const [title, setTitle] = useState("");
  const [impact, setImpact] = useState("");
  const [severity, setSeverity] = useState<"info" | "warning" | "critical">("warning");

  return (
    <AlertDialog
      open
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Prepare a manual incident</AlertDialogTitle>
          <AlertDialogDescription>
            Records a session-only incident. It is not published to any real incident-management
            system.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="flex flex-col gap-2 text-sm">
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium">Title</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="h-8 rounded border border-border bg-background px-2"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium">Impact</span>
            <textarea
              value={impact}
              onChange={(e) => setImpact(e.target.value)}
              rows={2}
              className="rounded border border-border bg-background p-2"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium">Severity</span>
            <select
              value={severity}
              onChange={(e) => setSeverity(e.target.value as typeof severity)}
              className="h-8 rounded border border-border bg-background px-2"
            >
              <option value="info">Info</option>
              <option value="warning">Warning</option>
              <option value="critical">Critical</option>
            </select>
          </label>
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={!title.trim() || !impact.trim()}
            onClick={() => onConfirm(title.trim(), impact.trim(), severity)}
          >
            Prepare incident
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

// ---------------------------------------------------------------------
// Configuration tab
// ---------------------------------------------------------------------
function ConfigurationTab() {
  const groups: Record<string, typeof mockConfigReference> = {
    environment: [],
    region: [],
    providers: [],
    release: [],
  };
  mockConfigReference.forEach((e) => groups[e.group].push(e));

  const groupTitles: Record<string, string> = {
    environment: "Environment",
    region: "Region",
    providers: "Providers",
    release: "Release",
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3 text-xs text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200">
        <p className="flex items-center gap-1.5 font-medium">
          <Info aria-hidden className="size-3.5" /> Secrets are intentionally hidden.
        </p>
        <p className="mt-0.5">
          Passwords, API keys, JWT secrets, database and Redis credentials, private bucket URLs and
          authentication tokens are never displayed here. Use the Secret Manager for those.
        </p>
      </div>

      {Object.entries(groups).map(([key, entries]) => (
        <section key={key} className="rounded-lg border border-border bg-card">
          <h3 className="border-b border-border px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {groupTitles[key]}
          </h3>
          <dl className="grid grid-cols-1 gap-x-6 gap-y-2 p-3 sm:grid-cols-2">
            {entries.map((e) => (
              <div
                key={e.key}
                className="flex items-start justify-between gap-2 border-b border-dashed border-border pb-1.5 last:border-b-0 last:pb-0"
              >
                <div>
                  <dt className="text-xs font-medium text-foreground">{e.label}</dt>
                  {e.hint ? <p className="text-[11px] text-muted-foreground">{e.hint}</p> : null}
                </div>
                <dd className="text-xs text-muted-foreground">
                  <code>{e.value}</code>
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ))}

      <section className="rounded-lg border border-border bg-card">
        <h3 className="border-b border-border px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Recent deployments
        </h3>
        <ul className="divide-y divide-border">
          {mockDeployments.map((d) => (
            <li
              key={d.id}
              className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs"
            >
              <div>
                <p className="font-medium text-foreground">{d.version}</p>
                <p className="text-muted-foreground">{d.summary}</p>
              </div>
              <p className="text-muted-foreground capitalize">
                {d.environment} · {formatRelativeTime(d.deployedAt)} · {d.deployedBy}
              </p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------
// Shared primitives
// ---------------------------------------------------------------------

function Th({ children }: { children?: ReactNode }) {
  return <th className="border-b border-border px-3 py-2 font-medium">{children}</th>;
}
function Td({ children, className }: { children?: ReactNode; className?: string }) {
  return (
    <td className={cn("border-b border-border px-3 py-2 align-top", className)}>{children}</td>
  );
}
function DT({ children }: { children?: ReactNode }) {
  return <dt className="text-muted-foreground">{children}</dt>;
}
function DD({ children, className }: { children?: ReactNode; className?: string }) {
  return <dd className={cn("text-foreground", className)}>{children}</dd>;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      {children}
    </section>
  );
}

function SlideOver({
  children,
  onClose,
  title,
}: {
  children: ReactNode;
  onClose: () => void;
  title: string;
}) {
  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label={title}>
      <button className="absolute inset-0 bg-foreground/40" aria-label="Close" onClick={onClose} />
      <aside className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col border-l border-border bg-background shadow-xl">
        <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          <h2 className="truncate text-sm font-semibold text-foreground">{title}</h2>
          <button
            onClick={onClose}
            aria-label="Close panel"
            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <X aria-hidden className="size-4" />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
      </aside>
    </div>
  );
}

function ActionBtn({
  children,
  onClick,
  disabled,
  disabledReason,
  tone,
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  disabledReason?: string;
  tone?: "danger";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={disabled ? disabledReason : undefined}
      className={cn(
        "inline-flex h-8 items-center gap-1 rounded-md border px-2.5 text-xs font-medium transition-colors",
        disabled
          ? "cursor-not-allowed border-border text-muted-foreground opacity-60"
          : tone === "danger"
            ? "border-rose-300 bg-rose-50 text-rose-900 hover:bg-rose-100 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-200"
            : "border-border bg-background text-foreground hover:bg-accent",
      )}
    >
      {children}
    </button>
  );
}

// ---------------------- Filter pill helpers ----------------------
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
        className="bg-transparent text-xs outline-none"
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
        "inline-flex h-8 items-center gap-1 rounded-md border px-2 text-xs font-medium",
        active
          ? "border-foreground/40 bg-foreground text-background"
          : "border-border bg-background text-foreground hover:bg-accent",
      )}
    >
      {label}
    </button>
  );
}

// ---------------------- Badges ----------------------
function HealthBadge({ state }: { state: ServiceHealthState }) {
  const map: Record<ServiceHealthState, string> = {
    operational:
      "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-900/60",
    degraded:
      "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60",
    delayed:
      "bg-orange-50 text-orange-900 ring-orange-200 dark:bg-orange-950/40 dark:text-orange-200 dark:ring-orange-900/60",
    incident:
      "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60",
    unknown:
      "bg-zinc-100 text-zinc-800 ring-zinc-200 dark:bg-zinc-800/60 dark:text-zinc-200 dark:ring-zinc-700",
  };
  const icon =
    state === "operational" ? (
      <CheckCircle2 aria-hidden className="size-3" />
    ) : state === "incident" ? (
      <ShieldAlert aria-hidden className="size-3" />
    ) : state === "degraded" || state === "delayed" ? (
      <AlertTriangle aria-hidden className="size-3" />
    ) : (
      <Info aria-hidden className="size-3" />
    );
  return (
    <span
      className={cn(
        "inline-flex w-fit items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        map[state],
      )}
    >
      {icon}
      {SERVICE_HEALTH_LABEL[state]}
    </span>
  );
}
function JobStatusBadge({ status }: { status: JobStatus }) {
  const map: Record<JobStatus, string> = {
    queued:
      "bg-zinc-100 text-zinc-800 ring-zinc-200 dark:bg-zinc-800/60 dark:text-zinc-200 dark:ring-zinc-700",
    running:
      "bg-sky-50 text-sky-900 ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:ring-sky-900/60",
    succeeded:
      "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-900/60",
    failed:
      "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60",
    retrying:
      "bg-orange-50 text-orange-900 ring-orange-200 dark:bg-orange-950/40 dark:text-orange-200 dark:ring-orange-900/60",
    cancelled:
      "bg-zinc-100 text-zinc-800 ring-zinc-200 dark:bg-zinc-800/60 dark:text-zinc-200 dark:ring-zinc-700",
  };
  return (
    <span
      className={cn(
        "inline-flex rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        map[status],
      )}
    >
      {JOB_STATUS_LABEL[status]}
    </span>
  );
}
function FlagStateBadge({ state }: { state: FlagState }) {
  const map: Record<FlagState, string> = {
    off: "bg-zinc-100 text-zinc-800 ring-zinc-200 dark:bg-zinc-800/60 dark:text-zinc-200 dark:ring-zinc-700",
    on: "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-900/60",
    rollout:
      "bg-sky-50 text-sky-900 ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:ring-sky-900/60",
  };
  return (
    <span
      className={cn(
        "inline-flex rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        map[state],
      )}
    >
      {FLAG_STATE_LABEL[state]}
    </span>
  );
}
function RiskChip({ level }: { level: "low" | "medium" | "high" | "critical" }) {
  const cls =
    level === "critical"
      ? "text-rose-700 dark:text-rose-300"
      : level === "high"
        ? "text-orange-700 dark:text-orange-300"
        : level === "medium"
          ? "text-amber-700 dark:text-amber-300"
          : "text-muted-foreground";
  return <span className={cn("capitalize", cls)}>{level}</span>;
}
function MessageStatusBadge({ status }: { status: MessageStatus }) {
  const map: Record<MessageStatus, string> = {
    queued:
      "bg-zinc-100 text-zinc-800 ring-zinc-200 dark:bg-zinc-800/60 dark:text-zinc-200 dark:ring-zinc-700",
    sent: "bg-sky-50 text-sky-900 ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:ring-sky-900/60",
    delivered:
      "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-900/60",
    opened:
      "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-900/60",
    bounced:
      "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60",
    failed:
      "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60",
    rejected:
      "bg-orange-50 text-orange-900 ring-orange-200 dark:bg-orange-950/40 dark:text-orange-200 dark:ring-orange-900/60",
    spam_complaint:
      "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60",
  };
  return (
    <span
      className={cn(
        "inline-flex rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        map[status],
      )}
    >
      {MESSAGE_STATUS_LABEL[status]}
    </span>
  );
}
function SeverityBadge({ severity }: { severity: "info" | "warning" | "critical" }) {
  const map = {
    info: "bg-sky-50 text-sky-900 ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:ring-sky-900/60",
    warning:
      "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60",
    critical:
      "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60",
  } as const;
  return (
    <span
      className={cn(
        "inline-flex rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        map[severity],
      )}
    >
      {ALERT_SEVERITY_LABEL[severity]}
    </span>
  );
}
function AlertStatusBadge({ status }: { status: AlertStatus }) {
  const map: Record<AlertStatus, string> = {
    open: "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60",
    acknowledged:
      "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60",
    investigating:
      "bg-sky-50 text-sky-900 ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:ring-sky-900/60",
    resolved:
      "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-900/60",
  };
  return (
    <span
      className={cn(
        "inline-flex rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        map[status],
      )}
    >
      {ALERT_STATUS_LABEL[status]}
    </span>
  );
}
function ResultBadge({ result }: { result: "success" | "failure" | "prepared" }) {
  const map = {
    success:
      "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-900/60",
    failure:
      "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60",
    prepared:
      "bg-sky-50 text-sky-900 ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:ring-sky-900/60",
  } as const;
  return (
    <span
      className={cn(
        "inline-flex rounded-md px-2 py-0.5 text-xs font-medium capitalize ring-1 ring-inset",
        map[result],
      )}
    >
      {result}
    </span>
  );
}

// ---------------------- Filter option constants ----------------------
const JOB_STATUS_OPTIONS: { value: JobStatus; label: string }[] = (
  ["queued", "running", "succeeded", "failed", "retrying", "cancelled"] as JobStatus[]
).map((v) => ({ value: v, label: JOB_STATUS_LABEL[v] }));
const JOB_TYPE_OPTIONS: { value: JobType; label: string }[] = (
  Object.keys(JOB_TYPE_LABEL) as JobType[]
).map((v) => ({ value: v, label: JOB_TYPE_LABEL[v] }));
const CHANNEL_OPTIONS: { value: MessageChannel; label: string }[] = [
  { value: "email", label: "Email" },
  { value: "sms", label: "SMS" },
];
const MESSAGE_STATUS_OPTIONS: { value: MessageStatus; label: string }[] = (
  Object.keys(MESSAGE_STATUS_LABEL) as MessageStatus[]
).map((v) => ({ value: v, label: MESSAGE_STATUS_LABEL[v] }));
const MESSAGE_KIND_OPTIONS: { value: MessageKind; label: string }[] = (
  Object.keys(MESSAGE_KIND_LABEL) as MessageKind[]
).map((v) => ({ value: v, label: MESSAGE_KIND_LABEL[v] }));
const AUDIT_RESOURCE_OPTIONS: { value: string; label: string }[] = (
  Object.keys(AUDIT_RESOURCE_LABEL) as (keyof typeof AUDIT_RESOURCE_LABEL)[]
).map((v) => ({ value: v, label: AUDIT_RESOURCE_LABEL[v] }));

// Suppress unused-import warning for icons kept for future callers.
const _keepIcons = { MessageSquare, Search, ShieldCheck, KeySquare };
void _keepIcons;
