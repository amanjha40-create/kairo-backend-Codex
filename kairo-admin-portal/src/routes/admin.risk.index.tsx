import { useMemo, useState } from "react";
import { Link, createFileRoute } from "@tanstack/react-router";
import {
  AlertTriangle,
  Copy,
  FileWarning,
  Flame,
  ShieldAlert,
  ShieldCheck,
  UserRoundSearch,
  Users,
} from "lucide-react";
import { AdminSearchField } from "@/features/admin/components/search-field";
import { FilterBar, FilterMultiSelect } from "@/features/admin/components/filter-bar";
import { EmptyState } from "@/features/admin/components/states";
import { useAdminAccess } from "@/features/admin/auth/admin-access";
import { hasPermission } from "@/features/admin/workflow/permissions";
import { formatRelativeTime } from "@/features/admin/lib/format";
import {
  ALL_INVESTIGATORS,
  getRiskMetrics,
  INVESTIGATION_STATUS_LABEL,
  mockInvestigations,
  RESOLVED_STATUSES,
  RISK_CATEGORY_LABEL,
  RISK_LEVEL_LABEL,
  type Investigation,
  type InvestigationStatus,
  type RiskCategory,
  type RiskLevel,
  type SubjectKind,
  SUBJECT_KIND_LABEL,
} from "@/features/admin/data/risk";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/admin/risk/")({
  head: () => ({
    meta: [
      { title: "Trust & Safety — Kairo Admin" },
      {
        name: "description",
        content:
          "Investigate risk signals, duplicate identities and document anomalies across the Kairo platform.",
      },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  component: RiskCenterPage,
});

function RiskCenterPage() {
  const { admin } = useAdminAccess();
  const permissions = admin?.permissions ?? [];
  const canView = hasPermission(permissions, "risk.view");

  const [query, setQuery] = useState("");
  const [riskLevel, setRiskLevel] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<Set<string>>(new Set());
  const [category, setCategory] = useState<Set<string>>(new Set());
  const [subjectKind, setSubjectKind] = useState<Set<string>>(new Set());
  const [country, setCountry] = useState<Set<string>>(new Set());
  const [verification, setVerification] = useState<Set<string>>(new Set());
  const [investigator, setInvestigator] = useState<Set<string>>(new Set());
  const [dateWindow, setDateWindow] = useState<"any" | "24h" | "7d" | "30d">("any");
  const [openOnly, setOpenOnly] = useState(true);
  const [escalatedOnly, setEscalatedOnly] = useState(false);

  const metrics = useMemo(() => getRiskMetrics(), []);
  const countryOptions = useMemo(
    () => uniqueSorted(mockInvestigations.map((i) => i.country).filter((c): c is string => !!c)),
    [],
  );
  const verificationOptions = useMemo(
    () =>
      uniqueSorted(
        mockInvestigations.map((i) => i.verificationType).filter((v): v is string => !!v),
      ),
    [],
  );

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
    return mockInvestigations.filter((inv) => {
      if (q) {
        const haystack = [
          inv.id,
          inv.reference,
          inv.reason,
          inv.summary,
          inv.subject.displayName,
          inv.subject.reference,
          inv.subject.id,
          ...inv.relatedUserIds,
          ...inv.relatedCaseIds,
          ...inv.relatedOrganizationIds,
          ...inv.documentAnomalies.map((d) => d.documentLabel),
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      if (riskLevel.size && !riskLevel.has(inv.riskLevel)) return false;
      if (status.size && !status.has(inv.status)) return false;
      if (category.size && !category.has(inv.category)) return false;
      if (subjectKind.size && !subjectKind.has(inv.subject.kind)) return false;
      if (country.size && (!inv.country || !country.has(inv.country))) return false;
      if (verification.size && (!inv.verificationType || !verification.has(inv.verificationType)))
        return false;
      if (investigator.size && !investigator.has(inv.owner)) return false;
      if (openOnly && RESOLVED_STATUSES.includes(inv.status)) return false;
      if (escalatedOnly && !inv.escalated) return false;
      if (dateWindow !== "any" && now - new Date(inv.createdAt).getTime() > window) return false;
      return true;
    });
  }, [
    query,
    riskLevel,
    status,
    category,
    subjectKind,
    country,
    verification,
    investigator,
    dateWindow,
    openOnly,
    escalatedOnly,
  ]);

  const activeCount =
    [riskLevel, status, category, subjectKind, country, verification, investigator].reduce(
      (n, s) => n + s.size,
      0,
    ) +
    (dateWindow !== "any" ? 1 : 0) +
    (openOnly ? 0 : 1) +
    (escalatedOnly ? 1 : 0);

  if (!canView) {
    return (
      <div className="mx-auto max-w-3xl">
        <EmptyState
          title="No access"
          description="Your role does not include the risk.view permission."
        />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-foreground">
            Trust &amp; Safety
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Investigate risk signals, duplicate identities, document anomalies and suspicious
            activity. Investigations are prepared here, not auto-actioned.
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-border bg-muted/40 px-2 py-1 text-[11px] text-muted-foreground">
          <ShieldAlert aria-hidden className="size-3.5" /> Session-only — no accounts are restricted
          from this surface.
        </span>
      </header>

      {/* Metrics */}
      <section aria-labelledby="risk-metrics">
        <h2 id="risk-metrics" className="sr-only">
          Risk overview
        </h2>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
          <MetricTile icon={ShieldAlert} label="Open investigations" value={metrics.open} />
          <MetricTile
            icon={Flame}
            label="High-risk users"
            value={metrics.highRiskUsers}
            tone="bad"
          />
          <MetricTile
            icon={Copy}
            label="Duplicate candidates"
            value={metrics.duplicateCandidates}
          />
          <MetricTile
            icon={FileWarning}
            label="Document anomalies"
            value={metrics.documentAnomalies}
          />
          <MetricTile
            icon={UserRoundSearch}
            label="Suspicious logins"
            value={metrics.suspiciousLogins}
          />
          <MetricTile
            icon={AlertTriangle}
            label="Pending T&S review"
            value={metrics.pendingTsReview}
          />
          <MetricTile
            icon={ShieldCheck}
            label="Resolved (7d)"
            value={metrics.recentlyResolved}
            tone="good"
          />
          <MetricTile icon={Users} label="Escalated" value={metrics.escalated} tone="bad" />
        </div>
      </section>

      {/* Search + filters */}
      <div className="flex flex-col gap-2">
        <AdminSearchField
          value={query}
          onChange={setQuery}
          placeholder="Search user, candidate, passport ID, case, org, document, investigation ID…"
          ariaLabel="Search investigations"
          className="max-w-xl"
        />
        <FilterBar
          activeCount={activeCount}
          onClear={() => {
            setRiskLevel(new Set());
            setStatus(new Set());
            setCategory(new Set());
            setSubjectKind(new Set());
            setCountry(new Set());
            setVerification(new Set());
            setInvestigator(new Set());
            setDateWindow("any");
            setOpenOnly(true);
            setEscalatedOnly(false);
          }}
        >
          <FilterMultiSelect
            label="Risk level"
            options={RISK_LEVEL_OPTIONS}
            selected={riskLevel}
            onChange={setRiskLevel}
          />
          <FilterMultiSelect
            label="Status"
            options={STATUS_OPTIONS}
            selected={status}
            onChange={setStatus}
          />
          <FilterMultiSelect
            label="Category"
            options={CATEGORY_OPTIONS}
            selected={category}
            onChange={setCategory}
          />
          <FilterMultiSelect
            label="Subject"
            options={SUBJECT_OPTIONS}
            selected={subjectKind}
            onChange={setSubjectKind}
          />
          <FilterMultiSelect
            label="Country"
            options={countryOptions.map((c) => ({ value: c, label: c }))}
            selected={country}
            onChange={setCountry}
          />
          <FilterMultiSelect
            label="Verification"
            options={verificationOptions.map((v) => ({ value: v, label: v }))}
            selected={verification}
            onChange={setVerification}
          />
          <FilterMultiSelect
            label="Investigator"
            options={ALL_INVESTIGATORS.map((i) => ({ value: i, label: i }))}
            selected={investigator}
            onChange={setInvestigator}
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
          <TogglePill label="Open only" active={openOnly} onToggle={() => setOpenOnly((v) => !v)} />
          <TogglePill
            label="Escalated only"
            active={escalatedOnly}
            onToggle={() => setEscalatedOnly((v) => !v)}
          />
        </FilterBar>
      </div>

      <InvestigationQueue rows={filtered} />
    </div>
  );
}

// ---------------------------------------------------------------------
function MetricTile({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof ShieldAlert;
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

function InvestigationQueue({ rows }: { rows: Investigation[] }) {
  if (rows.length === 0) return <EmptyState title="No investigations match your filters." />;
  return (
    <>
      {/* Desktop table */}
      <div className="hidden overflow-x-auto rounded-lg border border-border bg-card md:block">
        <table
          className="w-full min-w-[1000px] border-separate border-spacing-0 text-left text-sm"
          aria-label="Investigation queue"
        >
          <thead>
            <tr className="bg-muted/60 text-xs uppercase tracking-wide text-muted-foreground">
              <th className="border-b border-border px-3 py-2 font-medium">Risk</th>
              <th className="border-b border-border px-3 py-2 font-medium">Subject</th>
              <th className="border-b border-border px-3 py-2 font-medium">Category</th>
              <th className="border-b border-border px-3 py-2 font-medium">Reason</th>
              <th className="border-b border-border px-3 py-2 font-medium">Status</th>
              <th className="border-b border-border px-3 py-2 font-medium">Owner</th>
              <th className="border-b border-border px-3 py-2 font-medium">Created</th>
              <th className="border-b border-border px-3 py-2 font-medium">Last activity</th>
              <th className="border-b border-border px-3 py-2 font-medium">Priority</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((inv) => (
              <tr key={inv.id} className="hover:bg-accent/40">
                <td className="border-b border-border px-3 py-2 align-top">
                  <Link
                    to="/admin/risk/$investigationId"
                    params={{ investigationId: inv.id }}
                    className="inline-block"
                  >
                    <RiskLevelBadge level={inv.riskLevel} />
                  </Link>
                </td>
                <td className="border-b border-border px-3 py-2 align-top text-sm">
                  <Link
                    to="/admin/risk/$investigationId"
                    params={{ investigationId: inv.id }}
                    className="font-medium text-foreground underline-offset-2 hover:underline"
                  >
                    {inv.subject.displayName}
                  </Link>
                  <div className="text-[11px] text-muted-foreground">
                    {SUBJECT_KIND_LABEL[inv.subject.kind]} · {inv.reference}
                  </div>
                </td>
                <td className="border-b border-border px-3 py-2 align-top text-xs text-muted-foreground">
                  {RISK_CATEGORY_LABEL[inv.category]}
                </td>
                <td className="border-b border-border px-3 py-2 align-top text-xs text-foreground">
                  {inv.reason}
                </td>
                <td className="border-b border-border px-3 py-2 align-top">
                  <InvestigationStatusBadge status={inv.status} />
                </td>
                <td className="border-b border-border px-3 py-2 align-top text-xs text-muted-foreground">
                  {inv.owner}
                </td>
                <td className="border-b border-border px-3 py-2 align-top text-xs text-muted-foreground">
                  {formatRelativeTime(inv.createdAt)}
                </td>
                <td className="border-b border-border px-3 py-2 align-top text-xs text-muted-foreground">
                  {formatRelativeTime(inv.updatedAt)}
                </td>
                <td className="border-b border-border px-3 py-2 align-top text-xs">
                  <PriorityChip priority={inv.priority} />
                  {inv.escalated ? (
                    <span className="ml-1 rounded bg-rose-50 px-1.5 py-0.5 text-[10px] font-medium text-rose-800 ring-1 ring-inset ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60">
                      Escalated
                    </span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <ul className="grid grid-cols-1 gap-2 md:hidden">
        {rows.map((inv) => (
          <li key={inv.id}>
            <Link
              to="/admin/risk/$investigationId"
              params={{ investigationId: inv.id }}
              className="block rounded-lg border border-border bg-card p-3 hover:bg-accent/40"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-foreground">
                    {inv.subject.displayName}
                  </p>
                  <p className="truncate text-[11px] text-muted-foreground">
                    {SUBJECT_KIND_LABEL[inv.subject.kind]} · {RISK_CATEGORY_LABEL[inv.category]}
                  </p>
                </div>
                <RiskLevelBadge level={inv.riskLevel} />
              </div>
              <p className="mt-1.5 text-xs text-foreground">{inv.reason}</p>
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                <InvestigationStatusBadge status={inv.status} />
                <span>Owner: {inv.owner}</span>
                <span>Opened {formatRelativeTime(inv.createdAt)}</span>
                {inv.escalated ? (
                  <span className="text-rose-700 dark:text-rose-300">Escalated</span>
                ) : null}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}

// ---------------------------------------------------------------------
// Badges
// ---------------------------------------------------------------------
const LEVEL_CLASS: Record<RiskLevel, string> = {
  critical:
    "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60",
  high: "bg-orange-50 text-orange-900 ring-orange-200 dark:bg-orange-950/40 dark:text-orange-200 dark:ring-orange-900/60",
  medium:
    "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60",
  low: "bg-zinc-100 text-zinc-800 ring-zinc-200 dark:bg-zinc-800/60 dark:text-zinc-200 dark:ring-zinc-700",
};
export function RiskLevelBadge({ level }: { level: RiskLevel }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        LEVEL_CLASS[level],
      )}
    >
      <span aria-hidden className="size-1.5 rounded-full bg-current opacity-70" />
      {RISK_LEVEL_LABEL[level]}
    </span>
  );
}

const STATUS_CLASS: Record<InvestigationStatus, string> = {
  open: "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60",
  in_review:
    "bg-sky-50 text-sky-900 ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:ring-sky-900/60",
  pending_evidence:
    "bg-orange-50 text-orange-900 ring-orange-200 dark:bg-orange-950/40 dark:text-orange-200 dark:ring-orange-900/60",
  pending_ts_review:
    "bg-violet-50 text-violet-900 ring-violet-200 dark:bg-violet-950/40 dark:text-violet-200 dark:ring-violet-900/60",
  escalated:
    "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60",
  resolved_action_taken:
    "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-900/60",
  resolved_no_action:
    "bg-zinc-100 text-zinc-800 ring-zinc-200 dark:bg-zinc-800/60 dark:text-zinc-200 dark:ring-zinc-700",
  closed_duplicate:
    "bg-zinc-100 text-zinc-800 ring-zinc-200 dark:bg-zinc-800/60 dark:text-zinc-200 dark:ring-zinc-700",
};
export function InvestigationStatusBadge({ status }: { status: InvestigationStatus }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        STATUS_CLASS[status],
      )}
    >
      {INVESTIGATION_STATUS_LABEL[status]}
    </span>
  );
}

function PriorityChip({ priority }: { priority: "critical" | "high" | "normal" }) {
  const map = {
    critical: "text-rose-700 dark:text-rose-300",
    high: "text-amber-700 dark:text-amber-300",
    normal: "text-muted-foreground",
  } as const;
  return (
    <span className={cn("text-[11px] font-medium capitalize", map[priority])}>{priority}</span>
  );
}

// ---------------------------------------------------------------------
// Filter helpers
// ---------------------------------------------------------------------
const RISK_LEVEL_OPTIONS: { value: RiskLevel; label: string }[] = (
  ["critical", "high", "medium", "low"] as RiskLevel[]
).map((v) => ({ value: v, label: RISK_LEVEL_LABEL[v] }));

const STATUS_OPTIONS: { value: InvestigationStatus; label: string }[] = (
  [
    "open",
    "in_review",
    "pending_evidence",
    "pending_ts_review",
    "escalated",
    "resolved_action_taken",
    "resolved_no_action",
    "closed_duplicate",
  ] as InvestigationStatus[]
).map((v) => ({ value: v, label: INVESTIGATION_STATUS_LABEL[v] }));

const CATEGORY_OPTIONS: { value: RiskCategory; label: string }[] = (
  Object.keys(RISK_CATEGORY_LABEL) as RiskCategory[]
).map((v) => ({ value: v, label: RISK_CATEGORY_LABEL[v] }));

const SUBJECT_OPTIONS: { value: SubjectKind; label: string }[] = (
  ["user", "organization", "case"] as SubjectKind[]
).map((v) => ({ value: v, label: SUBJECT_KIND_LABEL[v] }));

function uniqueSorted<T>(arr: T[]): T[] {
  return Array.from(new Set(arr)).sort();
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
    <label className="inline-flex h-8 items-center gap-1 rounded-md border border-border bg-background px-2 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
        className="h-full bg-transparent text-xs text-foreground focus:outline-none"
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
      aria-pressed={active}
      className={cn(
        "inline-flex h-8 items-center rounded-md border px-2 text-xs font-medium",
        active
          ? "border-foreground bg-foreground text-background"
          : "border-border bg-background text-foreground hover:bg-accent",
      )}
    >
      {label}
    </button>
  );
}
