import { useMemo, useState } from "react";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import { ArrowUpRight, Bookmark, Download, SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";

import { StatusBadge } from "@/features/admin/components/status-badge";
import { PriorityBadge } from "@/features/admin/components/priority-badge";
import { AdminSearchField } from "@/features/admin/components/search-field";
import {
  AdminDataTable,
  type AdminTableColumn,
  type SortDirection,
} from "@/features/admin/components/data-table";
import { TablePagination } from "@/features/admin/components/table-pagination";
import { FilterBar, FilterMultiSelect } from "@/features/admin/components/filter-bar";
import { CasePreviewDrawer } from "@/features/admin/components/case-preview-drawer";
import { EmptyState } from "@/features/admin/components/states";
import { formatAge, formatRelativeTime } from "@/features/admin/lib/format";
import {
  ALL_ASSIGNEES,
  ATTENTION_FLAG_LABEL,
  COMPLETED_STATUSES,
  ORGANIZATION_STATUS_LABEL,
  SLA_LABEL,
  VERIFICATION_TYPE_LABEL,
  mockVerificationCases,
  type Assignee,
  type AttentionFlag,
  type OrganizationStatus,
  type SlaState,
  type VerificationCase,
  type VerificationType,
} from "@/features/admin/data/verifications";
import type { Priority, VerificationStatus } from "@/features/admin/data/types";

// ---------- View definitions ----------

type ViewId =
  | "all-active"
  | "pending-review"
  | "corrections"
  | "resubmitted"
  | "awaiting-organization"
  | "awaiting-employer"
  | "clarification"
  | "failed-outreach"
  | "completed";

const VALID_VIEWS: ViewId[] = [
  "all-active",
  "pending-review",
  "corrections",
  "resubmitted",
  "awaiting-organization",
  "awaiting-employer",
  "clarification",
  "failed-outreach",
  "completed",
];

const VIEW_LABEL: Record<ViewId, string> = {
  "all-active": "All active",
  "pending-review": "Pending review",
  corrections: "Corrections",
  resubmitted: "Resubmitted",
  "awaiting-organization": "Awaiting organization",
  "awaiting-employer": "Awaiting employer",
  clarification: "Clarification",
  "failed-outreach": "Failed outreach",
  completed: "Completed",
};

const VIEW_STATUSES: Record<ViewId, VerificationStatus[] | null> = {
  "all-active": null, // everything except completed statuses
  "pending-review": ["pending_review"],
  corrections: ["corrections_requested"],
  resubmitted: ["resubmitted"],
  "awaiting-organization": ["awaiting_organization"],
  "awaiting-employer": ["awaiting_employer"],
  clarification: ["clarification_requested"],
  "failed-outreach": ["failed_outreach"],
  completed: COMPLETED_STATUSES,
};

function viewMatches(view: ViewId, status: VerificationStatus): boolean {
  const allowed = VIEW_STATUSES[view];
  if (allowed === null) return !COMPLETED_STATUSES.includes(status);
  return allowed.includes(status);
}

// ---------- Search-param validation ----------
// Plain function validator — no zod-adapter installed. Unknown values fall back.

interface QueueSearch {
  view: ViewId;
}

export const Route = createFileRoute("/admin/verifications/")({
  head: () => ({
    meta: [
      { title: "Verifications — Kairo Admin" },
      { name: "description", content: "Verification queue for the Kairo operations team." },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  validateSearch: (raw: Record<string, unknown>) => {
    const v = typeof raw.view === "string" ? raw.view : "";
    const view: ViewId = (VALID_VIEWS as string[]).includes(v) ? (v as ViewId) : "all-active";
    return { view } satisfies QueueSearch;
  },
  component: VerificationsPage,
});

// ---------- Sorting ----------

type SortKey = "oldest" | "newest" | "priority" | "sla" | "updated";

const SORT_LABEL: Record<SortKey, string> = {
  oldest: "Oldest first",
  newest: "Newest first",
  priority: "Highest priority",
  sla: "SLA risk",
  updated: "Recently updated",
};

const PRIORITY_RANK: Record<Priority, number> = { urgent: 3, high: 2, normal: 1, low: 0 };
const SLA_RANK: Record<SlaState, number> = { breached: 2, approaching: 1, within: 0 };

function defaultOperationalOrder(a: VerificationCase, b: VerificationCase): number {
  // Urgent priority → breached SLA → oldest submitted.
  const p = PRIORITY_RANK[b.priority] - PRIORITY_RANK[a.priority];
  if (p !== 0) return p;
  const s = SLA_RANK[b.slaState] - SLA_RANK[a.slaState];
  if (s !== 0) return s;
  return new Date(a.submittedAt).getTime() - new Date(b.submittedAt).getTime();
}

function sortCases(list: VerificationCase[], key: SortKey): VerificationCase[] {
  const arr = [...list];
  switch (key) {
    case "oldest":
      return arr.sort(
        (a, b) => new Date(a.submittedAt).getTime() - new Date(b.submittedAt).getTime(),
      );
    case "newest":
      return arr.sort(
        (a, b) => new Date(b.submittedAt).getTime() - new Date(a.submittedAt).getTime(),
      );
    case "priority":
      return arr.sort(
        (a, b) =>
          PRIORITY_RANK[b.priority] - PRIORITY_RANK[a.priority] || defaultOperationalOrder(a, b),
      );
    case "sla":
      return arr.sort(
        (a, b) => SLA_RANK[b.slaState] - SLA_RANK[a.slaState] || defaultOperationalOrder(a, b),
      );
    case "updated":
      return arr.sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
  }
}

// ---------- Column sort mapping ----------
// Clicking a table header maps to a SortKey.
const COL_TO_SORT: Record<string, SortKey> = {
  priority: "priority",
  submitted: "oldest",
  age: "sla",
  status: "updated",
};

// ---------- Page ----------

function VerificationsPage() {
  // validateSearch already narrows to ViewId; the extra guard is defensive.
  const rawView = Route.useSearch().view as string;
  const view: ViewId = (VALID_VIEWS as string[]).includes(rawView)
    ? (rawView as ViewId)
    : "all-active";
  const navigate = useNavigate({ from: Route.fullPath });

  // Local mock state: assignment overrides + activity trail. In-memory only.
  const [assignmentOverrides, setAssignmentOverrides] = useState<Record<string, Assignee>>({});
  const [priorityOverrides, setPriorityOverrides] = useState<Record<string, Priority>>({});
  const [localActivity, setLocalActivity] = useState<
    { caseId: string; message: string; at: string }[]
  >([]);

  // Filters
  const [query, setQuery] = useState("");
  const [fType, setFType] = useState<Set<string>>(new Set());
  const [fPriority, setFPriority] = useState<Set<string>>(new Set());
  const [fReviewer, setFReviewer] = useState<Set<string>>(new Set());
  const [fOrg, setFOrg] = useState<Set<string>>(new Set());
  const [fSla, setFSla] = useState<Set<string>>(new Set());
  const [fFlag, setFFlag] = useState<Set<string>>(new Set());
  const [fSubmittedWindow, setFSubmittedWindow] = useState<Set<string>>(new Set());

  const [sortKey, setSortKey] = useState<SortKey>("priority");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);

  // Apply overrides to base data.
  const cases = useMemo<VerificationCase[]>(
    () =>
      mockVerificationCases.map((c) => ({
        ...c,
        assignedReviewer: assignmentOverrides[c.id] ?? c.assignedReviewer,
        priority: priorityOverrides[c.id] ?? c.priority,
      })),
    [assignmentOverrides, priorityOverrides],
  );

  // Counts per view (respect assignment/priority overrides).
  const viewCounts = useMemo(() => {
    const counts: Record<ViewId, number> = {} as Record<ViewId, number>;
    for (const v of VALID_VIEWS) counts[v] = cases.filter((c) => viewMatches(v, c.status)).length;
    return counts;
  }, [cases]);

  // Header summary uses all active cases (regardless of selected view).
  const headerSummary = useMemo(() => {
    const active = cases.filter((c) => !COMPLETED_STATUSES.includes(c.status));
    const urgent = active.filter((c) => c.priority === "urgent").length;
    const unassigned = active.filter((c) => c.assignedReviewer === "Unassigned").length;
    const oldest = active.reduce<VerificationCase | null>(
      (acc, c) => (!acc || new Date(c.submittedAt) < new Date(acc.submittedAt) ? c : acc),
      null,
    );
    return { requiringAction: active.length, urgent, unassigned, oldest };
  }, [cases]);

  // Filter pipeline.
  const filtered = useMemo(() => {
    let list = cases.filter((c) => viewMatches(view, c.status));
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      list = list.filter(
        (c) =>
          c.candidateName.toLowerCase().includes(q) ||
          c.candidateEmail.toLowerCase().includes(q) ||
          c.organizationName.toLowerCase().includes(q) ||
          c.roleOrProgram.toLowerCase().includes(q) ||
          c.reference.toLowerCase().includes(q),
      );
    }
    if (fType.size) list = list.filter((c) => fType.has(c.verificationType));
    if (fPriority.size) list = list.filter((c) => fPriority.has(c.priority));
    if (fReviewer.size) list = list.filter((c) => fReviewer.has(c.assignedReviewer));
    if (fOrg.size) list = list.filter((c) => fOrg.has(c.organizationStatus));
    if (fSla.size) list = list.filter((c) => fSla.has(c.slaState));
    if (fFlag.size) list = list.filter((c) => c.attentionFlags.some((f) => fFlag.has(f)));
    if (fSubmittedWindow.size) {
      const now = Date.now();
      list = list.filter((c) => {
        const ageDays = (now - new Date(c.submittedAt).getTime()) / 86_400_000;
        const buckets: string[] = [];
        if (ageDays <= 1) buckets.push("24h");
        if (ageDays <= 7) buckets.push("7d");
        if (ageDays <= 30) buckets.push("30d");
        if (ageDays > 30) buckets.push("older");
        return buckets.some((b) => fSubmittedWindow.has(b));
      });
    }
    return sortCases(list, sortKey);
  }, [
    cases,
    view,
    query,
    fType,
    fPriority,
    fReviewer,
    fOrg,
    fSla,
    fFlag,
    fSubmittedWindow,
    sortKey,
  ]);

  const totalActiveFilters =
    fType.size +
    fPriority.size +
    fReviewer.size +
    fOrg.size +
    fSla.size +
    fFlag.size +
    fSubmittedWindow.size;

  // Reset page whenever filters/view change and the current page overshoots.
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const paginated = filtered.slice((safePage - 1) * pageSize, safePage * pageSize);

  const previewCase = useMemo(
    () => (previewId ? (cases.find((c) => c.id === previewId) ?? null) : null),
    [previewId, cases],
  );

  function setView(next: ViewId) {
    setPage(1);
    setSelectedIds(new Set());
    navigate({ search: { view: next }, replace: true });
  }

  function clearAllFilters() {
    setFType(new Set());
    setFPriority(new Set());
    setFReviewer(new Set());
    setFOrg(new Set());
    setFSla(new Set());
    setFFlag(new Set());
    setFSubmittedWindow(new Set());
    setPage(1);
  }

  function bulkAssign(assignee: Assignee) {
    const next = { ...assignmentOverrides };
    const entries: typeof localActivity = [];
    for (const id of selectedIds) {
      next[id] = assignee;
      entries.push({
        caseId: id,
        message: `Assigned to ${assignee} (mock)`,
        at: new Date().toISOString(),
      });
    }
    setAssignmentOverrides(next);
    setLocalActivity((a) => [...entries, ...a].slice(0, 20));
    setSelectedIds(new Set());
  }

  function bulkPriority(p: Priority) {
    const next = { ...priorityOverrides };
    const entries: typeof localActivity = [];
    for (const id of selectedIds) {
      next[id] = p;
      entries.push({
        caseId: id,
        message: `Priority set to ${p} (mock)`,
        at: new Date().toISOString(),
      });
    }
    setPriorityOverrides(next);
    setLocalActivity((a) => [...entries, ...a].slice(0, 20));
    setSelectedIds(new Set());
  }

  // ----- Columns -----
  const columns: AdminTableColumn<VerificationCase>[] = [
    {
      id: "case",
      header: "Case",
      cell: (c) => (
        <div className="min-w-[160px]">
          <div className="font-mono text-[11px] font-medium text-muted-foreground">
            {c.reference}
          </div>
          <div className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
            {c.lastActivitySummary}
          </div>
        </div>
      ),
    },
    {
      id: "candidate",
      header: "Candidate",
      cell: (c) => (
        <div className="flex min-w-[180px] items-start gap-2">
          <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-[10px] font-semibold text-foreground">
            {c.candidateAvatarInitials}
          </span>
          <div className="min-w-0">
            <div className="truncate font-medium text-foreground">{c.candidateName}</div>
            <div className="truncate text-xs text-muted-foreground">{c.candidateEmail}</div>
          </div>
        </div>
      ),
    },
    {
      id: "organization",
      header: "Organization",
      cell: (c) => (
        <div className="min-w-[160px]">
          <div className="truncate text-foreground">{c.organizationName}</div>
          <div className="text-xs text-muted-foreground">
            {ORGANIZATION_STATUS_LABEL[c.organizationStatus]}
          </div>
        </div>
      ),
    },
    {
      id: "verification",
      header: "Verification",
      cell: (c) => (
        <div className="min-w-[140px]">
          <div className="text-foreground">{VERIFICATION_TYPE_LABEL[c.verificationType]}</div>
          <div className="truncate text-xs text-muted-foreground">{c.roleOrProgram}</div>
        </div>
      ),
    },
    {
      id: "status",
      header: "Status",
      sortable: true,
      cell: (c) => <StatusBadge status={c.status} />,
    },
    {
      id: "priority",
      header: "Priority",
      sortable: true,
      cell: (c) => <PriorityBadge priority={c.priority} />,
    },
    {
      id: "assigned",
      header: "Assigned to",
      cell: (c) => (
        <span
          className={cn(
            "text-foreground",
            c.assignedReviewer === "Unassigned" && "text-muted-foreground italic",
          )}
        >
          {c.assignedReviewer}
        </span>
      ),
    },
    {
      id: "evidence",
      header: "Evidence",
      align: "right",
      cell: (c) => <span className="tabular-nums">{c.evidenceCount}</span>,
    },
    {
      id: "submitted",
      header: "Submitted",
      sortable: true,
      cell: (c) => (
        <div>
          <div className="tabular-nums text-foreground">
            {new Date(c.submittedAt).toLocaleDateString()}
          </div>
          <div className="text-xs text-muted-foreground">{formatRelativeTime(c.submittedAt)}</div>
        </div>
      ),
    },
    {
      id: "age",
      header: "Age",
      sortable: true,
      cell: (c) => {
        const hours = Math.max(
          0,
          Math.round((Date.now() - new Date(c.submittedAt).getTime()) / 3_600_000),
        );
        const tone =
          c.slaState === "breached"
            ? "text-rose-700 dark:text-rose-400"
            : c.slaState === "approaching"
              ? "text-amber-700 dark:text-amber-400"
              : "text-muted-foreground";
        return (
          <div>
            <div className="tabular-nums text-foreground">{formatAge(hours)}</div>
            <div className={cn("text-xs", tone)}>{SLA_LABEL[c.slaState]}</div>
          </div>
        );
      },
    },
    {
      id: "attention",
      header: "Attention",
      cell: (c) =>
        c.attentionFlags.length === 0 ? (
          <span className="text-xs text-muted-foreground">—</span>
        ) : c.attentionFlags.length <= 2 ? (
          <div className="flex flex-wrap gap-1">
            {c.attentionFlags.map((f) => (
              <span
                key={f}
                className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-900 ring-1 ring-inset ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60"
              >
                {ATTENTION_FLAG_LABEL[f]}
              </span>
            ))}
          </div>
        ) : (
          <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-900 ring-1 ring-inset ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60">
            {c.attentionFlags.length} flags
          </span>
        ),
    },
  ];

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-4">
      {/* Header */}
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-foreground">Verifications</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Review, resolve and track verification cases across Kairo.
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            title="Saved views coming soon"
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-2 text-xs text-muted-foreground hover:text-foreground"
          >
            <Bookmark aria-hidden className="size-3.5" /> Saved views
          </button>
          <button
            type="button"
            title="Export is not available yet"
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-2 text-xs text-muted-foreground hover:text-foreground"
          >
            <Download aria-hidden className="size-3.5" /> Export
          </button>
        </div>
      </header>

      {/* Header summary */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <SummaryTile
          label="Requiring action"
          value={headerSummary.requiringAction.toString()}
          tone="foreground"
        />
        <SummaryTile
          label="Urgent cases"
          value={headerSummary.urgent.toString()}
          tone={headerSummary.urgent > 0 ? "rose" : "muted"}
        />
        <SummaryTile
          label="Oldest waiting"
          value={
            headerSummary.oldest
              ? formatAge(
                  Math.round(
                    (Date.now() - new Date(headerSummary.oldest.submittedAt).getTime()) / 3_600_000,
                  ),
                )
              : "—"
          }
          tone="amber"
        />
        <SummaryTile
          label="Unassigned"
          value={headerSummary.unassigned.toString()}
          tone={headerSummary.unassigned > 0 ? "amber" : "muted"}
        />
      </div>

      {/* Sub-queue tabs */}
      <nav aria-label="Workflow sub-queues" className="-mx-1 overflow-x-auto">
        <ul
          role="tablist"
          className="flex min-w-max items-center gap-1 border-b border-border px-1"
        >
          {VALID_VIEWS.map((v) => {
            const active = v === view;
            return (
              <li key={v} role="none">
                <button
                  role="tab"
                  aria-selected={active}
                  onClick={() => setView(v)}
                  className={cn(
                    "inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium transition-colors",
                    active
                      ? "border-foreground text-foreground"
                      : "border-transparent text-muted-foreground hover:text-foreground",
                  )}
                >
                  {VIEW_LABEL[v]}
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[10px] tabular-nums",
                      active ? "bg-foreground text-background" : "bg-muted text-muted-foreground",
                    )}
                  >
                    {viewCounts[v]}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Toolbar: search + filters + sort */}
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-1 items-center gap-2 md:max-w-md">
          <AdminSearchField
            value={query}
            onChange={(v) => {
              setQuery(v);
              setPage(1);
            }}
            placeholder="Search name, email, org, role or reference"
            ariaLabel="Search verification cases"
          />
          <button
            type="button"
            onClick={() => setMobileFiltersOpen((v) => !v)}
            className="inline-flex h-8 items-center gap-1 rounded-md border border-border bg-background px-2 text-xs md:hidden"
            aria-expanded={mobileFiltersOpen}
          >
            <SlidersHorizontal aria-hidden className="size-3.5" />
            Filters
            {totalActiveFilters > 0 ? (
              <span className="rounded bg-foreground px-1.5 text-[10px] font-semibold text-background">
                {totalActiveFilters}
              </span>
            ) : null}
          </button>
        </div>

        <div
          className={cn(
            "flex flex-wrap items-center gap-2",
            "md:flex",
            !mobileFiltersOpen && "hidden md:flex",
          )}
        >
          <FilterBar activeCount={totalActiveFilters} onClear={clearAllFilters}>
            <FilterMultiSelect
              label="Type"
              options={(Object.keys(VERIFICATION_TYPE_LABEL) as VerificationType[]).map((t) => ({
                value: t,
                label: VERIFICATION_TYPE_LABEL[t],
              }))}
              selected={fType}
              onChange={(s) => {
                setFType(s);
                setPage(1);
              }}
            />
            <FilterMultiSelect
              label="Priority"
              options={(["urgent", "high", "normal", "low"] as Priority[]).map((p) => ({
                value: p,
                label: p[0].toUpperCase() + p.slice(1),
              }))}
              selected={fPriority}
              onChange={(s) => {
                setFPriority(s);
                setPage(1);
              }}
            />
            <FilterMultiSelect
              label="Assigned"
              options={ALL_ASSIGNEES.map((a) => ({ value: a, label: a }))}
              selected={fReviewer}
              onChange={(s) => {
                setFReviewer(s);
                setPage(1);
              }}
            />
            <FilterMultiSelect
              label="Organization"
              options={(Object.keys(ORGANIZATION_STATUS_LABEL) as OrganizationStatus[]).map(
                (o) => ({
                  value: o,
                  label: ORGANIZATION_STATUS_LABEL[o],
                }),
              )}
              selected={fOrg}
              onChange={(s) => {
                setFOrg(s);
                setPage(1);
              }}
            />
            <FilterMultiSelect
              label="SLA"
              options={(["within", "approaching", "breached"] as SlaState[]).map((s) => ({
                value: s,
                label: SLA_LABEL[s],
              }))}
              selected={fSla}
              onChange={(s) => {
                setFSla(s);
                setPage(1);
              }}
            />
            <FilterMultiSelect
              label="Submitted"
              options={[
                { value: "24h", label: "Last 24h" },
                { value: "7d", label: "Last 7 days" },
                { value: "30d", label: "Last 30 days" },
                { value: "older", label: "Older than 30 days" },
              ]}
              selected={fSubmittedWindow}
              onChange={(s) => {
                setFSubmittedWindow(s);
                setPage(1);
              }}
            />
            <FilterMultiSelect
              label="Flags"
              options={(Object.keys(ATTENTION_FLAG_LABEL) as AttentionFlag[]).map((f) => ({
                value: f,
                label: ATTENTION_FLAG_LABEL[f],
              }))}
              selected={fFlag}
              onChange={(s) => {
                setFFlag(s);
                setPage(1);
              }}
            />
          </FilterBar>
          <label className="ml-auto inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            Sort
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
              className="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              aria-label="Sort"
            >
              {(Object.keys(SORT_LABEL) as SortKey[]).map((k) => (
                <option key={k} value={k}>
                  {SORT_LABEL[k]}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {/* Bulk action bar */}
      {selectedIds.size > 0 ? (
        <div
          role="region"
          aria-label="Bulk actions"
          className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-foreground/20 bg-foreground/5 px-3 py-2 text-xs"
        >
          <div className="text-foreground">
            <span className="font-semibold tabular-nums">{selectedIds.size}</span>{" "}
            {selectedIds.size === 1 ? "case" : "cases"} selected
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <BulkMenu label="Assign reviewer">
              {ALL_ASSIGNEES.map((a) => (
                <button
                  key={a}
                  onClick={() => bulkAssign(a)}
                  className="block w-full rounded px-2 py-1.5 text-left text-xs hover:bg-accent"
                >
                  {a}
                </button>
              ))}
            </BulkMenu>
            <BulkMenu label="Change priority">
              {(["urgent", "high", "normal", "low"] as Priority[]).map((p) => (
                <button
                  key={p}
                  onClick={() => bulkPriority(p)}
                  className="block w-full rounded px-2 py-1.5 text-left text-xs capitalize hover:bg-accent"
                >
                  {p}
                </button>
              ))}
            </BulkMenu>
            <button
              onClick={() =>
                toast("Export coming later", {
                  description: "Bulk export isn't wired up yet — this action is a placeholder.",
                })
              }
              className="inline-flex h-7 items-center gap-1 rounded-md border border-border bg-background px-2 hover:bg-accent"
            >
              <Download aria-hidden className="size-3" /> Export selected
            </button>

            <button
              onClick={() => setSelectedIds(new Set())}
              className="ml-1 rounded px-2 py-1 text-muted-foreground hover:text-foreground"
            >
              Clear
            </button>
          </div>
        </div>
      ) : null}

      {/* Desktop table */}
      <div className="hidden overflow-hidden rounded-lg border border-border bg-card md:block">
        <AdminDataTable<VerificationCase>
          ariaLabel="Verification cases"
          columns={columns}
          rows={paginated}
          rowKey={(c) => c.id}
          onRowClick={(c) => setPreviewId(c.id)}
          selection={{
            selectedIds,
            onToggle: (id) => {
              const next = new Set(selectedIds);
              if (next.has(id)) next.delete(id);
              else next.add(id);
              setSelectedIds(next);
            },
            onToggleAll: (ids) => {
              const allSelected = ids.every((id) => selectedIds.has(id));
              const next = new Set(selectedIds);
              if (allSelected) ids.forEach((id) => next.delete(id));
              else ids.forEach((id) => next.add(id));
              setSelectedIds(next);
            },
          }}
          sort={{ id: sortKeyToColumn(sortKey), direction: sortKeyDirection(sortKey) }}
          onSortChange={(colId) => {
            const key = COL_TO_SORT[colId];
            if (key) setSortKey(key);
          }}
          empty={
            <EmptyStateFor
              query={query}
              activeFilters={totalActiveFilters}
              viewLabel={VIEW_LABEL[view]}
              onClearFilters={clearAllFilters}
              onClearSearch={() => setQuery("")}
            />
          }
        />
        <TablePagination
          page={safePage}
          pageSize={pageSize}
          total={filtered.length}
          onPageChange={setPage}
          onPageSizeChange={(s) => {
            setPageSize(s);
            setPage(1);
          }}
        />
      </div>

      {/* Mobile cards */}
      <div className="flex flex-col gap-2 md:hidden">
        {paginated.length === 0 ? (
          <EmptyStateFor
            query={query}
            activeFilters={totalActiveFilters}
            viewLabel={VIEW_LABEL[view]}
            onClearFilters={clearAllFilters}
            onClearSearch={() => setQuery("")}
          />
        ) : (
          paginated.map((c) => (
            <button
              key={c.id}
              onClick={() => setPreviewId(c.id)}
              className="rounded-lg border border-border bg-card p-3 text-left hover:bg-accent/40"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {c.reference}
                    </span>
                    <StatusBadge status={c.status} />
                  </div>
                  <div className="mt-1 truncate text-sm font-medium text-foreground">
                    {c.candidateName}
                  </div>
                  <div className="truncate text-xs text-muted-foreground">{c.organizationName}</div>
                </div>
                <PriorityBadge priority={c.priority} />
              </div>
              <div className="mt-2 grid grid-cols-2 gap-1 text-[11px] text-muted-foreground">
                <div>
                  Age:{" "}
                  <span className="tabular-nums text-foreground">
                    {formatAge(
                      Math.max(
                        0,
                        Math.round((Date.now() - new Date(c.submittedAt).getTime()) / 3_600_000),
                      ),
                    )}
                  </span>
                </div>
                <div className="truncate">
                  Assigned: <span className="text-foreground">{c.assignedReviewer}</span>
                </div>
                <div>
                  Attention: <span className="text-foreground">{c.attentionFlags.length}</span>
                </div>
                <div>{SLA_LABEL[c.slaState]}</div>
              </div>
            </button>
          ))
        )}
        {paginated.length > 0 ? (
          <TablePagination
            page={safePage}
            pageSize={pageSize}
            total={filtered.length}
            onPageChange={setPage}
            onPageSizeChange={(s) => {
              setPageSize(s);
              setPage(1);
            }}
          />
        ) : null}
      </div>

      {/* Local activity log (mock only) */}
      {localActivity.length > 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-muted/40 p-3 text-xs text-muted-foreground">
          <div className="mb-1 font-semibold text-foreground">
            Local mock activity (session-only)
          </div>
          <ul className="space-y-0.5">
            {localActivity.slice(0, 5).map((e, i) => (
              <li key={i}>
                <span className="font-mono">{e.caseId}</span> · {e.message} ·{" "}
                {formatRelativeTime(e.at)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <CasePreviewDrawer
        caseRecord={previewCase}
        open={!!previewCase}
        onOpenChange={(o) => !o && setPreviewId(null)}
      />
    </div>
  );
}

function SummaryTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "foreground" | "rose" | "amber" | "muted";
}) {
  const toneClass =
    tone === "rose"
      ? "text-rose-700 dark:text-rose-400"
      : tone === "amber"
        ? "text-amber-700 dark:text-amber-400"
        : tone === "muted"
          ? "text-muted-foreground"
          : "text-foreground";
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2">
      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className={cn("mt-0.5 text-xl font-semibold tabular-nums", toneClass)}>{value}</div>
    </div>
  );
}

function BulkMenu({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex h-7 items-center gap-1 rounded-md border border-border bg-background px-2 hover:bg-accent"
      >
        {label}
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
            className="absolute right-0 z-20 mt-1 w-44 rounded-md border border-border bg-popover p-1 shadow-md"
            onClick={() => setOpen(false)}
          >
            {children}
          </div>
        </>
      ) : null}
    </div>
  );
}

function EmptyStateFor({
  query,
  activeFilters,
  viewLabel,
  onClearFilters,
  onClearSearch,
}: {
  query: string;
  activeFilters: number;
  viewLabel: string;
  onClearFilters: () => void;
  onClearSearch: () => void;
}) {
  if (query) {
    return (
      <EmptyState
        title="No matching cases"
        description={`No verification cases match “${query}” in ${viewLabel}.`}
        action={
          <button
            onClick={onClearSearch}
            className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-xs hover:bg-accent"
          >
            Clear search
          </button>
        }
      />
    );
  }
  if (activeFilters > 0) {
    return (
      <EmptyState
        title="No cases match your filters"
        description={`${activeFilters} filters active in ${viewLabel}.`}
        action={
          <button
            onClick={onClearFilters}
            className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-xs hover:bg-accent"
          >
            Clear all filters
          </button>
        }
      />
    );
  }
  return (
    <EmptyState
      title={`${viewLabel} is clear`}
      description="No verification cases in this queue right now."
      action={
        <Link
          to="/admin/verifications"
          search={{ view: "all-active" }}
          className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-xs hover:bg-accent"
        >
          <ArrowUpRight aria-hidden className="size-3" /> Back to All active
        </Link>
      }
    />
  );
}

function sortKeyToColumn(k: SortKey): string {
  switch (k) {
    case "priority":
      return "priority";
    case "oldest":
    case "newest":
      return "submitted";
    case "sla":
      return "age";
    case "updated":
      return "status";
  }
}
function sortKeyDirection(k: SortKey): SortDirection {
  switch (k) {
    case "newest":
      return "desc";
    case "oldest":
      return "asc";
    case "priority":
    case "sla":
    case "updated":
      return "desc";
  }
}
