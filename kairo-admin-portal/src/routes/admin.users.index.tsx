import { useMemo, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { AlertTriangle, ShieldCheck, Users as UsersIcon } from "lucide-react";
import { WorkspaceSection } from "@/features/admin/components/workspace-section";
import { AdminSearchField } from "@/features/admin/components/search-field";
import { EmptyState } from "@/features/admin/components/states";
import { formatRelativeTime } from "@/features/admin/lib/format";
import {
  ACCOUNT_STATUS_LABEL,
  PASSPORT_STATUS_LABEL,
  PROFILE_TYPE_LABEL,
  getUserDirectoryMetrics,
  initialsFor,
  mockUsers,
  type PassportStatus,
  type ProfileType,
  type UserAccountStatus,
  type UserRecord,
} from "@/features/admin/data/users";

export const Route = createFileRoute("/admin/users/")({
  head: () => ({
    meta: [{ title: "Users — Kairo Admin" }, { name: "robots", content: "noindex, nofollow" }],
  }),
  component: UsersDirectoryPage,
});

type OnbFilter = "all" | "completed" | "in_progress" | "blocked" | "abandoned";

function UsersDirectoryPage() {
  const metrics = useMemo(getUserDirectoryMetrics, []);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<"all" | UserAccountStatus>("all");
  const [profile, setProfile] = useState<"all" | ProfileType>("all");
  const [passport, setPassport] = useState<"all" | PassportStatus>("all");
  const [onb, setOnb] = useState<OnbFilter>("all");
  const [attentionOnly, setAttentionOnly] = useState(false);

  const rows = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return mockUsers.filter((u) => {
      if (status !== "all" && u.accountStatus !== status) return false;
      if (profile !== "all" && u.profileType !== profile) return false;
      if (passport !== "all" && u.passport.status !== passport) return false;
      if (onb !== "all" && u.onboarding.state !== onb) return false;
      if (attentionOnly && u.attentionFlags.length === 0) return false;
      if (!ql) return true;
      const hay = [
        u.fullName,
        u.email,
        u.phone,
        u.displayId,
        u.passport.passportId ?? "",
        u.employer ?? "",
        u.educationInstitution ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(ql);
    });
  }, [q, status, profile, passport, onb, attentionOnly]);

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-4">
      <header>
        <h1 className="text-lg font-semibold tracking-tight text-foreground">Users</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Search candidate accounts, review Trust Passports and take safe administrative actions.
        </p>
      </header>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Metric label="Total users" value={metrics.total} />
        <Metric label="Active" value={metrics.active} />
        <Metric label="Onboarding incomplete" value={metrics.onboardingIncomplete} tone="warning" />
        <Metric label="Verified Passports" value={metrics.passportVerified} />
        <Metric label="Attention required" value={metrics.attentionRequired} tone="warning" />
        <Metric label="Disabled" value={metrics.disabled} />
      </div>

      <WorkspaceSection
        title="Directory"
        description={`${rows.length} of ${mockUsers.length} shown.`}
        action={
          <div className="w-64">
            <AdminSearchField
              value={q}
              onChange={setQ}
              placeholder="Search name, email, phone, employer…"
            />
          </div>
        }
      >
        <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-5">
          <FilterSelect
            label="Account"
            value={status}
            onChange={(v) => setStatus(v as typeof status)}
            options={
              [["all", "All"], ...Object.entries(ACCOUNT_STATUS_LABEL)] as [string, string][]
            }
          />
          <FilterSelect
            label="Onboarding"
            value={onb}
            onChange={(v) => setOnb(v as OnbFilter)}
            options={[
              ["all", "All"],
              ["completed", "Completed"],
              ["in_progress", "In progress"],
              ["blocked", "Blocked"],
              ["abandoned", "Abandoned"],
            ]}
          />
          <FilterSelect
            label="Passport"
            value={passport}
            onChange={(v) => setPassport(v as typeof passport)}
            options={
              [["all", "All"], ...Object.entries(PASSPORT_STATUS_LABEL)] as [string, string][]
            }
          />
          <FilterSelect
            label="Profile type"
            value={profile}
            onChange={(v) => setProfile(v as typeof profile)}
            options={[["all", "All"], ...Object.entries(PROFILE_TYPE_LABEL)] as [string, string][]}
          />
          <label className="flex items-end gap-1.5 text-xs text-foreground">
            <input
              type="checkbox"
              checked={attentionOnly}
              onChange={(e) => setAttentionOnly(e.target.checked)}
              className="size-3.5"
            />
            Attention only
          </label>
        </div>

        {rows.length === 0 ? (
          <EmptyState
            title="No users match"
            description="Adjust filters or clear the search box."
          />
        ) : (
          <>
            {/* Desktop table */}
            <div className="hidden overflow-x-auto rounded-md border border-border md:block">
              <table className="min-w-full divide-y divide-border text-xs">
                <thead className="bg-muted/40 text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 font-medium">User</th>
                    <th className="px-3 py-2 font-medium">Profile</th>
                    <th className="px-3 py-2 font-medium">Account</th>
                    <th className="px-3 py-2 font-medium">Onboarding</th>
                    <th className="px-3 py-2 font-medium">Passport</th>
                    <th className="px-3 py-2 font-medium">Score</th>
                    <th className="px-3 py-2 font-medium">Verifications</th>
                    <th className="px-3 py-2 font-medium">Last active</th>
                    <th className="px-3 py-2 font-medium">Attention</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border bg-background">
                  {rows.map((u) => (
                    <tr key={u.id} className="hover:bg-accent/40">
                      <td className="px-3 py-2">
                        <Link
                          to="/admin/users/$userId"
                          params={{ userId: u.id }}
                          className="flex min-w-0 items-center gap-2 text-foreground hover:underline"
                        >
                          <span className="flex size-6 items-center justify-center rounded-full bg-muted text-[10px] font-semibold">
                            {initialsFor(u)}
                          </span>
                          <span className="min-w-0">
                            <span className="block font-medium">{u.fullName}</span>
                            <span className="block text-[11px] text-muted-foreground">
                              {u.email}
                            </span>
                          </span>
                        </Link>
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {PROFILE_TYPE_LABEL[u.profileType]}
                      </td>
                      <td className="px-3 py-2">
                        <AccountChip status={u.accountStatus} />
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        <OnboardingChip
                          state={u.onboarding.state}
                          pct={u.onboarding.profileCompletionPct}
                        />
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {PASSPORT_STATUS_LABEL[u.passport.status]}
                      </td>
                      <td className="px-3 py-2 tabular-nums text-foreground">
                        {u.trustScore.current}
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {u.trustScore.verifiedSignals} ✓ / {u.trustScore.pendingSignals} ⏳
                      </td>
                      <td className="px-3 py-2 tabular-nums text-muted-foreground">
                        {formatRelativeTime(u.lastActiveAt)}
                      </td>
                      <td className="px-3 py-2">
                        {u.attentionFlags.length === 0 ? (
                          <span className="text-muted-foreground">—</span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-900 ring-1 ring-inset ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60">
                            <AlertTriangle aria-hidden className="size-3" />
                            {u.attentionFlags.length}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Mobile cards */}
            <ul className="grid gap-2 md:hidden">
              {rows.map((u) => (
                <li key={u.id}>
                  <Link
                    to="/admin/users/$userId"
                    params={{ userId: u.id }}
                    className="block rounded-md border border-border bg-background p-3 hover:bg-accent/40"
                  >
                    <div className="flex items-start gap-2">
                      <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-semibold">
                        {initialsFor(u)}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-foreground">{u.fullName}</p>
                        <p className="truncate text-[11px] text-muted-foreground">{u.email}</p>
                        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                          <AccountChip status={u.accountStatus} />
                          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                            {PROFILE_TYPE_LABEL[u.profileType]}
                          </span>
                          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                            Passport: {PASSPORT_STATUS_LABEL[u.passport.status]}
                          </span>
                          {u.attentionFlags.length > 0 ? (
                            <span className="inline-flex items-center gap-1 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-900 ring-1 ring-inset ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60">
                              <AlertTriangle aria-hidden className="size-3" />
                              {u.attentionFlags.length}
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}
      </WorkspaceSection>
    </div>
  );
}

function Metric({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: number;
  tone?: "default" | "warning";
}) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <div className="mt-1 flex items-baseline gap-1">
        <p className="text-xl font-semibold tracking-tight text-foreground">{value}</p>
        {tone === "warning" && value > 0 ? (
          <AlertTriangle aria-hidden className="size-3.5 text-amber-600" />
        ) : null}
      </div>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: Array<[string, string]>;
}) {
  return (
    <label className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
      >
        {options.map(([k, v]) => (
          <option key={k} value={k}>
            {v}
          </option>
        ))}
      </select>
    </label>
  );
}

function AccountChip({ status }: { status: UserAccountStatus }) {
  const map: Record<UserAccountStatus, string> = {
    active:
      "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-900/60",
    pending:
      "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60",
    disabled:
      "bg-zinc-100 text-zinc-800 ring-zinc-200 dark:bg-zinc-800/60 dark:text-zinc-200 dark:ring-zinc-700",
    suspended:
      "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60",
    deletion_requested:
      "bg-orange-50 text-orange-900 ring-orange-200 dark:bg-orange-950/40 dark:text-orange-200 dark:ring-orange-900/60",
  };
  return (
    <span
      className={
        "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset " +
        map[status]
      }
    >
      {ACCOUNT_STATUS_LABEL[status]}
    </span>
  );
}

function OnboardingChip({ state, pct }: { state: UserRecord["onboarding"]["state"]; pct: number }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {state === "completed" ? (
        <ShieldCheck aria-hidden className="size-3 text-emerald-600" />
      ) : null}
      <span className="tabular-nums">{pct}%</span>
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {state.replace("_", " ")}
      </span>
    </span>
  );
}

// Reference so tree-shakers keep imports.
void UsersIcon;
