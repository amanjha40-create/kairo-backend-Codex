import { Link, createFileRoute } from "@tanstack/react-router";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Bell,
  MailWarning,
  Rocket,
  Send,
  Zap,
} from "lucide-react";
import { SectionHeader } from "@/features/admin/components/section-header";
import { MetricCard } from "@/features/admin/components/metric-card";
import { AttentionCard } from "@/features/admin/components/attention-card";
import { Funnel } from "@/features/admin/components/funnel";
import { VerificationStatusGrid } from "@/features/admin/components/verification-status-grid";
import { ActivityItem } from "@/features/admin/components/activity-item";
import { PlatformSummary } from "@/features/admin/components/platform-summary";
import { DateRangeSelector } from "@/features/admin/components/date-range-selector";
import {
  getActivity,
  getAttention,
  getFunnel,
  getMetrics,
  getServices,
  getStatuses,
} from "@/features/admin/data/overview";
import { getCommunicationMetrics } from "@/features/admin/data/communications";
import {
  SERVICE_HEALTH_LABEL,
  getSystemOverviewMetrics,
  mockDeployments,
  type ServiceHealthState,
} from "@/features/admin/data/system";
import { formatRelativeTime } from "@/features/admin/lib/format";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/admin/")({
  head: () => ({
    meta: [
      { title: "Overview — Kairo Admin" },
      {
        name: "description",
        content: "Kairo growth, verification operations and urgent activity.",
      },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  component: OverviewPage,
});

function OverviewPage() {
  const metrics = getMetrics();
  const attention = getAttention();
  const funnel = getFunnel();
  const statuses = getStatuses();
  const activity = getActivity();
  const services = getServices();
  const comms = getCommunicationMetrics();
  const sys = getSystemOverviewMetrics();
  const recentDeployment = mockDeployments[0];

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-8">
      {/* Page header */}
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-foreground">Overview</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Monitor Kairo's growth, verification operations and urgent platform activity.
          </p>
        </div>
        <DateRangeSelector />
      </header>

      {/* Primary metrics */}
      <section aria-labelledby="metrics-heading">
        <SectionHeader
          title="Business metrics"
          description="How Kairo is growing and converting."
        />
        <h2 id="metrics-heading" className="sr-only">
          Primary metrics
        </h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          {metrics.map((m) => (
            <MetricCard key={m.id} metric={m} />
          ))}
        </div>
      </section>

      {/* Urgent attention */}
      <section aria-labelledby="attention-heading">
        <SectionHeader
          title="Urgent attention"
          description="Operational work that needs an admin decision now."
        />
        <h2 id="attention-heading" className="sr-only">
          Urgent attention
        </h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {attention.map((a) => (
            <AttentionCard key={a.id} item={a} />
          ))}
        </div>
      </section>

      {/* Funnel + Verification operations */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        <section aria-labelledby="funnel-heading" className="lg:col-span-2">
          <SectionHeader
            title="Onboarding & verification funnel"
            description="Where users progress and where they drop off."
          />
          <h2 id="funnel-heading" className="sr-only">
            Funnel
          </h2>
          <div className="rounded-lg border border-border bg-card p-4">
            <Funnel stages={funnel} />
          </div>
        </section>

        <section aria-labelledby="ops-heading" className="lg:col-span-3">
          <SectionHeader
            title="Verification operations"
            description="Live status across the verification pipeline. Select a status to open its queue."
          />
          <h2 id="ops-heading" className="sr-only">
            Verification operations
          </h2>
          <VerificationStatusGrid items={statuses} />
        </section>
      </div>

      {/* Activity + Platform */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        <section aria-labelledby="activity-heading" className="lg:col-span-3">
          <SectionHeader
            title="Recent activity"
            description="Latest admin, candidate, employer and system events."
          />
          <h2 id="activity-heading" className="sr-only">
            Recent activity
          </h2>
          <div className="rounded-lg border border-border bg-card px-3">
            <ul className="divide-y divide-border">
              {activity.map((a) => (
                <ActivityItem key={a.id} item={a} />
              ))}
            </ul>
          </div>
        </section>

        <section aria-labelledby="platform-heading" className="lg:col-span-2">
          <SectionHeader
            title="Platform summary"
            description="Application-level status. Mock operational data until service telemetry is wired in."
          />
          <h2 id="platform-heading" className="sr-only">
            Platform
          </h2>
          <PlatformSummary services={services} />
        </section>
      </div>

      {/* Communications */}
      <section aria-labelledby="comms-heading">
        <SectionHeader
          title="Communications"
          description="Delivery health across every outbound verification message."
          actions={
            <Link
              to="/admin/communications"
              className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
            >
              Open center <ArrowRight aria-hidden className="size-3" />
            </Link>
          }
        />
        <h2 id="comms-heading" className="sr-only">
          Communications
        </h2>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
          <CommTile
            label="Sent (total)"
            value={comms.total}
            tone="neutral"
            icon={<Send aria-hidden className="size-3.5" />}
          />
          <CommTile label="Pending" value={comms.pending} tone="neutral" />
          <CommTile label="Delivered" value={comms.delivered} tone="good" />
          <CommTile label="Awaiting response" value={comms.awaitingResponse} tone="warn" />
          <CommTile
            label="Failed / bounced"
            value={comms.failedTotal}
            tone="bad"
            icon={<MailWarning aria-hidden className="size-3.5" />}
          />
          <CommTile label="Follow-ups due today" value={comms.followUpsDueToday} tone="warn" />
        </div>
      </section>

      {/* System operations */}
      <section aria-labelledby="sys-heading">
        <SectionHeader
          title="System operations"
          description="Platform health, background activity and open incidents. Mock operational data."
          actions={
            <Link
              to="/admin/system"
              className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
            >
              Open system <ArrowRight aria-hidden className="size-3" />
            </Link>
          }
        />
        <h2 id="sys-heading" className="sr-only">
          System operations
        </h2>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          <SysTile label="Platform status" href="/admin/system">
            <PlatformSummaryChip
              states={[
                sys.api,
                sys.database,
                sys.emailDelivery,
                sys.smsDelivery,
                sys.backgroundJobs,
                sys.documentStorage,
              ]}
            />
          </SysTile>
          <SysTile
            label="Failed jobs"
            href="/admin/system"
            icon={<Zap aria-hidden className="size-3.5" />}
          >
            <p
              className={cn(
                "text-xl font-semibold tabular-nums",
                sys.failedJobs > 0 ? "text-rose-700 dark:text-rose-300" : "text-foreground",
              )}
            >
              {sys.failedJobs}
            </p>
          </SysTile>
          <SysTile
            label="Open incidents"
            href="/admin/system"
            icon={<Bell aria-hidden className="size-3.5" />}
          >
            <p
              className={cn(
                "text-xl font-semibold tabular-nums",
                sys.openAlerts > 0 ? "text-rose-700 dark:text-rose-300" : "text-foreground",
              )}
            >
              {sys.openAlerts}
            </p>
          </SysTile>
          <SysTile
            label="Delivery failures"
            href="/admin/system"
            icon={<AlertTriangle aria-hidden className="size-3.5" />}
          >
            <p
              className={cn(
                "text-xl font-semibold tabular-nums",
                comms.failedTotal > 0 ? "text-amber-700 dark:text-amber-300" : "text-foreground",
              )}
            >
              {comms.failedTotal}
            </p>
          </SysTile>
          <SysTile
            label="Recent deployment"
            href="/admin/system"
            icon={<Rocket aria-hidden className="size-3.5" />}
          >
            <p className="text-xs font-medium text-foreground">{recentDeployment.version}</p>
            <p className="text-[11px] text-muted-foreground">
              {formatRelativeTime(recentDeployment.deployedAt)}
            </p>
          </SysTile>
        </div>
      </section>
    </div>
  );
}

function SysTile({
  label,
  href,
  icon,
  children,
}: {
  label: string;
  href: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Link
      to={href}
      className="block rounded-lg border border-border bg-card p-3 hover:bg-accent/40"
    >
      <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {icon}
        {label}
      </p>
      <div className="mt-1">{children}</div>
    </Link>
  );
}

function PlatformSummaryChip({ states }: { states: ServiceHealthState[] }) {
  const worst: ServiceHealthState = states.includes("incident")
    ? "incident"
    : states.includes("degraded")
      ? "degraded"
      : states.includes("delayed")
        ? "delayed"
        : states.includes("unknown")
          ? "unknown"
          : "operational";
  const cls =
    worst === "operational"
      ? "text-emerald-700 dark:text-emerald-300"
      : worst === "incident"
        ? "text-rose-700 dark:text-rose-300"
        : worst === "unknown"
          ? "text-muted-foreground"
          : "text-amber-700 dark:text-amber-300";
  return (
    <p className={cn("inline-flex items-center gap-1 text-sm font-semibold", cls)}>
      <Activity aria-hidden className="size-3.5" /> {SERVICE_HEALTH_LABEL[worst]}
    </p>
  );
}

function CommTile({
  label,
  value,
  tone,
  icon,
}: {
  label: string;
  value: number;
  tone: "neutral" | "good" | "warn" | "bad";
  icon?: React.ReactNode;
}) {
  const toneCls =
    tone === "good"
      ? "text-emerald-700 dark:text-emerald-300"
      : tone === "warn"
        ? "text-amber-700 dark:text-amber-300"
        : tone === "bad"
          ? "text-rose-700 dark:text-rose-300"
          : "text-foreground";
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {icon}
        {label}
      </p>
      <p className={`mt-1 text-xl font-semibold tabular-nums ${toneCls}`}>{value}</p>
    </div>
  );
}
